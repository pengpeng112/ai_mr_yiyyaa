"""
审计类型注册表服务。

ADR-2 维度数组项子字段映射协议（方案A）：
- 统一核心字段：dimension_code / dimension / severity / issue_summary / recommendation / confidence
- 类型专属证据统一放入 extra 字段（如 extra.evidence_lab / extra.evidence_exam / extra.evidence_frontpage）
- _save_audit_results 读取 dim.get("extra", {}) 后序列化到 AuditDimensionResult.extra_json
- 旧 progress_vs_nursing 的 medical_evidence / nursing_evidence 仍走原字段，保持不变
"""
import copy
import logging
from typing import Any

try:
    from jsonpath_ng.ext import parse as parse_jsonpath
except ImportError:  # pragma: no cover - 依赖缺失时兜底
    def parse_jsonpath(path: str):
        text = str(path or "").strip()
        if not text.startswith("$"):
            raise ValueError("JSONPath must start with '$'")
        if text.count("[") != text.count("]"):
            raise ValueError("invalid JSONPath brackets")
        return text

from app.config import encrypt_value, load_config, mask_secret, save_config, _ensure_default_audit_type
from app.db_client_base import validate_configurable_sql
from app.dify_pusher import sanitize_extra_inputs
from app.schemas import AuditTypeConfig

logger = logging.getLogger(__name__)

_PATH_FIELDS = (
    "dimension_path",
    "conclusion_path",
    "severity_path",
    "risk_score_path",
    "inconsistency_path",
)

_REQUIRE_QUERY_DATE_AND_DEPT_FILTER = {
    "lab_exam_vs_progress_nursing": {"lab", "exam", "progress", "nursing"},
    "frontpage_surgery_diagnosis_vs_first_progress": {"frontpage", "first_progress"},
}


class AuditTypeRegistry:
    """读取、校验并管理 audit_types 配置。"""

    def __init__(self, config: dict | None = None):
        self.config = _ensure_default_audit_type(copy.deepcopy(config or load_config()))
        self._items = self._load_items()

    def _load_items(self) -> list[AuditTypeConfig]:
        audit_types = self.config.get("audit_types", []) or []
        items: list[AuditTypeConfig] = []
        try:
            for raw in audit_types:
                items.append(AuditTypeConfig.model_validate(raw))
        except Exception as exc:
            logger.error("audit_types 配置损坏，回退为默认内置类型: %s", exc, exc_info=True)
            fallback_config = load_config()
            audit_types = fallback_config.get("audit_types", []) or []
            items = [AuditTypeConfig.model_validate(raw) for raw in audit_types]
            self.config = fallback_config
        return sorted(items, key=lambda item: (int(item.sort_order), item.code))

    def refresh(self) -> None:
        self.config = load_config()
        self._items = self._load_items()

    def list_all(self) -> list[AuditTypeConfig]:
        return list(self._items)

    def list_enabled(self) -> list[AuditTypeConfig]:
        return [item for item in self._items if item.enabled]

    def list_default_schedule(self) -> list[AuditTypeConfig]:
        defaults = [item for item in self.list_enabled() if item.default_for_schedule]
        return defaults or [self.get("progress_vs_nursing")]

    def get(self, code: str) -> AuditTypeConfig:
        target = str(code or "").strip()
        for item in self._items:
            if item.code == target:
                return item
        raise KeyError(f"audit_type not found: {target}")

    def get_or_default(self, code: str | None) -> AuditTypeConfig:
        target = str(code or "").strip()
        if not target:
            return self.get("progress_vs_nursing")
        try:
            return self.get(target)
        except KeyError:
            return self.get("progress_vs_nursing")

    def to_masked_dict(self, item: AuditTypeConfig) -> dict[str, Any]:
        data = item.model_dump()
        dify_cfg = data.get("dify", {}) or {}
        if dify_cfg.get("api_key"):
            dify_cfg["api_key"] = mask_secret(str(dify_cfg.get("api_key") or ""))
        if dify_cfg.get("api_key_enc"):
            dify_cfg["api_key_enc"] = "***"
        for target in dify_cfg.get("targets", []) or []:
            if target.get("api_key"):
                target["api_key"] = mask_secret(str(target.get("api_key") or ""))
            if target.get("api_key_enc"):
                target["api_key_enc"] = "***"
        data["dify"] = dify_cfg
        return data

    def validate_for_save(self, cfg: AuditTypeConfig, existing_code: str | None = None) -> None:
        current_code = str(existing_code or "").strip()
        for item in self._items:
            if item.code == cfg.code and item.code != current_code:
                raise ValueError(f"audit_type code already exists: {cfg.code}")

        for source_name, source in (cfg.sources or {}).items():
            validate_configurable_sql(source.query_sql, f"{cfg.code}.{source_name}.query_sql")

        required_sources = _REQUIRE_QUERY_DATE_AND_DEPT_FILTER.get(cfg.code, set())
        for source_name in required_sources:
            source_cfg = (cfg.sources or {}).get(source_name)
            if not source_cfg:
                continue
            sql_text = str(source_cfg.query_sql or "")
            if ":query_date" not in sql_text:
                raise ValueError(f"{cfg.code}.{source_name}.query_sql must include :query_date")
            if "{dept_filter}" not in sql_text:
                raise ValueError(f"{cfg.code}.{source_name}.query_sql must include {{dept_filter}}")

        response_cfg = cfg.response or {}
        for field_name in _PATH_FIELDS:
            path = str(response_cfg.get(field_name) or "").strip()
            if path:
                parse_jsonpath(path)

        for block in (cfg.display.summary_blocks + cfg.display.detail_blocks):
            parse_jsonpath(block.path)
            for column in block.columns or []:
                parse_jsonpath(column.path)

    @staticmethod
    def _merge_secret_config(new_cfg: dict[str, Any], old_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
        merged = copy.deepcopy(new_cfg or {})
        current = copy.deepcopy(old_cfg or {})
        plain = str(merged.get("api_key") or "").strip()
        encrypted = str(merged.get("api_key_enc") or "").strip()
        keep_existing = not plain and (not encrypted or encrypted == "***")

        if plain and "*" not in plain:
            merged["api_key_enc"] = encrypt_value(plain)
        elif keep_existing and current.get("api_key_enc"):
            merged["api_key_enc"] = current.get("api_key_enc")
        elif encrypted == "***":
            merged["api_key_enc"] = str(current.get("api_key_enc") or "")

        merged.pop("api_key", None)
        return merged

    def _prepare_for_save(self, cfg: AuditTypeConfig, existing_code: str | None = None) -> dict[str, Any]:
        payload = cfg.model_dump(exclude_none=True)
        previous = None
        if existing_code:
            try:
                previous = self.get(existing_code).model_dump(exclude_none=True)
            except KeyError:
                previous = None

        payload["dify"] = self._merge_secret_config(payload.get("dify", {}), (previous or {}).get("dify", {}))
        input_var = str(payload["dify"].get("workflow_input_variable") or "mr_txt")
        payload["dify"]["extra_inputs"] = sanitize_extra_inputs(
            payload["dify"].get("extra_inputs", {}),
            input_var,
        )

        old_targets = {
            str(item.get("name") or "").strip(): item
            for item in ((previous or {}).get("dify", {}) or {}).get("targets", []) or []
            if str(item.get("name") or "").strip()
        }
        next_targets = []
        for item in (payload.get("dify", {}) or {}).get("targets", []) or []:
            target_name = str(item.get("name") or "").strip()
            next_targets.append(self._merge_secret_config(item, old_targets.get(target_name)))
        payload["dify"]["targets"] = next_targets
        return payload

    def save(self, cfg: AuditTypeConfig, existing_code: str | None = None) -> AuditTypeConfig:
        self.validate_for_save(cfg, existing_code=existing_code)
        config_data = copy.deepcopy(self.config)
        payload = self._prepare_for_save(cfg, existing_code=existing_code)
        audit_types = config_data.get("audit_types", []) or []
        replaced = False
        for index, item in enumerate(audit_types):
            if str(item.get("code") or "").strip() == str(existing_code or cfg.code):
                audit_types[index] = payload
                replaced = True
                break
        if not replaced:
            audit_types.append(payload)
        config_data["audit_types"] = audit_types
        save_config(config_data)
        self.refresh()
        return self.get(cfg.code)

    def delete(self, code: str) -> None:
        target = str(code or "").strip()
        if target == "progress_vs_nursing":
            raise ValueError("progress_vs_nursing cannot be deleted")
        config_data = copy.deepcopy(self.config)
        config_data["audit_types"] = [
            item for item in (config_data.get("audit_types", []) or [])
            if str(item.get("code") or "").strip() != target
        ]
        save_config(config_data)
        self.refresh()


def get_audit_type_registry(config: dict | None = None) -> AuditTypeRegistry:
    return AuditTypeRegistry(config=config)
