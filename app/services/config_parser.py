"""
统一的配置解析服务 —— 消除代码重复，提供一致的配置处理逻辑
"""
from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List, Optional

from app.config import decrypt_value, normalize_dify_base_url
from app.dify_pusher import sanitize_extra_inputs

logger = logging.getLogger(__name__)

_DEFAULT_TARGET_STRATEGY = "round_robin"
_DEFAULT_CIRCUIT_FAILURES = 3
_DEFAULT_CIRCUIT_SECONDS = 60
_ALLOWED_TARGET_STRATEGIES = frozenset({"round_robin", "weighted_random"})
# target 只允许覆盖端点相关字段，不得覆盖输入输出变量与 mr_type。
_TARGET_ENDPOINT_KEYS = frozenset({
    "name", "base_url", "api_key", "api_key_enc", "timeout_seconds", "weight", "enabled",
})


class ConfigParser:
    """配置解析器，提供统一的配置处理方法"""

    @staticmethod
    def get_data_source_type(config: Dict[str, Any]) -> str:
        ds = (config.get("data_source", {}) or {}).get("type", "oracle")
        if ds == "fixture":
            from app.services.isolated_mode import assert_fixture_source_allowed
            assert_fixture_source_allowed()
            return "fixture"
        return ds if ds in ("oracle", "postgresql") else "oracle"

    @staticmethod
    def parse_oracle_config(config: Dict[str, Any]) -> Dict[str, Any]:
        """解析 Oracle 配置，自动解密密码"""
        oracle_cfg = config.get("oracle", {}).copy()
        try:
            encrypted_pwd = oracle_cfg.get("password_enc", "")
            oracle_cfg["password"] = decrypt_value(encrypted_pwd) if encrypted_pwd else ""
        except Exception as e:
            logger.error(f"Oracle密码解密失败: {e}")
            raise ValueError(f"Oracle 密码解密失败，请检查配置或密钥是否正确: {e}")
        return oracle_cfg

    @staticmethod
    def parse_postgresql_config(config: Dict[str, Any]) -> Dict[str, Any]:
        """解析 PostgreSQL 配置，自动解密密码"""
        pg_cfg = config.get("postgresql", {}).copy()
        try:
            encrypted_pwd = pg_cfg.get("password_enc", "")
            pg_cfg["password"] = decrypt_value(encrypted_pwd) if encrypted_pwd else ""
        except Exception as e:
            logger.error(f"PostgreSQL密码解密失败: {e}")
            raise ValueError(f"PostgreSQL 密码解密失败，请检查配置或密钥是否正确: {e}")
        return pg_cfg

    @staticmethod
    def parse_dify_config(config: Dict[str, Any]) -> Dict[str, Any]:
        """解析 Dify 配置，自动解密 API Key"""
        dify_cfg = config.get("dify", {}).copy()
        if dify_cfg.get("base_url"):
            try:
                dify_cfg["base_url"] = normalize_dify_base_url(dify_cfg["base_url"])
            except ValueError as e:
                logger.warning(f"Dify base_url 配置无效: {e}")
        dify_cfg.setdefault("workflow_input_variable", "mr_txt")
        dify_cfg.setdefault("workflow_output_key", "aa")
        dify_cfg.setdefault("user_identifier", "med-audit-system")
        dify_cfg.setdefault("timeout_seconds", 90)
        dify_cfg["extra_inputs"] = sanitize_extra_inputs(
            dify_cfg.get("extra_inputs", {}),
            str(dify_cfg.get("workflow_input_variable") or "mr_txt"),
        )

        try:
            encrypted_key = dify_cfg.get("api_key_enc", "")
            dify_cfg["api_key"] = decrypt_value(encrypted_key) if encrypted_key else ""
        except Exception as e:
            logger.error(f"Dify API Key解密失败: {e}")
            raise ValueError(f"Dify API Key 解密失败，请检查配置或密钥是否正确: {e}")

        return dify_cfg

    @staticmethod
    def get_department_list(config: Dict[str, Any]) -> List[str]:
        dept_cfg = config.get("departments", {})
        mode = dept_cfg.get("mode", "include")
        dept_list = dept_cfg.get("list", [])
        return dept_list if mode == "include" else []

    @staticmethod
    def filter_departments(records: List[Dict[str, Any]], dept_config: Dict[str, Any],
                           dept_field: str = "所在科室名称") -> List[Dict[str, Any]]:
        if not records:
            return records

        mode = dept_config.get("mode", "include")
        dept_list = dept_config.get("list", [])
        if not dept_list:
            return records

        if mode == "include":
            dept_set = set(dept_list)
            return [r for r in records if r.get(dept_field, r.get("科室", "")) in dept_set]

        exclude_set = set(dept_list)
        return [r for r in records if r.get(dept_field, r.get("科室", "")) not in exclude_set]

    @staticmethod
    def get_push_settings(config: Dict[str, Any]) -> Dict[str, int]:
        push_cfg = config.get("push", {})
        return {
            "interval_ms": push_cfg.get("interval_ms", 500),
            "max_retry": push_cfg.get("max_retry", 3),
            "batch_size": push_cfg.get("batch_size", 50),
            "parallel_workers": push_cfg.get("parallel_workers", 4),
        }

    @staticmethod
    def parse_emr_vastbase_config(config: Dict[str, Any]) -> Dict[str, Any]:
        """解析电子病历海量库配置，自动解密密码"""
        emr_cfg = (config.get("emr_vastbase") or {}).copy()
        defaults = {
            "schema": "jhemr",
            "view": "v_blws",
            "patient_id_field": "patient_id",
            "visit_id_field": "visit_id",
            "dept_field": "dept_name",
            "content_field": "progress_message",
            "title_field": "progress_title_name",
            "type_field": "progress_type_name",
            "template_field": "progress_template_name",
            "record_time_field": "record_time_format",
            "finish_time_field": "finish_time_format",
            "first_save_time_field": "first_save_time",
            "create_date_field": "create_date",
            "doctor_field": "doctor_name",
            "status_field": "progress_status",
            "connect_timeout_seconds": 10,
            "statement_timeout_ms": 60000,
            "max_records": 50000,
            "use_for_export_progress": True,
            "use_for_export_discharge": True,
            "fallback_to_oracle": True,
        }
        for k, v in defaults.items():
            emr_cfg.setdefault(k, v)
        try:
            encrypted_pwd = emr_cfg.get("password_enc", "")
            emr_cfg["password"] = decrypt_value(encrypted_pwd) if encrypted_pwd else ""
        except Exception as e:
            logger.error(f"电子病历海量库密码解密失败: {e}")
            raise ValueError(f"电子病历海量库密码解密失败: {e}")
        return emr_cfg

    @staticmethod
    def get_field_mapping(config: Dict[str, Any], data_source: str = "oracle") -> Dict[str, str]:
        section = "postgresql" if data_source == "postgresql" else "oracle"
        section_cfg = config.get(section, {})
        mapping = (section_cfg.get("field_mapping", {}) or {}).copy()
        defaults = {
            "patient_id": "患者ID",
            "visit_number": "次数",
            "patient_name": "患者姓名",
            "dept": "所在科室名称",
            "admission_no": "住院号",
        }
        for k, v in defaults.items():
            mapping.setdefault(k, v)
        return mapping

    @staticmethod
    def _normalize_target_strategy(value: Any) -> str:
        strategy = str(value or _DEFAULT_TARGET_STRATEGY).strip().lower()
        if strategy not in _ALLOWED_TARGET_STRATEGIES:
            return _DEFAULT_TARGET_STRATEGY
        return strategy

    @staticmethod
    def _clamp_int(value: Any, default: int, min_value: int, max_value: int) -> int:
        try:
            number = int(value)
        except Exception:
            number = default
        return max(min_value, min(max_value, number))

    @staticmethod
    def parse_dify_pool_settings(config: Dict[str, Any]) -> Dict[str, Any]:
        """读取全局 Dify 节点池策略与熔断参数（不含密钥）。"""
        dify_section = (config or {}).get("dify", {}) or {}
        return {
            "target_strategy": ConfigParser._normalize_target_strategy(
                dify_section.get("target_strategy")
            ),
            "circuit_breaker_failures": ConfigParser._clamp_int(
                dify_section.get("circuit_breaker_failures"),
                _DEFAULT_CIRCUIT_FAILURES,
                1,
                20,
            ),
            "circuit_breaker_seconds": ConfigParser._clamp_int(
                dify_section.get("circuit_breaker_seconds"),
                _DEFAULT_CIRCUIT_SECONDS,
                1,
                3600,
            ),
        }

    @staticmethod
    def count_configured_enabled_targets(config: Dict[str, Any]) -> int:
        """统计配置中声明为启用的 target 数（不校验 Key 是否可解密）。"""
        dify_section = (config or {}).get("dify", {}) or {}
        raw_targets = dify_section.get("targets", []) or []
        count = 0
        for item in raw_targets:
            t = dict(item or {})
            if t and bool(t.get("enabled", True)):
                count += 1
        return count

    @staticmethod
    def parse_persisted_dify_targets(config: Dict[str, Any]) -> list:
        """加载全局持久化的可用 Dify 目标节点。"""
        dify_section = (config or {}).get("dify", {}) or {}
        raw_targets = dify_section.get("targets", []) or []
        persisted = []
        for idx, item in enumerate(raw_targets):
            t = dict(item or {})
            if not t or not bool(t.get("enabled", True)):
                continue
            api_key = ""
            try:
                if t.get("api_key_enc"):
                    api_key = decrypt_value(t["api_key_enc"])
                elif t.get("api_key"):
                    # 兼容测试或内存中已解密结构
                    api_key = str(t.get("api_key") or "")
            except Exception:
                api_key = ""
            if not api_key:
                continue
            base_url = str(t.get("base_url") or "").strip()
            if not base_url:
                continue
            try:
                base_url = normalize_dify_base_url(base_url)
            except Exception:
                continue
            persisted.append({
                "name": str(t.get("name") or f"target-{idx + 1}"),
                "base_url": base_url,
                "api_key": api_key,
                "timeout_seconds": int(t.get("timeout_seconds") or 90),
                "weight": max(1, int(t.get("weight") or 1)),
                "enabled": True,
            })
        return persisted

    @staticmethod
    def _audit_type_dify_dict(audit_type: Any) -> Optional[Dict[str, Any]]:
        if audit_type is None:
            return None
        dify_obj = None
        if hasattr(audit_type, "dify"):
            dify_obj = getattr(audit_type, "dify", None)
        elif isinstance(audit_type, dict):
            dify_obj = audit_type.get("dify")
        if dify_obj is None:
            return None
        if hasattr(dify_obj, "model_dump"):
            return dict(dify_obj.model_dump() or {})
        if isinstance(dify_obj, dict):
            return dict(dify_obj)
        return None

    @staticmethod
    def resolve_audit_type_dify_base(config: Dict[str, Any], audit_type: Any = None) -> Dict[str, Any]:
        """解析审计类型/全局单节点 Dify 基配置（深拷贝，不写回原 config）。

        契约字段（workflow_input_variable / workflow_output_key / extra_inputs.mr_type）
        优先取审计类型；端点字段（base_url / api_key）以系统配置 dify 为准，
        避免「系统 Dify 已换新 Key，但审计类型仍绑旧应用」导致一直打到旧 Workflow。
        """
        global_dify = ConfigParser.parse_dify_config(config or {})
        audit_dify = ConfigParser._audit_type_dify_dict(audit_type)
        if not audit_dify:
            return copy.deepcopy(global_dify)

        try:
            base = ConfigParser.parse_dify_config({"dify": audit_dify})
        except Exception:
            # 审计类型 Key 解密失败时，仍保留其 input/output/extra，端点密钥用全局覆盖
            base = dict(audit_dify)
            base.setdefault("workflow_input_variable", "mr_txt")
            base.setdefault("workflow_output_key", "aa")
            base.setdefault("user_identifier", "med-audit-system")
            base.setdefault("timeout_seconds", 90)
            base["extra_inputs"] = sanitize_extra_inputs(
                base.get("extra_inputs", {}),
                str(base.get("workflow_input_variable") or "mr_txt"),
            )
            if base.get("base_url"):
                try:
                    base["base_url"] = normalize_dify_base_url(base["base_url"])
                except Exception:
                    pass
            if not base.get("api_key") and base.get("api_key_enc"):
                try:
                    base["api_key"] = decrypt_value(base["api_key_enc"])
                except Exception:
                    base["api_key"] = ""

        # 系统配置页 Dify 为端点权威来源
        if global_dify.get("base_url"):
            base["base_url"] = global_dify["base_url"]
        if global_dify.get("api_key"):
            base["api_key"] = global_dify["api_key"]
        if global_dify.get("user_identifier") and not base.get("user_identifier"):
            base["user_identifier"] = global_dify["user_identifier"]
        return copy.deepcopy(base)

    @staticmethod
    def resolve_dify_target_pool(config: Dict[str, Any], audit_type: Any = None) -> Dict[str, Any]:
        """统一解析 Dify 节点池：基配置 + 可执行 targets + 策略/熔断。

        合并规则（006 冻结）：
        - base_config：审计类型 Dify（无则全局），提供 input/output/extra_inputs/mr_type 基础
        - targets：仅端点字段（name/base_url/api_key/timeout/weight）
        - 返回值始终为拷贝，禁止写回原 config
        """
        base_config = ConfigParser.resolve_audit_type_dify_base(config, audit_type)
        pool_settings = ConfigParser.parse_dify_pool_settings(config)
        targets = ConfigParser.parse_persisted_dify_targets(config)
        configured_enabled = ConfigParser.count_configured_enabled_targets(config)

        # 配置了启用节点但无一可解密/可用 → 明确池不可用，禁止静默换另一套 Key
        pool_unavailable = configured_enabled > 0 and len(targets) == 0

        return {
            "base_config": base_config,
            "targets": copy.deepcopy(targets),
            "strategy": pool_settings["target_strategy"],
            "target_strategy": pool_settings["target_strategy"],
            "circuit_breaker_failures": pool_settings["circuit_breaker_failures"],
            "circuit_breaker_seconds": pool_settings["circuit_breaker_seconds"],
            "use_bulk": bool(targets) and not pool_unavailable,
            "enabled_target_count": len(targets),
            "configured_enabled_count": configured_enabled,
            "pool_unavailable": pool_unavailable,
            "error_code": "dify_target_pool_unavailable" if pool_unavailable else "",
        }

    @staticmethod
    def endpoint_only_target_overlay(target: Dict[str, Any]) -> Dict[str, Any]:
        """仅保留 target 允许覆盖的端点字段（用于契约测试与安全合并）。"""
        src = dict(target or {})
        out: Dict[str, Any] = {}
        for key in _TARGET_ENDPOINT_KEYS:
            if key in src:
                out[key] = src[key]
        return out
