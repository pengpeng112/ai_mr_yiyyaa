# -*- coding: utf-8 -*-
"""规则中心服务层（039 T2）：状态机 / 导入 / file-compare-registry 三模式 / 治理配置。

状态机（039 §5.2）：
    draft → validated → approved → published → retired
      │                                   └─ rollback：指针指回旧 published 版本
      └─ 编辑（仅 draft，乐观锁）

硬规则：
- published 内容不可修改（仓储层 status 守卫）；运行时只读指针，不读 draft；
- 发布/回滚写审计（操作者/时间/原因/前后版本/request_id）；
- FID 未确认（mark_item_fid 为 null）的 paperless_t_mark_item 来源规则可保存草稿，
  但不得发布为 deduct_ref>0 的自动扣分规则；
- 默认一切规则只提示（deduct_ref=0 / 不阻断）——治理开关见 governance。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from .rule_models import (
    RULE_STATUS_APPROVED,
    RULE_STATUS_DRAFT,
    RULE_STATUS_PUBLISHED,
    RULE_STATUS_RETIRED,
    RULE_STATUS_VALIDATED,
    RuleVersionRow,
    canonical_json,
    content_sha256,
)
from .rule_repository import (
    RuleConflictError,
    RuleNotFoundError,
    RuleRepository,
)
from .rules import RuleValidationError, load_rules_multi, validate_rule

logger = logging.getLogger("prearchive.rulecenter")

RULE_MODES = ("file", "compare", "registry")

# DSL 之外禁止出现的键（防把规则编辑器变代码执行器，039 §5.3）
_FORBIDDEN_KEYS = ("sql", "script", "python", "javascript", "jinja", "eval",
                   "exec", "shell", "url", "http_url", "command", "template_code")
_FORBIDDEN_PATTERN_PREFIXES = ("eval(", "exec(", "import ", "__import__",
                               "subprocess", "os.system", "<script", "javascript:")


@dataclass
class Actor:
    id: str = ""
    name: str = ""
    permissions: List[str] = field(default_factory=list)

    def has(self, permission: str) -> bool:
        return permission in self.permissions or "*" in self.permissions


def scan_dangerous_content(rule_dict: dict) -> List[str]:
    """规则内容危险扫描：禁止任意 SQL/Python/JS/Jinja/eval/Shell/URL。"""
    problems: List[str] = []

    def _walk(value, path):
        if isinstance(value, dict):
            for key, sub in value.items():
                key_l = str(key).lower()
                if key_l in _FORBIDDEN_KEYS:
                    problems.append(f"forbidden key {path}.{key}")
                _walk(sub, f"{path}.{key}")
        elif isinstance(value, list):
            for idx, sub in enumerate(value):
                _walk(sub, f"{path}[{idx}]")
        elif isinstance(value, str):
            for prefix in _FORBIDDEN_PATTERN_PREFIXES:
                if prefix in value.lower():
                    problems.append(f"dangerous pattern {prefix!r} at {path}")

    _walk(rule_dict, "$")
    return problems


def validate_rule_content(rule_dict: dict) -> dict:
    """完整校验：既有 DSL 校验 + 危险内容扫描；返回错误列表（空=通过）。"""
    errors: List[str] = []
    try:
        validate_rule(rule_dict)
    except RuleValidationError as exc:
        errors.append(str(exc))
    errors.extend(scan_dangerous_content(rule_dict))
    return errors


class RuleService:
    def __init__(self, repository: RuleRepository, *,
                 require_separate_approver: bool = False):
        self.repository = repository
        self.require_separate_approver = bool(require_separate_approver)

    # ---- 生命周期 ----

    def create_draft(self, rule_dict: dict, actor: Actor, *,
                     domain: str = "medical_record", track: str = "main",
                     origin: str = "manual", based_on_version: str = "",
                     request_id: str = "") -> RuleVersionRow:
        errors = validate_rule_content(rule_dict)
        if errors:
            raise RuleValidationError("; ".join(errors))
        rule_key = str(rule_dict["rule_id"])
        existing = self.repository.latest_version(rule_key)
        if existing is not None and existing.rule_version == str(rule_dict.get("version")):
            raise RuleConflictError(
                f"rule {rule_key} already has version {existing.rule_version}; "
                "bump the version field to create a new version")
        row = self.repository.insert_version(
            rule_key=rule_key,
            domain=domain, track=track, origin=origin,
            rule_version=str(rule_dict.get("version") or ""),
            set_version="",
            status=RULE_STATUS_DRAFT,
            content_json=canonical_json(rule_dict),
            content_sha256=content_sha256(rule_dict),
            created_by=actor.id,
        )
        self.repository.append_audit(
            action="create_draft", rule_key=rule_key, version_to=row.rule_version,
            actor_id=actor.id, actor_name=actor.name, request_id=request_id,
            detail={"sha256": row.content_sha256})
        return row

    def update_draft(self, rule_key: str, rule_version: str, rule_dict: dict,
                     expect_edit_version: int, actor: Actor,
                     request_id: str = "") -> RuleVersionRow:
        errors = validate_rule_content(rule_dict)
        if errors:
            raise RuleValidationError("; ".join(errors))
        if str(rule_dict.get("rule_id")) != rule_key:
            raise RuleValidationError("rule_id cannot be changed by draft edit")
        if str(rule_dict.get("version")) != rule_version:
            raise RuleValidationError("draft edit cannot change version; create a new version")
        row = self.repository.update_draft_content(
            rule_key, rule_version, rule_dict, expect_edit_version)
        self.repository.append_audit(
            action="update_draft", rule_key=rule_key, version_to=rule_version,
            actor_id=actor.id, actor_name=actor.name, request_id=request_id,
            detail={"sha256": row.content_sha256,
                    "edit_version": row.draft_edit_version})
        return row

    def validate(self, rule_key: str, rule_version: str, actor: Actor,
                 request_id: str = "") -> dict:
        row = self.repository.get_version(rule_key, rule_version)
        if row is None:
            raise RuleNotFoundError(f"{rule_key}@{rule_version}")
        rule_dict = json.loads(row.content_json)
        errors = validate_rule_content(rule_dict)
        result = {"valid": not errors, "errors": errors,
                  "sha256": row.content_sha256}
        if errors:
            return result
        if row.status == RULE_STATUS_DRAFT:
            self.repository.transition(rule_key, rule_version, RULE_STATUS_VALIDATED)
            self.repository.append_audit(
                action="validate", rule_key=rule_key, version_to=rule_version,
                actor_id=actor.id, actor_name=actor.name, request_id=request_id)
        return result

    def approve(self, rule_key: str, rule_version: str, actor: Actor,
                reason: str = "", request_id: str = "") -> RuleVersionRow:
        row = self.repository.get_version(rule_key, rule_version)
        if row is None:
            raise RuleNotFoundError(f"{rule_key}@{rule_version}")
        if row.status not in (RULE_STATUS_DRAFT, RULE_STATUS_VALIDATED):
            raise RuleConflictError(
                f"cannot approve from status {row.status}; expected draft/validated")
        if self.require_separate_approver and row.created_by == actor.id:
            raise RuleConflictError(
                "require_separate_approver=true: approver must differ from draft creator")
        # FID 硬门（039 §5.2）：paperless 来源且 FID 未确认的规则不得发布为扣分规则
        rule_dict = json.loads(row.content_json)
        if row.origin == "paperless_t_mark_item" and rule_dict.get("mark_item_fid") is None \
                and float(rule_dict.get("deduct_ref") or 0) > 0:
            raise RuleConflictError(
                "paperless_t_mark_item rule without confirmed mark_item_fid "
                "cannot be approved with deduct_ref > 0")
        self.repository.transition(
            rule_key, rule_version, RULE_STATUS_APPROVED,
            approved_by=actor.id, approved_at=datetime.now())
        self.repository.append_audit(
            action="approve", rule_key=rule_key, version_to=rule_version,
            actor_id=actor.id, actor_name=actor.name, reason=reason,
            request_id=request_id)
        return self.repository.get_version(rule_key, rule_version)

    def publish(self, rule_key: str, rule_version: str, actor: Actor,
                reason: str = "", request_id: str = "",
                expect_pointer_version: Optional[int] = None) -> dict:
        """发布单事务：锁规则→校验状态→旧 published 置 retired→指针更新→审计。"""
        row = self.repository.get_version(rule_key, rule_version)
        if row is None:
            raise RuleNotFoundError(f"{rule_key}@{rule_version}")
        if row.status != RULE_STATUS_APPROVED:
            raise RuleConflictError(
                f"cannot publish from status {row.status}; expected approved")
        rule_dict = json.loads(row.content_json)
        # 跨轨 rule_id 唯一性：同 key 其他 published 版本会被置 retired（单轨单活）
        retired_versions = []
        for old in self.repository.list_versions(rule_key):
            if old.status == RULE_STATUS_PUBLISHED and old.rule_version != rule_version:
                self.repository.transition(
                    rule_key, old.rule_version, RULE_STATUS_RETIRED,
                    retired_at=datetime.now())
                retired_versions.append(old.rule_version)
        self.repository.transition(
            rule_key, rule_version, RULE_STATUS_PUBLISHED, published_at=datetime.now())
        pointer = self.repository.set_pointer(
            row.domain, row.track, rule_key, rule_version,
            updated_by=actor.id, expect_pointer_version=expect_pointer_version)
        self.repository.append_audit(
            action="publish", rule_key=rule_key,
            version_from=retired_versions[0] if retired_versions else "",
            version_to=rule_version,
            actor_id=actor.id, actor_name=actor.name, reason=reason,
            request_id=request_id,
            detail={"pointer_version": pointer.pointer_version,
                    "sha256": row.content_sha256})
        return {
            "rule_key": rule_key, "rule_version": rule_version,
            "retired_versions": retired_versions,
            "pointer_version": pointer.pointer_version,
            "sha256": row.content_sha256,
        }

    def rollback(self, rule_key: str, to_version: str, actor: Actor,
                 reason: str = "", request_id: str = "") -> dict:
        """指针指回旧已发布版本（不覆盖历史）。"""
        target = self.repository.get_version(rule_key, to_version)
        if target is None:
            raise RuleNotFoundError(f"{rule_key}@{to_version}")
        if target.status not in (RULE_STATUS_PUBLISHED, RULE_STATUS_RETIRED):
            raise RuleConflictError(
                f"rollback target must be published/retired, got {target.status}")
        pointer = self.repository.get_pointer(target.domain, target.track, rule_key)
        old_version = pointer.published_version if pointer else ""
        if target.status == RULE_STATUS_RETIRED:
            self.repository.transition(
                rule_key, to_version, RULE_STATUS_PUBLISHED,
                published_at=datetime.now())
        self.repository.set_pointer(
            target.domain, target.track, rule_key, to_version, updated_by=actor.id)
        self.repository.append_audit(
            action="rollback", rule_key=rule_key,
            version_from=old_version, version_to=to_version,
            actor_id=actor.id, actor_name=actor.name, reason=reason,
            request_id=request_id)
        return {"rule_key": rule_key, "from": old_version, "to": to_version}

    def retire(self, rule_key: str, rule_version: str, actor: Actor,
               reason: str = "", request_id: str = "") -> RuleVersionRow:
        row = self.repository.get_version(rule_key, rule_version)
        if row is None:
            raise RuleNotFoundError(f"{rule_key}@{rule_version}")
        self.repository.transition(
            rule_key, rule_version, RULE_STATUS_RETIRED, retired_at=datetime.now())
        self.repository.append_audit(
            action="retire", rule_key=rule_key, version_to=rule_version,
            actor_id=actor.id, actor_name=actor.name, reason=reason,
            request_id=request_id)
        return self.repository.get_version(rule_key, rule_version)

    def diff(self, rule_key: str, version_a: str, version_b: str) -> dict:
        """canonical JSON 层面 diff：变更键列表 + 逐键 before/after。"""
        row_a = self.repository.get_version(rule_key, version_a)
        row_b = self.repository.get_version(rule_key, version_b)
        if row_a is None or row_b is None:
            raise RuleNotFoundError(f"{rule_key}@{version_a}|{version_b}")
        dict_a = json.loads(row_a.content_json)
        dict_b = json.loads(row_b.content_json)
        keys = sorted(set(dict_a) | set(dict_b))
        changes = []
        for key in keys:
            va, vb = dict_a.get(key, "<absent>"), dict_b.get(key, "<absent>")
            if canonical_json(va) != canonical_json(vb):
                changes.append({"key": key, "from": va, "to": vb})
        return {
            "rule_key": rule_key,
            "version_a": version_a, "version_b": version_b,
            "sha256_a": row_a.content_sha256, "sha256_b": row_b.content_sha256,
            "changed_keys": [c["key"] for c in changes],
            "changes": changes,
        }

    # ---- 文件导入（039 §5.5） ----

    def import_files(self, paths: List[str], *, apply: bool, actor: Actor,
                     domain_map: Optional[dict] = None,
                     origin_map: Optional[dict] = None) -> dict:
        """规则文件 → 规则仓 published 版本（幂等：同版本同 SHA 跳过）。

        不改写原 JSON 文件；dry-run 只报告不落库。
        """
        domain_map = domain_map or {}
        origin_map = origin_map or {}
        report = {"files": [], "apply": apply,
                  "created": 0, "skipped": 0, "conflicts": [], "errors": []}
        for raw_path in paths:
            path = Path(raw_path)
            file_report = {"path": str(path), "exists": path.exists(),
                           "version": "", "rules": 0}
            if not path.exists():
                file_report["error"] = "file not found"
                report["files"].append(file_report)
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
            file_version = str(raw.get("version") or "")
            file_report["version"] = file_version
            rules = raw.get("rules") or []
            file_report["rules"] = len(rules)
            file_key = path.name
            domain = domain_map.get(file_key, "medical_record")
            origin = origin_map.get(file_key, "paperless_t_mark_item")
            for index, item in enumerate(rules):
                if not isinstance(item, dict):
                    report["errors"].append(f"{path}[{index}]: not an object")
                    continue
                errors = validate_rule_content(item)
                if errors:
                    report["errors"].append(f"{path}[{index}]: {'; '.join(errors)}")
                    continue
                rule_key = str(item["rule_id"])
                rule_version = str(item.get("version") or "")
                sha = content_sha256(item)
                existing = self.repository.get_version(rule_key, rule_version)
                if existing is not None:
                    if existing.content_sha256 == sha:
                        report["skipped"] += 1
                        continue
                    report["conflicts"].append(
                        {"rule_key": rule_key, "rule_version": rule_version,
                         "reason": "same version exists with different sha256"})
                    continue
                report["created"] += 1
                if apply:
                    self.repository.insert_version(
                        rule_key=rule_key, domain=domain, track="main", origin=origin,
                        rule_version=rule_version, set_version=file_version,
                        status=RULE_STATUS_PUBLISHED,
                        content_json=canonical_json(item),
                        content_sha256=sha,
                        published_at=datetime.now(),
                        created_by=actor.id,
                    )
                    self.repository.set_pointer(domain, "main", rule_key,
                                                rule_version, updated_by=actor.id)
            if apply:
                self.repository.append_audit(
                    action="import", actor_id=actor.id, actor_name=actor.name,
                    reason=f"import {'applied' if apply else 'dry-run'}",
                    detail={"files": [str(p) for p in paths],
                            "file_versions": {f["path"]: f["version"]
                                              for f in report["files"]}})
            report["files"].append(file_report)
        return report

    # ---- 运行时三模式（039 §2.1） ----

    def effective_rules(self, mode: str, file_paths: List[str]) -> dict:
        """返回 {mode, specs, rule_version, registry_specs(仅 compare), set_versions}。

        - file：现行行为（load_rules_multi），零行为变化；
        - registry：指针 → published 版本 → 逐条 validate_rule；
        - compare：file 规则给业务结果 + registry 规则影子执行（调用方负责比对）。
        """
        if mode not in RULE_MODES:
            raise ValueError(f"rule_registry.mode must be one of {RULE_MODES}, got {mode!r}")
        result = {"mode": mode, "specs": [], "rule_version": "",
                  "registry_specs": [], "set_versions": []}
        if mode in ("file", "compare"):
            specs, combined = load_rules_multi([str(p) for p in file_paths])
            result["specs"] = specs
            result["rule_version"] = combined
        if mode in ("registry", "compare"):
            published = self.repository.published_rules()
            seen_ids = set()
            reg_specs = []
            set_versions = []
            for row in published:
                if row.rule_key in seen_ids:
                    raise RuleValidationError(
                        f"duplicate published rule_key in registry: {row.rule_key}")
                seen_ids.add(row.rule_key)
                rule_dict = json.loads(row.content_json)
                reg_specs.append(validate_rule(rule_dict))   # 已发布内容二次校验防漂移
                if row.set_version and row.set_version not in set_versions:
                    set_versions.append(row.set_version)
            result["registry_specs"] = reg_specs
            result["set_versions"] = set_versions
            if mode == "registry":
                result["specs"] = reg_specs
                result["rule_version"] = "+".join(set_versions)
        return result


def compare_outputs(file_output, registry_output) -> List[dict]:
    """compare 模式差异计算（脱敏：只含 rule_id/字段名，不含患者数据）。"""
    def _key(problem):
        return str(problem.get("rule_id") or "")

    file_map = {_key(p): p for p in (file_output.problems or [])}
    reg_map = {_key(p): p for p in (registry_output.problems or [])}
    diffs = []
    for rule_id in sorted(set(file_map) | set(reg_map)):
        fp, rp = file_map.get(rule_id), reg_map.get(rule_id)
        if fp is None or rp is None:
            diffs.append({"rule_id": rule_id, "kind": "presence",
                          "file": fp is not None, "registry": rp is not None})
            continue
        for field in ("severity", "message", "mark_item_fid", "deduct_ref", "type"):
            if str(fp.get(field)) != str(rp.get(field)):
                diffs.append({"rule_id": rule_id, "kind": "field", "field": field,
                              "file": fp.get(field), "registry": rp.get(field)})
    return diffs


def rule_registry_settings(config: dict) -> dict:
    """rule_registry 配置读取（含治理项安全默认）。"""
    section = (config or {}).get("rule_registry") or {}
    mode = str(section.get("mode") or "file")
    if mode not in RULE_MODES:
        raise ValueError(f"rule_registry.mode invalid: {mode!r}")
    governance = section.get("governance") or {}
    return {
        "mode": mode,
        "require_separate_approver": bool(section.get("require_separate_approver", False)),
        "governance": {
            "pilot_dept_codes": list(governance.get("pilot_dept_codes") or []),
            "action_policy": str(governance.get("action_policy") or "notify_only"),
            "notify_severities": list(governance.get("notify_severities")
                                      or ["low", "medium", "high"]),
        },
    }
