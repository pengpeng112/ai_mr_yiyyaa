# -*- coding: utf-8 -*-
"""规则引擎：四类判定器（missing_doc / time_limit / empty_field / duplicate）。

判定次序（每规则）：
  enabled → 科室范围(dept_codes) → 豁免场景(exempt.scenes) →
  类型专属就绪门（require_source_ready 源水位 / min_hours_after_event 时间窗 /
  首页源可用性硬闸门）→ 判定器本体。

skip 不算问题，但记录 notice（原因可审计）；时间窗内不判缺、源水位未就绪不判缺
是负例语义（A2/R15），测试覆盖。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

from .context import (
    SRC_HIS_ITF,
    SRC_JHEMR_BLWS,
    PatientContext,
)
from .rules import SEVERITY_ORDER, RuleSpec


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
    notices: list = field(default_factory=list)    # skip/pass 审计记录
    rule_version: str = ""

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


def _notice(notices: list, rule: RuleSpec, status: str, reason: str, **extra):
    record = {"rule_id": rule.rule_id, "status": status, "reason": reason}
    record.update(extra)
    notices.append(record)


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


# ---------------------------------------------------------------------------
# 四类判定器：返回 (problems, continue_flag)；continue=False 表示已被就绪门跳过
# ---------------------------------------------------------------------------
def evaluate_missing_doc(ctx: PatientContext, rule: RuleSpec, notices: list) -> list:
    trigger = rule.trigger or {}
    kind = str(trigger.get("patient_has") or "")

    if kind == "surgery":
        surgeries = _surgery_evidence(ctx, rule)
        if not surgeries:
            _notice(notices, rule, "pass", "trigger_not_met")
            return []
        event_time = _event_time_for(ctx, "surgery", surgeries)
    elif kind == "lab_order":
        evidence = trigger.get("evidence") or {}
        codes = {str(c) for c in (evidence.get("report_codes") or [])}
        hit = any(e.source == SRC_HIS_ITF and e.report_name in codes
                  for e in ctx.documents)
        if not hit:
            _notice(notices, rule, "pass", "trigger_not_met")
            return []
        event_time = ctx.finished_date_time
    else:
        _notice(notices, rule, "pass", "trigger_kind_unknown")
        return []

    # 时间窗门：事件后 N 小时内不判缺（防"未出报告"误判，A2/R15）
    if rule.min_hours_after_event > 0 and event_time is not None:
        deadline = event_time + timedelta(hours=rule.min_hours_after_event)
        if ctx.effective_check_time() < deadline:
            _notice(notices, rule, "skip", "within_time_window",
                    event_time=event_time.isoformat() if event_time else None,
                    deadline=deadline.isoformat())
            return []

    # 源水位门：require_source_ready 且任一匹配源未就绪 → 不判缺
    # T8-1（R5 极性修正）：paperless_rpa 锚点下该门整体禁用——采集完成时点
    # （≈出院后5天）必然晚于全部文书到达，"源水位≥完成时点"必判未就绪致规则全 skip
    if rule.require_source_ready and not ctx.source_ready_gate_disabled:
        for source_label in (rule.match.get("sources") or []):
            from .collectors import source_is_ready

            if not source_is_ready(ctx, source_label):
                _notice(notices, rule, "skip", "source_not_ready", source=source_label)
                return []

    mode = str(rule.match.get("by") or "report_name_fuzzy")
    vocab = rule.match.get("vocab") or {}
    exclude_vocab = rule.match.get("exclude_vocab") or []
    template_field = str(rule.match.get("template_field") or "progress_template_name")
    sources = set(rule.match.get("sources") or [])

    candidates = [e for e in ctx.documents if e.source in sources]
    missing = []
    matched = {}
    for expected in rule.expect:
        found = None
        for entry in candidates:
            if entry_name_matches(entry.match_name(template_field), expected,
                                  vocab, exclude_vocab, mode):
                found = entry
                break
        if found is None:
            missing.append(expected)
        else:
            matched[expected] = found.report_name

    if not missing:
        _notice(notices, rule, "pass", "all_docs_present",
                matched={k: v for k, v in matched.items()})
        return []

    return [Problem(
        rule_id=rule.rule_id, name=rule.name, rule_type="missing_doc",
        severity=rule.severity, message=rule.message,
        mark_item_fid=rule.mark_item_fid, mark_item_note=rule.mark_item_note,
        deduct_ref=rule.deduct_ref,
        details={"missing_docs": missing, "matched_docs": matched,
                 "candidate_count": len(candidates)},
    )]


def evaluate_time_limit(ctx: PatientContext, rule: RuleSpec, notices: list) -> list:
    vocab = rule.match.get("vocab") or {}
    exclude_vocab = rule.match.get("exclude_vocab") or []
    template_field = str(rule.match.get("template_field") or "progress_template_name")

    event_time = _event_time_for(ctx, rule.event, ctx.surgeries)
    if event_time is None:
        _notice(notices, rule, "pass", "event_time_unknown", event=rule.event)
        return []

    doc_time_source = str(getattr(rule, "doc_time_source", "") or "blws")
    doc_label = ""
    if doc_time_source == "file_index_topic":
        # T2-4（用户拍板口径）：文书完成时间取 jhmr_file_index.topic 标题前缀时间戳
        from .context import parse_topic_datetime

        fi_row = None
        for row in ctx.file_index or []:
            topic = str(row.get("topic") or "")
            file_name = str(row.get("file_name") or "")
            if (entry_name_matches(topic, rule.doc_name, vocab, exclude_vocab)
                    or entry_name_matches(file_name, rule.doc_name, vocab,
                                          exclude_vocab)):
                fi_row = row
                break
        if fi_row is None:
            _notice(notices, rule, "pass", "doc_not_found", doc=rule.doc_name)
            return []
        doc_time = parse_topic_datetime(fi_row.get("topic"))
        doc_label = str(fi_row.get("topic") or fi_row.get("file_name") or "")
        if doc_time is None:
            _notice(notices, rule, "pass", "doc_time_unknown",
                    doc=rule.doc_name, source="file_index_topic")
            return []
    else:
        sources = set(rule.match.get("sources") or [SRC_JHEMR_BLWS])
        candidates = [e for e in ctx.documents if e.source in sources]
        doc = None
        for entry in candidates:
            if entry_name_matches(entry.match_name(template_field), rule.doc_name,
                                  vocab, exclude_vocab):
                doc = entry
                break
        if doc is None:
            _notice(notices, rule, "pass", "doc_not_found", doc=rule.doc_name)
            return []
        if doc.event_time is None:
            _notice(notices, rule, "pass", "doc_time_unknown", doc=rule.doc_name)
            return []
        doc_time = doc.event_time
        doc_label = doc.report_name

    elapsed_hours = (doc_time - event_time).total_seconds() / 3600.0
    if elapsed_hours <= rule.threshold_hours:
        _notice(notices, rule, "pass", "within_limit",
                elapsed_hours=round(elapsed_hours, 2),
                threshold_hours=rule.threshold_hours)
        return []

    return [Problem(
        rule_id=rule.rule_id, name=rule.name, rule_type="time_limit",
        severity=rule.severity, message=rule.message,
        mark_item_fid=rule.mark_item_fid, mark_item_note=rule.mark_item_note,
        deduct_ref=rule.deduct_ref,
        details={"doc": rule.doc_name, "matched_doc": doc_label,
                 "elapsed_hours": round(elapsed_hours, 2),
                 "threshold_hours": rule.threshold_hours, "event": rule.event,
                 "doc_time_source": doc_time_source},
    )]


_EMPTY_SENTINELS = ("", None)


def evaluate_empty_field(ctx: PatientContext, rule: RuleSpec, notices: list) -> list:
    # 首页硬闸门（P0-3④）：源不可用 → 整族条件跳过（028 §3.1 条件覆盖语义）
    if not ctx.firstpage.available:
        _notice(notices, rule, "skip", "firstpage_source_unavailable")
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
        _notice(notices, rule, "pass", "all_fields_filled", fields=values)
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
        _notice(notices, rule, "skip", "firstpage_source_unavailable")
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
        _notice(notices, rule, "pass", "no_duplicate", count=len(raw_values))
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
    """按规则列表评估 PatientContext；规则顺序即报告顺序。"""

    def __init__(self, rules: list, rule_version: str = ""):
        self.rules = [r for r in rules if isinstance(r, RuleSpec)]
        self.rule_version = rule_version

    def evaluate(self, ctx: PatientContext) -> EvaluationOutput:
        output = EvaluationOutput(rule_version=self.rule_version)
        for rule in self.rules:
            try:
                self._evaluate_one(rule, ctx, output)
            except Exception as exc:  # noqa: BLE001 —— 单规则异常不阻断其他规则
                _notice(output.notices, rule, "skip", "evaluator_error",
                        error=f"{type(exc).__name__}: {exc}")
                continue
        return output

    def _evaluate_one(self, rule: RuleSpec, ctx: PatientContext,
                      output: EvaluationOutput) -> None:
        if not rule.enabled:
            _notice(output.notices, rule, "skip", "disabled")
            return
        if rule.dept_codes and ctx.dept_code not in rule.dept_codes:
            _notice(output.notices, rule, "skip", "dept_not_matched",
                    dept_code=ctx.dept_code)
            return
        if rule.exempt_scenes:
            hit_scenes = [s for s in rule.exempt_scenes if ctx.has_scene(s)]
            if hit_scenes:
                _notice(output.notices, rule, "skip", "exempt_scene", scenes=hit_scenes)
                return

        evaluator = {
            "missing_doc": evaluate_missing_doc,
            "time_limit": evaluate_time_limit,
            "empty_field": evaluate_empty_field,
            "duplicate": evaluate_duplicate,
        }.get(rule.rule_type)
        if evaluator is None:
            _notice(output.notices, rule, "skip", "unknown_type")
            return

        problems = evaluator(ctx, rule, output.notices)
        for problem in problems:
            output.problems.append(problem.to_dict())
