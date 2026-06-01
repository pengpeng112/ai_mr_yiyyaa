"""
统一的配置解析服务 —— 消除代码重复，提供一致的配置处理逻辑
"""
import logging
from typing import List, Dict, Any
from app.config import decrypt_value, normalize_dify_base_url
from app.dify_pusher import sanitize_extra_inputs

logger = logging.getLogger(__name__)


class ConfigParser:
    """配置解析器，提供统一的配置处理方法"""

    @staticmethod
    def get_data_source_type(config: Dict[str, Any]) -> str:
        ds = (config.get("data_source", {}) or {}).get("type", "oracle")
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
                "weight": int(t.get("weight") or 1),
                "enabled": True,
            })
        return persisted
