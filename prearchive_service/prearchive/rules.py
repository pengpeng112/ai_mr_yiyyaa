# -*- coding: utf-8 -*-
"""规则 DSL：加载 + 校验（028 §3.2 v2 完整字段）。

治理字段组（A2）：enabled / version / dept_codes / exempt / min_hours_after_event /
require_source_ready；missing_doc 匹配组（A15）：match.vocab + match.exclude_vocab +
match.template_field；空项黑名单不含「无」（A13，临床"无过敏"为合法填写）。

硬序红线（028 §3.3）：mark_item_fid 一期全部为 null——质控科签字版回填前不得
编写正式规则配置；示例规则仅供开发联调，每条都带 mark_item_note 标注。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .context import KNOWN_SOURCE_LABELS

RULE_TYPES = {"missing_doc", "time_limit", "empty_field", "duplicate"}
SEVERITY_ORDER = {"low": 1, "medium": 2, "high": 3}
EVENT_KINDS = {"admission", "surgery", "discharge"}
MATCH_MODES = {"report_name_fuzzy", "report_name_exact"}
LIST_FIELDS = {"diagnoses", "surgeries"}
TRIGGER_KINDS = {"surgery", "lab_order"}
SURGERY_EVIDENCE_SOURCES = {"his_firstpage_operation", "sm_itf_entry"}

# 临床合法的"无"类填写——禁止进入空项黑名单（A13）
LEGAL_EMPTY_LIKE_VALUES = {"无", "无过敏", "无药物过敏", "未发现", "否认"}

DEFAULT_MARK_ITEM_NOTE = "对应 t_mark_item FID 待质控科签字版回填"


class RuleValidationError(Exception):
    """规则 DSL 校验失败（聚合所有问题一次性报告）。"""


@dataclass
class RuleSpec:
    rule_id: str
    rule_type: str
    name: str
    message: str
    severity: str = "medium"
    deduct_ref: float = 0.0
    mark_item_fid: int = None      # None=待质控科签字版回填（一期示例规则全部 None）
    mark_item_note: str = DEFAULT_MARK_ITEM_NOTE
    enabled: bool = True
    version: str = ""
    dept_codes: list = field(default_factory=list)     # 空=全院
    exempt_scenes: list = field(default_factory=list)  # 豁免场景（自动出院/日间手术…）
    min_hours_after_event: float = 0.0
    require_source_ready: bool = False
    # missing_doc
    trigger: dict = field(default_factory=dict)
    expect: list = field(default_factory=list)
    match: dict = field(default_factory=dict)
    # time_limit
    doc_name: str = ""
    event: str = ""
    threshold_hours: float = 0.0
    # empty_field
    fields: list = field(default_factory=list)
    extra_blacklist_values: list = field(default_factory=list)   # 只允许追加空串类；禁"无"
    # duplicate
    list_field: str = ""
    # 保留原文（新增治理字段向前兼容）
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "rule_type": self.rule_type,
            "name": self.name,
            "message": self.message,
            "severity": self.severity,
            "mark_item_fid": self.mark_item_fid,
            "mark_item_note": self.mark_item_note,
        }


def _require(errors: list, cond: bool, msg: str):
    if not cond:
        errors.append(msg)


def validate_rule(raw: dict, index: int = 0) -> RuleSpec:
    """校验单条规则 DSL，返回 RuleSpec；问题聚在 RuleValidationError。"""
    errors: list = []
    where = f"rule[{index}]"

    rule_id = str(raw.get("rule_id") or "").strip()
    _require(errors, bool(rule_id), f"{where}: rule_id required")
    rule_type = str(raw.get("type") or raw.get("rule_type") or "").strip()
    _require(errors, rule_type in RULE_TYPES,
             f"{where}({rule_id}): type must be one of {sorted(RULE_TYPES)}, got {rule_type!r}")

    name = str(raw.get("name") or "").strip()
    _require(errors, bool(name), f"{where}({rule_id}): name required")
    message = str(raw.get("message") or "").strip()
    _require(errors, bool(message), f"{where}({rule_id}): message required")

    severity = str(raw.get("severity") or "medium").strip()
    _require(errors, severity in SEVERITY_ORDER,
             f"{where}({rule_id}): severity must be low/medium/high, got {severity!r}")

    version = str(raw.get("version") or "").strip()
    _require(errors, bool(version), f"{where}({rule_id}): version required (A2 治理字段)")

    mark_item_fid = raw.get("mark_item_fid")
    if mark_item_fid is not None and not isinstance(mark_item_fid, int):
        errors.append(f"{where}({rule_id}): mark_item_fid must be int or null")

    dept_codes = raw.get("dept_codes") or []
    _require(errors, isinstance(dept_codes, list),
             f"{where}({rule_id}): dept_codes must be list")
    exempt = raw.get("exempt") or {}
    if isinstance(exempt, dict):
        exempt_scenes = list(exempt.get("scenes") or [])
    else:
        exempt_scenes = list(exempt)
        _require(errors, False, f"{where}({rule_id}): exempt must be object {{scenes:[...]}}")
    _require(errors, isinstance(exempt_scenes, list),
             f"{where}({rule_id}): exempt.scenes must be list")

    min_hours = raw.get("min_hours_after_event") or 0
    try:
        min_hours = float(min_hours)
        _require(errors, min_hours >= 0, f"{where}({rule_id}): min_hours_after_event >= 0")
    except (TypeError, ValueError):
        errors.append(f"{where}({rule_id}): min_hours_after_event must be number")
        min_hours = 0.0

    require_ready = bool(raw.get("require_source_ready", False))

    trigger = raw.get("trigger") or {}
    expect = [str(x) for x in (raw.get("expect") or [])]
    match = raw.get("match") or {}

    if rule_type == "missing_doc":
        _require(errors, bool(trigger), f"{where}({rule_id}): missing_doc requires trigger")
        if trigger:
            kind = str(trigger.get("patient_has") or "").strip()
            _require(errors, kind in TRIGGER_KINDS,
                     f"{where}({rule_id}): trigger.patient_has must be one of "
                     f"{sorted(TRIGGER_KINDS)}, got {kind!r}")
            if kind == "lab_order":
                evidence = trigger.get("evidence") or {}
                codes = evidence.get("report_codes") if isinstance(evidence, dict) else None
                _require(errors, isinstance(codes, list) and codes,
                         f"{where}({rule_id}): lab_order trigger requires evidence.report_codes "
                         "(HIS REPORTNAME 数字编码字典，待 P0-3① 回填)")
            if kind == "surgery":
                evidence = trigger.get("evidence") or {}
                src = str((evidence or {}).get("surgery_evidence") or "sm_itf_entry")
                _require(errors, src in SURGERY_EVIDENCE_SOURCES,
                         f"{where}({rule_id}): surgery_evidence must be one of "
                         f"{sorted(SURGERY_EVIDENCE_SOURCES)}")
        _require(errors, bool(expect), f"{where}({rule_id}): missing_doc requires expect list")
        sources = match.get("sources") or []
        _require(errors, bool(sources), f"{where}({rule_id}): match.sources required")
        for s in sources:
            _require(errors, s in KNOWN_SOURCE_LABELS,
                     f"{where}({rule_id}): unknown match source {s!r}")
        by = str(match.get("by") or "report_name_fuzzy")
        _require(errors, by in MATCH_MODES, f"{where}({rule_id}): match.by invalid: {by!r}")
        vocab = match.get("vocab") or {}
        _require(errors, isinstance(vocab, dict),
                 f"{where}({rule_id}): match.vocab must be object")
        for key, words in vocab.items():
            _require(errors, isinstance(words, list) and all(isinstance(w, str) for w in words),
                     f"{where}({rule_id}): match.vocab[{key!r}] must be list[str]")
        exclude_vocab = match.get("exclude_vocab") or []
        _require(errors, isinstance(exclude_vocab, list)
                 and all(isinstance(w, str) for w in exclude_vocab),
                 f"{where}({rule_id}): match.exclude_vocab must be list[str]")

    if rule_type == "time_limit":
        doc_name = str(raw.get("doc_name") or "").strip()
        _require(errors, bool(doc_name), f"{where}({rule_id}): time_limit requires doc_name")
        event = str(raw.get("event") or "").strip()
        _require(errors, event in EVENT_KINDS,
                 f"{where}({rule_id}): event must be one of {sorted(EVENT_KINDS)}, got {event!r}")
        try:
            threshold = float(raw.get("threshold_hours") or 0)
            _require(errors, threshold > 0, f"{where}({rule_id}): threshold_hours > 0")
        except (TypeError, ValueError):
            errors.append(f"{where}({rule_id}): threshold_hours must be number")
            threshold = 0.0

    if rule_type == "empty_field":
        fields_list = [str(x) for x in (raw.get("fields") or [])]
        _require(errors, bool(fields_list), f"{where}({rule_id}): empty_field requires fields")
        extra_blacklist = [str(x) for x in (raw.get("extra_blacklist_values") or [])]
        for value in extra_blacklist:
            _require(errors, value not in LEGAL_EMPTY_LIKE_VALUES,
                     f"{where}({rule_id}): 「{value}」是临床合法填写，禁止加入空项黑名单（A13）")

    if rule_type == "duplicate":
        list_field = str(raw.get("list_field") or "").strip()
        _require(errors, list_field in LIST_FIELDS,
                 f"{where}({rule_id}): list_field must be one of {sorted(LIST_FIELDS)}")

    if errors:
        raise RuleValidationError("; ".join(errors))

    return RuleSpec(
        rule_id=rule_id,
        rule_type=rule_type,
        name=name,
        message=message,
        severity=severity,
        deduct_ref=float(raw.get("deduct_ref") or 0),
        mark_item_fid=mark_item_fid,
        mark_item_note=str(raw.get("mark_item_note") or DEFAULT_MARK_ITEM_NOTE),
        enabled=bool(raw.get("enabled", True)),
        version=version,
        dept_codes=[str(x) for x in dept_codes],
        exempt_scenes=[str(x) for x in exempt_scenes],
        min_hours_after_event=min_hours,
        require_source_ready=require_ready,
        trigger=trigger,
        expect=expect,
        match=match,
        doc_name=str(raw.get("doc_name") or ""),
        event=str(raw.get("event") or ""),
        threshold_hours=float(raw.get("threshold_hours") or 0),
        fields=[str(x) for x in (raw.get("fields") or [])],
        extra_blacklist_values=[str(x) for x in (raw.get("extra_blacklist_values") or [])],
        list_field=str(raw.get("list_field") or ""),
        extra={k: v for k, v in raw.items()
               if k not in {"rule_id", "type", "rule_type", "name", "message", "severity",
                            "deduct_ref", "mark_item_fid", "mark_item_note", "enabled",
                            "version", "dept_codes", "exempt", "min_hours_after_event",
                            "require_source_ready", "trigger", "expect", "match",
                            "doc_name", "event", "threshold_hours", "fields",
                            "extra_blacklist_values", "list_field"}},
    )


def load_rules(path) -> list:
    """加载规则文件并全量校验；rule_id 重复视为配置错误。"""
    file_path = Path(path)
    if not file_path.exists():
        raise RuleValidationError(f"rules file not found: {file_path}")
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuleValidationError(f"rules file invalid JSON: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("rules"), list):
        raise RuleValidationError("rules file must be an object {version, rules:[...]}")

    specs = []
    seen_ids = set()
    for index, item in enumerate(raw["rules"]):
        if not isinstance(item, dict):
            raise RuleValidationError(f"rule[{index}] must be an object")
        spec = validate_rule(item, index)
        if spec.rule_id in seen_ids:
            raise RuleValidationError(f"duplicate rule_id: {spec.rule_id}")
        seen_ids.add(spec.rule_id)
        specs.append(spec)

    version = str(raw.get("version") or "").strip()
    if not version:
        raise RuleValidationError("rules file requires top-level version")
    return specs


def rules_version(path) -> str:
    file_path = Path(path)
    raw = json.loads(file_path.read_text(encoding="utf-8"))
    return str(raw.get("version") or "")


_VERSION_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2}.*$")


def looks_like_signed_version(version: str) -> bool:
    """签字版本号口径：YYYY.MM.DD 前缀（028 §3.3 硬序提示用，不做强校验）。"""
    return bool(_VERSION_RE.match(version or ""))
