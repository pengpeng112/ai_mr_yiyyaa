# -*- coding: utf-8 -*-
"""规则引擎：四类判定器（missing_doc / time_limit / empty_field / duplicate）。

判定次序（每规则）：
  enabled → 科室范围(dept_codes) → 豁免场景(exempt.scenes) →
  类型专属就绪门（require_source_ready 源水位 / min_hours_after_event 时间窗 /
  首页源可用性硬闸门）→ 判定器本体。

046 §3.3 状态口径（F05 修复）：每规则评估产生五态结论（写入 notice["eval"]，
由调用方落 RULE_EVAL）：
  pass            适用且数据完整，已执行且满足；
  fail            适用、数据充分，有明确违例证据（含"已确认必需+源完整+过期限"的缺文书）；
  unknown         源故障/身份关联不确定/事件或文书时间无法可靠取值——不得当合格；
  not_applicable  有可靠证据证明不适用（如手术证据源健康且无手术条目）；
  pending         尚未到检查期限（deadline 记录复查时间）；
  excluded*       disabled/dept_excluded/exempt_scene 等执行范围排除（不计已通过）。

缺文书判 fail 的必要条件（缺一即 unknown/pending）：必需性由规则自身声明
（time_limit 的 doc_name / missing_doc 的 expect 即必需清单）＋ 源完整
（匹配源无采集错误）＋ 已过期限（event_time+threshold/min_hours）。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from .context import (
    SRC_HIS_ITF,
    SRC_JHEMR_BLWS,
    WATERMARK_KEYS,
    PatientContext,
)
from .rules import SEVERITY_ORDER, RuleSpec

# 评估五态（与 closed_loop_models 常量一致；本地定义避免模型层反向依赖）
EVAL_PASS = "pass"
EVAL_FAIL = "fail"
EVAL_UNKNOWN = "unknown"
EVAL_NOT_APPLICABLE = "not_applicable"
EVAL_PENDING = "pending"
EVAL_EXCLUDED = "excluded"


@dataclass
class Problem:
    rule_id: str
    name: str
    rule_type: str
    severity: str
    message: str
    mark_item_fid: int = None
    mark_item_note: str = ""
    deduct_ref: float = 0.0
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = {
            "rule_id": self.rule_id,
            "name": self.name,
            "type": self.rule_type,
            "severity": self.severity,
            "message": self.message,
            "mark_item_fid": self.mark_item_fid,
            "mark_item_note": self.mark_item_note,
            "deduct_ref": self.deduct_ref,
        }
        if self.details:
            data["details"] = self.details
        return data


@dataclass
class EvaluationOutput:
    problems: list = field(default_factory=list)   # list[dict]
    notices: list = field(default_factory=list)    # 审计记录（含 eval 五态，F06）
    rule_version: str = ""
    evaluations: list = field(default_factory=list)  # list[dict] 逐规则评估（046 §3.3）

    @property
    def problem_count(self) -> int:
        return len(self.problems)

    @property
    def severity_top(self) -> str:
        top = ""
        for problem in self.problems:
            if SEVERITY_ORDER.get(problem.get("severity"), 0) > SEVERITY_ORDER.get(top, 0):
                top = problem["severity"]
        return top


def _notice(notices: list, rule: RuleSpec, status: str, reason: str,
            eval_status: str = "", deadline=None, event_instance_id: str = "",
            **extra):
    record = {"rule_id": rule.rule_id, "status": status, "reason": reason}
    if eval_status:
        eval_record = {"status": eval_status, "reason_code": reason,
                       "event_instance_id": event_instance_id}
        if deadline is not None:
            eval_record["deadline"] = deadline.isoformat() \
                if hasattr(deadline, "isoformat") else str(deadline)
        eval_record.update({k: v for k, v in extra.items()
                            if k not in ("matched",)})
        record["eval"] = eval_record
    record.update(extra)
    notices.append(record)
    return record


def _source_keys(source_labels) -> list:
    """源标签 → 水位/采集错误短键。"""
    return sorted({WATERMARK_KEYS.get(s, s) for s in source_labels or []})


def absence_conclusive(ctx: PatientContext, source_labels) -> bool:
    """「能否得出不存在结论」检查（046 §5.1）：匹配源无采集错误才允许缺文书定性。

    RPA 模式水位门禁用（T8-1/R5）不影响本判定——源故障（collect_errors）仍然
    阻止缺失结论。
    """
    keys = _source_keys(source_labels)
    return all(key not in (ctx.collect_errors or {}) for key in keys)


def _source_errors_for(ctx: PatientContext, source_labels) -> dict:
    keys = _source_keys(source_labels)
    return {k: ctx.collect_errors[k] for k in keys if k in ctx.collect_errors}


# ---------------------------------------------------------------------------
# 名称规范化与模糊匹配（duplicate / missing_doc 共用）
# ---------------------------------------------------------------------------
_SERIAL_PREFIX_RE = re.compile(r"^\s*(?:\(?\d{1,3}[\.\、\)）])\s*")
_CIRCLED_PREFIX_RE = re.compile(r"^\s*[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮]\s*")


def normalize_name(value: str) -> str:
    """名称归一：圆圈序号剥离（NFKC 前）、全角→半角、去空白、前导序号剥离。"""
    text = str(value or "")
    text = _CIRCLED_PREFIX_RE.sub("", text)          # ①NFKC 会变成普通数字，先剥
    text = unicodedata.normalize("NFKC", text).strip()
    text = _SERIAL_PREFIX_RE.sub("", text)
    text = text.strip()
    return re.sub(r"\s+", "", text)


def entry_name_matches(entry_name: str, expected: str, vocab: dict,
                       exclude_vocab: list, mode: str = "report_name_fuzzy") -> bool:
    """expect 项与条目名的匹配：词表模糊（默认）或精确。

    exclude_vocab 命中一票否决（v_blws 知情同意书/查房记录误命中防护，A15）。
    """
    name = str(entry_name or "")
    if any(word and word in name for word in (exclude_vocab or [])):
        return False
    if mode == "report_name_exact":
        return normalize_name(name) == normalize_name(expected)
    keywords = vocab.get(expected) or [expected]
    normalized = normalize_name(name)
    for keyword in keywords:
        candidate = normalize_name(keyword)
        if candidate and candidate in normalized:
            return True
    return False


def _pair_docs_to_events(event_times: list, doc_slots: list) -> list:
    """事件→文书贪心配对（046 T3 多手术事件关联）。

    event_times：事件时间列表（None=时间未知，排末尾）；doc_slots：[(key, time|None)]。
    每个事件取「时间≥事件时间的最早未被占用文书」，无则取最近的未占用文书，
    再无则 None；同一份文书不得被两个事件共享（多次手术不能一份文书蒙混，046 §7）。
    返回与 event_times 等长的 [doc_key_or_None]。
    """
    unassigned = sorted(range(len(doc_slots)),
                        key=lambda i: (doc_slots[i][1] is None,
                                       doc_slots[i][1] or datetime.max))
    result = []
    for event_time in event_times:
        chosen = None
        if event_time is not None:
            after = [i for i in unassigned if doc_slots[i][1] is not None
                     and doc_slots[i][1] >= event_time]
            if after:
                chosen = min(after, key=lambda i: doc_slots[i][1])
        if chosen is None and unassigned:
            known = [i for i in unassigned if doc_slots[i][1] is not None]
            if known and event_time is not None:
                chosen = min(known, key=lambda i: abs(
                    (doc_slots[i][1] - event_time).total_seconds()))
            else:
                chosen = unassigned[0]
        if chosen is not None:
            unassigned.remove(chosen)
            result.append(doc_slots[chosen][0])
        else:
            result.append(None)
    return result


def _surgery_instances(surgeries: list) -> list:
    """手术事件实例：按时间排序（时间未知排末尾），编号 1..n。"""
    ordered = sorted(
        enumerate(surgeries, start=1),
        key=lambda pair: (pair[1].surgery_time is None,
                          pair[1].surgery_time or datetime.max))
    return [(f"surgery-{i}", s.surgery_time) for i, s in ordered]


def _event_time_for(ctx: PatientContext, kind: str,
                    surgeries: list) -> Optional[object]:
    if kind == "admission":
        return ctx.admit_time
    if kind == "discharge":
        return ctx.discharge_time or ctx.finished_date_time
    if kind == "surgery":
        times = [s.surgery_time for s in surgeries if s.surgery_time]
        return min(times) if times else None
    return None


def _surgery_evidence(ctx: PatientContext, rule: RuleSpec) -> list:
    evidence = (rule.trigger.get("evidence") or {}) if rule.trigger else {}
    want = str(evidence.get("surgery_evidence") or "sm_itf_entry")
    return [s for s in ctx.surgeries if not want or s.source == want]


# 手术证据源名 → 源标签（水位/采集错误键映射用）
_SURGERY_EVIDENCE_LABELS = {
    "sm_itf_entry": "sm_itf",
    "his_firstpage_operation": "his_firstpage",
}


def _surgery_evidence_all(ctx: PatientContext, rule: RuleSpec) -> list:
    """时限规则用的手术事件全集：不限证据源（每次手术都需各自文书）。"""
    return list(ctx.surgeries)


def _surgery_evidence_label(trigger: dict) -> str:
    return _SURGERY_EVIDENCE_LABELS.get(
        str((trigger.get("evidence") or {}).get("surgery_evidence")
            or "sm_itf_entry"), "sm_itf")


# ---------------------------------------------------------------------------
# 四类判定器：返回 (problems, continue_flag)；continue=False 表示已被就绪门跳过
# ---------------------------------------------------------------------------
def evaluate_missing_doc(ctx: PatientContext, rule: RuleSpec, notices: list) -> list:
    trigger = rule.trigger or {}
    kind = str(trigger.get("patient_has") or "")
    doc_sources = set(rule.match.get("sources") or [])

    if kind == "surgery":
        surgeries = _surgery_evidence(ctx, rule)
        if not surgeries:
            # 046 §3.3：无手术证据≠无手术——证据源健康才可 not_applicable
            evidence_src = _surgery_evidence_label(trigger)
            if absence_conclusive(ctx, [evidence_src]):
                _notice(notices, rule, "not_applicable", "trigger_not_met",
                        eval_status=EVAL_NOT_APPLICABLE)
            else:
                _notice(notices, rule, "unknown", "trigger_not_met_source_error",
                        eval_status=EVAL_UNKNOWN,
                        source_errors=_source_errors_for(ctx, [evidence_src]))
            return []
        event_time = _event_time_for(ctx, "surgery", surgeries)
    elif kind == "lab_order":
        evidence = trigger.get("evidence") or {}
        codes = {str(c) for c in (evidence.get("report_codes") or [])}
        hit = any(e.source == SRC_HIS_ITF and e.report_name in codes
                  for e in ctx.documents)
        if not hit:
            if absence_conclusive(ctx, [SRC_HIS_ITF]):
                _notice(notices, rule, "not_applicable", "trigger_not_met",
                        eval_status=EVAL_NOT_APPLICABLE)
            else:
                _notice(notices, rule, "unknown", "trigger_not_met_source_error",
                        eval_status=EVAL_UNKNOWN,
                        source_errors=_source_errors_for(ctx, [SRC_HIS_ITF]))
            return []
        event_time = ctx.finished_date_time
    elif kind == "report_expected":
        # T8-4（R8）：系统推送类报告"应出未出"——存在申请/医嘱类条目即触发；
        # always=true 兜底（无申请证据也检查，配合 min_hours_after_event 时间窗）
        evidence = trigger.get("evidence") or {}
        if bool((evidence or {}).get("always", False)):
            event_time = ctx.finished_date_time
        else:
            codes = {str(c) for c in ((evidence or {}).get("report_codes") or [])}
            trigger_sources = set((evidence or {}).get("trigger_sources") or [])
            hit_entries = [e for e in ctx.documents
                           if (not trigger_sources or e.source in trigger_sources)
                           and (not codes or e.report_name in codes)]
            if not hit_entries:
                if absence_conclusive(ctx, trigger_sources or list(codes)):
                    _notice(notices, rule, "not_applicable", "trigger_not_met",
                            eval_status=EVAL_NOT_APPLICABLE)
                else:
                    _notice(notices, rule, "unknown", "trigger_not_met_source_error",
                            eval_status=EVAL_UNKNOWN)
                return []
            times = [e.time_basis() for e in hit_entries if e.time_basis()]
            event_time = max(times) if times else ctx.finished_date_time
    else:
        _notice(notices, rule, "excluded", "trigger_kind_unknown",
                eval_status=EVAL_EXCLUDED)
        return []

    # 源水位门：require_source_ready 且任一匹配源未就绪 → 不判缺
    # T8-1（R5 极性修正）：paperless_rpa 锚点下该门整体禁用——采集完成时点
    # （≈出院后5天）必然晚于全部文书到达，"源水位≥完成时点"必判未就绪致规则全 skip
    if rule.require_source_ready and not ctx.source_ready_gate_disabled:
        for source_label in (rule.match.get("sources") or []):
            from .collectors import source_is_ready

            if not source_is_ready(ctx, source_label):
                _notice(notices, rule, "unknown", "source_not_ready",
                        eval_status=EVAL_UNKNOWN, source=source_label)
                return []

    mode = str(rule.match.get("by") or "report_name_fuzzy")
    vocab = rule.match.get("vocab") or {}
    exclude_vocab = rule.match.get("exclude_vocab") or []
    template_field = str(rule.match.get("template_field") or "progress_template_name")
    sources = set(rule.match.get("sources") or [])

    candidates = [e for e in ctx.documents if e.source in sources]
    # 匹配池：每个 expect 名 → 全部命中条目索引（供多事件分配，046 T3）
    pools = {
        expected: [i for i, entry in enumerate(candidates)
                   if entry_name_matches(entry.match_name(template_field),
                                         expected, vocab, exclude_vocab, mode)]
        for expected in rule.expect
    }

    # 046 F05：缺文书定性三条件——必需（expect 即声明）+ 源完整 + 已过期限。
    # 源有采集错误 → unknown（不能断言"不存在"）；全局一次性判定。
    source_errors = _source_errors_for(ctx, sources)
    if source_errors:
        _notice(notices, rule, "unknown", "missing_doc_source_error",
                eval_status=EVAL_UNKNOWN, source_errors=source_errors)
        return []

    # 事件实例（046 T3 多手术事件关联）：每实例独立判定 + 时间窗 pending
    if kind == "surgery":
        instances = _surgery_instances(surgeries)
    else:
        instances = [(f"{kind}-1", event_time)]

    used: set = set()
    problems = []
    for event_id, stime in instances:
        if stime is None and rule.min_hours_after_event > 0:
            # 时间未知且需要时间窗 → unknown；min_hours=0 时存在性判定不受影响
            _notice(notices, rule, "unknown", "event_time_unknown",
                    eval_status=EVAL_UNKNOWN, event_instance_id=event_id,
                    event=kind)
            continue
        if stime is not None and rule.min_hours_after_event > 0:
            deadline = stime + timedelta(hours=rule.min_hours_after_event)
            if ctx.effective_check_time() < deadline:
                _notice(notices, rule, "pending", "within_time_window",
                        eval_status=EVAL_PENDING, deadline=deadline,
                        event_instance_id=event_id,
                        event_time=stime.isoformat())
                continue

        missing = []
        matched = {}
        for expected in rule.expect:
            avail = [(i, candidates[i].time_basis())
                     for i in pools[expected] if i not in used]
            if not avail:
                missing.append(expected)
                continue
            assigned = _pair_docs_to_events([stime], avail)[0]
            if assigned is None:
                missing.append(expected)
            else:
                used.add(assigned)
                matched[expected] = candidates[assigned].report_name

        if not missing:
            _notice(notices, rule, "pass", "all_docs_present",
                    eval_status=EVAL_PASS, event_instance_id=event_id,
                    matched={k: v for k, v in matched.items()})
            continue
        problems.append(Problem(
            rule_id=rule.rule_id, name=rule.name, rule_type="missing_doc",
            severity=rule.severity, message=rule.message,
            mark_item_fid=rule.mark_item_fid, mark_item_note=rule.mark_item_note,
            deduct_ref=rule.deduct_ref,
            details={"missing_docs": missing, "matched_docs": matched,
                     "candidate_count": len(candidates),
                     "event_instance_id": event_id,
                     "event_time": stime.isoformat() if stime else None},
        ))
    return problems


def evaluate_time_limit(ctx: PatientContext, rule: RuleSpec, notices: list) -> list:
    """时限判定（046 F05 修复）：

    - event_time 不可靠 → unknown（不再 pass）；
    - 文书缺失：期限未到 → pending（登记复查时间）；已过期限且文书源健康 → fail
      （time_limit 规则自身声明该文书必需）；源有采集错误 → unknown；
    - 文书时间不可靠 → unknown（不再 pass）；
    - 超时限 → fail。
    """
    vocab = rule.match.get("vocab") or {}
    exclude_vocab = rule.match.get("exclude_vocab") or []
    template_field = str(rule.match.get("template_field") or "progress_template_name")

    doc_sources = set(rule.match.get("sources") or [SRC_JHEMR_BLWS])
    source_errors = _source_errors_for(ctx, doc_sources)

    # 事件实例（046 T3）：手术事件逐实例配对；admission/discharge 单实例
    if rule.event == "surgery":
        all_surgeries = _surgery_evidence_all(ctx, rule)
        if not all_surgeries:
            # 无手术事件：证据源健康 → not_applicable；源故障 → unknown
            if absence_conclusive(ctx, ["sm_itf"]):
                _notice(notices, rule, "not_applicable", "trigger_not_met",
                        eval_status=EVAL_NOT_APPLICABLE)
            else:
                _notice(notices, rule, "unknown", "trigger_not_met_source_error",
                        eval_status=EVAL_UNKNOWN,
                        source_errors=_source_errors_for(ctx, ["sm_itf"]))
            return []
        instances = _surgery_instances(all_surgeries)
    else:
        event_time = _event_time_for(ctx, rule.event, ctx.surgeries)
        instances = [(f"{rule.event}-1", event_time)]

    doc_time_source = str(getattr(rule, "doc_time_source", "") or "blws")

    # 匹配文书池（或 file_index 行池）
    if doc_time_source == "file_index_topic":
        from .context import parse_topic_datetime

        matched_rows = []
        for row in ctx.file_index or []:
            topic = str(row.get("topic") or "")
            file_name = str(row.get("file_name") or "")
            if (entry_name_matches(topic, rule.doc_name, vocab, exclude_vocab)
                    or entry_name_matches(file_name, rule.doc_name, vocab,
                                          exclude_vocab)):
                matched_rows.append(row)
        slots = [(i, parse_topic_datetime(row.get("topic")))
                 for i, row in enumerate(matched_rows)]
    else:
        candidates = [e for e in ctx.documents if e.source in doc_sources]
        matched_idx = [i for i, entry in enumerate(candidates)
                       if entry_name_matches(entry.match_name(template_field),
                                             rule.doc_name, vocab, exclude_vocab)]
        slots = [(i, candidates[i].event_time) for i in matched_idx]
        matched_rows = None

    problems = []
    for event_id, event_time in instances:
        if event_time is None:
            _notice(notices, rule, "unknown", "event_time_unknown",
                    eval_status=EVAL_UNKNOWN, event=rule.event,
                    event_instance_id=event_id)
            continue
        deadline = event_time + timedelta(hours=rule.threshold_hours)
        assigned = _pair_docs_to_events([event_time], slots)[0] if slots else None
        # 已分配的文书不能被下一事件复用（多手术各配各的文书，046 §7）
        if assigned is not None:
            slots = [s for s in slots if s[0] != assigned]

        if assigned is None:
            # 046 F05：缺文书三条件分流（每事件实例独立）
            if ctx.effective_check_time() < deadline:
                _notice(notices, rule, "pending", "doc_not_found",
                        eval_status=EVAL_PENDING, deadline=deadline,
                        doc=rule.doc_name, event_instance_id=event_id)
            elif source_errors:
                _notice(notices, rule, "unknown", "doc_not_found_source_error",
                        eval_status=EVAL_UNKNOWN, source_errors=source_errors,
                        doc=rule.doc_name, event_instance_id=event_id)
            else:
                # 已确认必需（规则声明）+ 源完整 + 过期限 → 缺文书=缺陷（§7 场景1）
                _notice(notices, rule, "fail", "doc_not_found",
                        eval_status=EVAL_FAIL, doc=rule.doc_name,
                        deadline=deadline.isoformat(),
                        event_instance_id=event_id)
                problems.append(Problem(
                    rule_id=rule.rule_id, name=rule.name, rule_type="time_limit",
                    severity=rule.severity, message=rule.message,
                    mark_item_fid=rule.mark_item_fid,
                    mark_item_note=rule.mark_item_note,
                    deduct_ref=rule.deduct_ref,
                    details={"doc": rule.doc_name, "matched_doc": "",
                             "elapsed_hours": None,
                             "threshold_hours": rule.threshold_hours,
                             "event": rule.event,
                             "missing": True,
                             "deadline": deadline.isoformat(),
                             "event_instance_id": event_id},
                ))
            continue

        if doc_time_source == "file_index_topic":
            row = matched_rows[assigned]
            doc_time = parse_topic_datetime(row.get("topic"))
            doc_label = str(row.get("topic") or row.get("file_name") or "")
            if doc_time is None:
                _notice(notices, rule, "unknown", "doc_time_unknown",
                        eval_status=EVAL_UNKNOWN, doc=rule.doc_name,
                        source="file_index_topic", event_instance_id=event_id)
                continue
        else:
            entry = candidates[assigned]
            doc_time = entry.event_time
            doc_label = entry.report_name
            if doc_time is None:
                _notice(notices, rule, "unknown", "doc_time_unknown",
                        eval_status=EVAL_UNKNOWN, doc=rule.doc_name,
                        event_instance_id=event_id)
                continue

        elapsed_hours = (doc_time - event_time).total_seconds() / 3600.0
        if elapsed_hours <= rule.threshold_hours:
            _notice(notices, rule, "pass", "within_limit",
                    eval_status=EVAL_PASS,
                    elapsed_hours=round(elapsed_hours, 2),
                    threshold_hours=rule.threshold_hours,
                    event_instance_id=event_id)
            continue
        problems.append(Problem(
            rule_id=rule.rule_id, name=rule.name, rule_type="time_limit",
            severity=rule.severity, message=rule.message,
            mark_item_fid=rule.mark_item_fid, mark_item_note=rule.mark_item_note,
            deduct_ref=rule.deduct_ref,
            details={"doc": rule.doc_name, "matched_doc": doc_label,
                     "elapsed_hours": round(elapsed_hours, 2),
                     "threshold_hours": rule.threshold_hours, "event": rule.event,
                     "doc_time_source": doc_time_source,
                     "event_instance_id": event_id},
        ))
    return problems


_EMPTY_SENTINELS = ("", None)


def evaluate_empty_field(ctx: PatientContext, rule: RuleSpec, notices: list) -> list:
    # 首页硬闸门（P0-3④）：源不可用 → unknown（046 §3.3：源故障不得当合格）
    if not ctx.firstpage.available:
        _notice(notices, rule, "unknown", "firstpage_source_unavailable",
                eval_status=EVAL_UNKNOWN)
        return []

    blacklist = set(_EMPTY_SENTINELS) | {str(x) for x in rule.extra_blacklist_values}
    empty_fields = []
    values = {}
    for field_name in rule.fields:
        value = getattr(ctx.firstpage, field_name, None)
        values[field_name] = value
        if value in _EMPTY_SENTINELS or (isinstance(value, str)
                                         and value.strip() in blacklist):
            # '无' 不是空（A13）——它不等于 '' 且不在合法黑名单，天然通过
            empty_fields.append(field_name)

    if not empty_fields:
        _notice(notices, rule, "pass", "all_fields_filled",
                eval_status=EVAL_PASS, fields=values)
        return []

    return [Problem(
        rule_id=rule.rule_id, name=rule.name, rule_type="empty_field",
        severity=rule.severity, message=rule.message,
        mark_item_fid=rule.mark_item_fid, mark_item_note=rule.mark_item_note,
        deduct_ref=rule.deduct_ref,
        details={"empty_fields": empty_fields},
    )]


def evaluate_duplicate(ctx: PatientContext, rule: RuleSpec, notices: list) -> list:
    if not ctx.firstpage.available:
        _notice(notices, rule, "unknown", "firstpage_source_unavailable",
                eval_status=EVAL_UNKNOWN)
        return []

    raw_values = getattr(ctx.firstpage, rule.list_field, None) or []
    groups: dict = {}
    for raw in raw_values:
        normalized = normalize_name(raw)
        if not normalized:
            continue
        groups.setdefault(normalized, []).append(str(raw))

    duplicates = {k: v for k, v in groups.items() if len(v) > 1}
    if not duplicates:
        _notice(notices, rule, "pass", "no_duplicate",
                eval_status=EVAL_PASS, count=len(raw_values))
        return []

    return [Problem(
        rule_id=rule.rule_id, name=rule.name, rule_type="duplicate",
        severity=rule.severity, message=rule.message,
        mark_item_fid=rule.mark_item_fid, mark_item_note=rule.mark_item_note,
        deduct_ref=rule.deduct_ref,
        details={"duplicates": duplicates, "list_field": rule.list_field},
    )]


# ---------------------------------------------------------------------------
# 引擎主体
# ---------------------------------------------------------------------------
class RuleEngine:
    """按规则列表评估 PatientContext；规则顺序即报告顺序。

    046 T4/F04：rules 可传 RefreshableRuleSet（每患者 evaluate 时取一次 TTL
    快照，发布后下一任务读到新版本，无需重启）。
    """

    def __init__(self, rules: list, rule_version: str = "", dept_matcher=None):
        self._rules_provider = None
        if hasattr(rules, "snapshot"):
            self._rules_provider = rules
            rules, rule_version = rules.snapshot()
        self.rules = [r for r in rules if isinstance(r, RuleSpec)]
        self.rule_version = rule_version
        self.dept_matcher = dept_matcher

    def _current_rules(self):
        if self._rules_provider is not None:
            specs, version = self._rules_provider.snapshot()
            self.rule_version = version
            return [r for r in specs if isinstance(r, RuleSpec)]
        return self.rules

    def evaluate(self, ctx: PatientContext) -> EvaluationOutput:
        rules = self._current_rules()   # 先取快照：rule_version 跟随本次快照
        output = EvaluationOutput(rule_version=self.rule_version)
        for rule in rules:
            try:
                self._evaluate_one(rule, ctx, output)
            except Exception as exc:  # noqa: BLE001 —— 单规则异常不阻断其他规则
                _notice(output.notices, rule, "unknown", "evaluator_error",
                        eval_status=EVAL_UNKNOWN,
                        error=f"{type(exc).__name__}: {exc}")
                continue
        return output

    def _evaluate_one(self, rule: RuleSpec, ctx: PatientContext,
                      output: EvaluationOutput) -> None:
        if not rule.enabled:
            _notice(output.notices, rule, "excluded", "disabled",
                    eval_status=EVAL_EXCLUDED)
            output.evaluations.append(self._gate_eval(rule, "disabled"))
            return
        dept_matched = ctx.dept_code in rule.dept_codes
        if rule.dept_codes and self.dept_matcher is not None:
            dept_matched = bool(self.dept_matcher(
                ctx.dept_code, ctx.dept_name, rule.dept_codes))
        if rule.dept_codes and not dept_matched:
            _notice(output.notices, rule, "excluded", "dept_not_matched",
                    eval_status=EVAL_EXCLUDED, dept_code=ctx.dept_code)
            output.evaluations.append(self._gate_eval(rule, "dept_excluded",
                                                      dept_code=ctx.dept_code))
            return
        if rule.exempt_scenes:
            hit_scenes = [s for s in rule.exempt_scenes if ctx.has_scene(s)]
            if hit_scenes:
                _notice(output.notices, rule, "excluded", "exempt_scene",
                        eval_status=EVAL_EXCLUDED, scenes=hit_scenes)
                output.evaluations.append(self._gate_eval(rule, "exempt_scene",
                                                          scenes=hit_scenes))
                return

        evaluator = {
            "missing_doc": evaluate_missing_doc,
            "time_limit": evaluate_time_limit,
            "empty_field": evaluate_empty_field,
            "duplicate": evaluate_duplicate,
        }.get(rule.rule_type)
        if evaluator is None:
            _notice(output.notices, rule, "excluded", "unknown_type",
                    eval_status=EVAL_EXCLUDED)
            output.evaluations.append(self._gate_eval(rule, "unknown_type"))
            return

        rule_notices_before = len(output.notices)
        problems = evaluator(ctx, rule, output.notices)
        for problem in problems:
            output.problems.append(problem.to_dict())

        # 046 §3.3/F06：逐规则评估记录（evaluations）——fail 来自 problems，
        # 其余状态来自判定器写入 notice 的 eval 块；两者都不在时兜底 unknown。
        self._collect_evaluations(rule, output, problems, rule_notices_before)

    @staticmethod
    def _gate_eval(rule: RuleSpec, exclusion_reason: str, **evidence) -> dict:
        return {"rule_id": rule.rule_id, "rule_version": rule.version,
                "fid": getattr(rule, "mark_item_fid", None),
                "status": EVAL_EXCLUDED, "is_excluded": True,
                "exclusion_reason": exclusion_reason, "reason_code": "",
                "event_instance_id": "", "evidence": _shrink_evidence(evidence)}

    @staticmethod
    def _collect_evaluations(rule: RuleSpec, output: EvaluationOutput,
                             problems: list, notices_start: int) -> None:
        """合并 problems 与 notice eval 块 → 逐实例评估记录。

        多事件实例下一条规则可能同时有 pass 实例（notice）与 fail 实例（problem）；
        fail notice（如 time_limit 缺文书）与 problem 同实例去重，不双记。
        """
        fid = getattr(rule, "mark_item_fid", None)
        base = {"rule_id": rule.rule_id, "rule_version": rule.version,
                "fid": fid, "is_excluded": False}

        notice_evals = []
        for notice in output.notices[notices_start:]:
            if not isinstance(notice.get("eval"), dict):
                continue
            eval_block = dict(notice["eval"])
            status = eval_block.pop("status")
            excluded = status == EVAL_EXCLUDED
            notice_evals.append({
                **base, "status": status, "is_excluded": excluded,
                "exclusion_reason": notice.get("reason", "") if excluded else "",
                "reason_code": eval_block.pop("reason_code", ""),
                "event_instance_id": eval_block.pop("event_instance_id", ""),
                "evidence": _shrink_evidence(eval_block),
                "deadline": eval_block.pop("deadline", None),
            })

        problem_evals = []
        for problem in problems:
            details = problem.details or {}
            problem_evals.append({
                **base, "status": EVAL_FAIL,
                "reason_code": "required_doc_missing" if details.get("missing")
                               else problem.rule_type,
                "event_instance_id": str(details.get("event_instance_id") or ""),
                "evidence": _shrink_evidence(details),
            })

        if not notice_evals and not problem_evals:
            output.evaluations.append({
                **base, "status": EVAL_UNKNOWN, "reason_code": "no_eval_record",
                "event_instance_id": "", "evidence": {}})
            return

        # 同实例 fail 已有 notice 记录时去重（notice 证据更完整）
        fail_notice_keys = {(e["event_instance_id"], e["status"])
                            for e in notice_evals}
        output.evaluations.extend(notice_evals)
        for pe in problem_evals:
            if (pe["event_instance_id"], EVAL_FAIL) not in fail_notice_keys:
                output.evaluations.append(pe)


def _shrink_evidence(details: dict) -> dict:
    """最小证据：只留标量/短列表，长文本截断（不携带病历正文）。"""
    out = {}
    for key, value in (details or {}).items():
        if isinstance(value, (str, int, float, bool)) and len(str(value)) <= 200:
            out[key] = value
        elif isinstance(value, list) and len(value) <= 20 \
                and all(isinstance(x, (str, int, float)) for x in value):
            out[key] = value
        elif isinstance(value, dict) and len(value) <= 20:
            out[key] = {k: v for k, v in value.items()
                        if isinstance(v, (str, int, float, bool))}
    return out
