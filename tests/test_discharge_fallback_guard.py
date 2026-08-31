"""discharge_final 类型级生效性防呆回归（035/RP2，B1）。

生产核验结论（2026-09-01 只读）：
- admission_vs_first_progress / surgery_chain / discharge_vs_frontpage 三类型为
  EMR 文档源（query_sql 为空、backend/data_source=emr_vastbase），
  出院模式走 data_source_loader._fetch_discharged_emr_records 专用加载
  （V_QYBR 出院患者 → Vastbase 文书），通用 fallback 的 a."出院日期" 注入不适用；
- 通用 fallback（scheduler_run_modes.py）面向"SQL 源含 {dept_filter}"的类型，
  注入过滤硬编码别名 a，SQL 无别名 a 时运行将 ORA-00904；
- 生效性缺口=合法类型 fallback 未命中时仅 info 日志——本文件固化的告警将其升级为
  /api/scheduler/status 与配置保存响应中的可见告警。
"""

from __future__ import annotations

from types import SimpleNamespace

from app.routers import config as config_router
from app.routers import scheduler as scheduler_router
from app.schemas import AuditTypeConfig
from app.services.scheduler_run_modes import (
    audit_type_for_run_mode,
    discharge_effectiveness_warnings,
)


def _sql_audit_type(code: str, sources: dict) -> AuditTypeConfig:
    return AuditTypeConfig.model_validate({
        "code": code,
        "name": code,
        "sources": sources,
        "group_key": ["patient_id", "visit_number"],
        "payload": {"builder": "generic_multi_source"},
        "dify": {"base_url": "http://example.com/v1"},
    })


def _config_with_discharge(audit_types: list[dict], codes: list[str]) -> dict:
    return {
        "audit_types": audit_types,
        "scheduler_discharge": {"enabled": True, "audit_type_codes": codes},
    }


class TestFallbackInjection:
    def test_fallback_injects_discharge_filter_for_placeholder_sql(self):
        """T1：SQL 源含 {dept_filter} → 通用 fallback 注入出院日期过滤。"""
        sql = 'SELECT a."患者ID" AS patient_id FROM jhemr.v_qybr a WHERE {dept_filter}'
        audit_type = _sql_audit_type("admission_vs_first_progress", {
            "admission": {"type": "sql", "query_sql": sql, "required": False},
        })
        converted = audit_type_for_run_mode(audit_type, "discharge_final")
        converted_sql = converted.sources["admission"].query_sql
        assert '{dept_filter}' in converted_sql
        assert 'a."出院日期" >= TO_DATE(:query_date' in converted_sql
        assert 'a."出院日期" < TO_DATE(:query_date' in converted_sql
        # 原配置不被污染（克隆副本）
        assert '{dept_filter}\n    AND a."出院日期"' not in audit_type.sources["admission"].query_sql


class TestEffectivenessWarnings:
    def test_placeholder_sql_without_alias_a_triggers_warning(self):
        """T2：SQL 含 {dept_filter} 但无别名 a → 注入将 ORA-00904，告警触发。"""
        cfg = _config_with_discharge([{
            "code": "surgery_chain",
            "name": "手术链",
            "sources": {
                "perioperative": {
                    "type": "sql",
                    "query_sql": "SELECT p.x FROM jhemr.v_blws p WHERE {dept_filter}",
                },
            },
        }], ["surgery_chain"])
        warnings = discharge_effectiveness_warnings(cfg)
        assert len(warnings) == 1
        assert warnings[0]["code"] == "surgery_chain"
        assert warnings[0]["source"] == "perioperative"
        assert "ORA-00904" in warnings[0]["detail"]

    def test_emr_sources_are_discharge_safe_without_warnings(self):
        """生产 3 类型实际形态：EMR 源 + 空 query_sql → 专用出院加载，零告警。"""
        cfg = _config_with_discharge([
            {"code": "admission_vs_first_progress", "name": "入院与首次病程", "sources": {
                "admission": {"type": "sql", "backend": "emr_vastbase", "query_sql": "", "kind_filter": "AND x = '入院记录'"},
                "progress": {"type": "sql", "data_source": "emr_vastbase", "query_sql": ""},
            }},
            {"code": "surgery_chain", "name": "手术链", "sources": {
                "perioperative": {"type": "sql", "backend": "emr_vastbase", "query_sql": ""},
            }},
            {"code": "discharge_vs_frontpage", "name": "出院与病案首页", "sources": {
                "discharge": {"type": "sql", "backend": "default", "data_source": "emr_vastbase", "query_sql": ""},
                "progress": {"type": "sql", "backend": "emr_vastbase", "query_sql": "", "document_kind": "first_progress"},
            }},
        ], ["admission_vs_first_progress", "surgery_chain", "discharge_vs_frontpage"])
        assert discharge_effectiveness_warnings(cfg) == []

    def test_dedicated_type_without_placeholder_warns(self):
        """专属转换类型（syssvsscbc）参与源均无 {dept_filter} → 转换不生效告警。"""
        cfg = _config_with_discharge([{
            "code": "syssvsscbc",
            "name": "系统一致性",
            "sources": {
                "frontpage": {"type": "sql", "query_sql": "SELECT 1 FROM dual"},
                "first_progress": {"type": "sql", "query_sql": "SELECT 2 FROM dual"},
            },
        }], ["syssvsscbc"])
        warnings = discharge_effectiveness_warnings(cfg)
        assert len(warnings) == 1
        assert warnings[0]["code"] == "syssvsscbc"
        assert "{dept_filter}" in warnings[0]["detail"]

    def test_unknown_code_and_plain_sql_warn(self):
        cfg = _config_with_discharge([{
            "code": "real_type",
            "name": "实型",
            "sources": {"s1": {"type": "sql", "query_sql": "SELECT x FROM t WHERE d = :query_date"}},
        }], ["ghost_type", "real_type"])
        warnings = discharge_effectiveness_warnings(cfg)
        codes = {w["code"] for w in warnings}
        assert codes == {"ghost_type", "real_type"}
        details = " | ".join(w["detail"] for w in warnings)
        assert "不存在" in details
        assert "依赖 SQL 自身" in details

    def test_disabled_discharge_returns_empty(self):
        cfg = _config_with_discharge(
            [{"code": "x", "sources": {"s": {"type": "sql", "query_sql": "SELECT 1"}}}],
            ["x"],
        )
        cfg["scheduler_discharge"]["enabled"] = False
        assert discharge_effectiveness_warnings(cfg) == []


class TestStatusAndSaveWiring:
    @staticmethod
    def _patch_status_env(monkeypatch, cfg):
        monkeypatch.setattr(scheduler_router, "load_config", lambda: cfg)
        monkeypatch.setattr(scheduler_router, "get_scheduler", lambda: None)
        monkeypatch.setattr(scheduler_router, "get_last_run_info", lambda: {})
        monkeypatch.setattr(scheduler_router, "get_scheduler_lock_info", lambda name: {"status": "idle"})
        monkeypatch.setattr(scheduler_router, "is_scheduler_env_enabled", lambda: True)

    def test_status_includes_discharge_effectiveness_keys(self, monkeypatch):
        """T4：/api/scheduler/status 含 discharge_effectiveness 告警键。"""
        cfg = _config_with_discharge([{
            "code": "surgery_chain",
            "name": "手术链",
            "sources": {"perioperative": {"type": "sql", "query_sql": "SELECT p.x FROM t p WHERE {dept_filter}"}},
        }], ["surgery_chain"])
        self._patch_status_env(monkeypatch, cfg)
        response = scheduler_router.scheduler_status(_user=SimpleNamespace())
        body = response if isinstance(response, dict) else response.body
        import json
        payload = json.loads(body) if not isinstance(response, dict) else response
        assert "discharge_effectiveness" in payload
        assert payload["discharge_effectiveness"]["checked"] is True
        assert len(payload["discharge_effectiveness"]["warnings"]) == 1
        assert any("出院终末模式生效性告警" in d for d in payload["diagnostics"])

    def test_save_discharge_config_returns_effectiveness_warnings(self, monkeypatch):
        """T3：配置保存（合法但不生效类型）→ 响应携带生效性告警，不拒绝保存。"""
        from app.schemas import SchedulerConfig

        cfg = _config_with_discharge([{
            "code": "surgery_chain",
            "name": "手术链",
            "sources": {"perioperative": {"type": "sql", "query_sql": "SELECT p.x FROM t p WHERE {dept_filter}"}},
        }], ["progress_vs_nursing"])

        monkeypatch.setattr(config_router, "update_scheduler", lambda *a, **k: {"applied": True})

        def _fake_update_section(section, payload):
            cfg[section] = payload

        monkeypatch.setattr(config_router, "update_section", _fake_update_section)
        monkeypatch.setattr(config_router, "load_config", lambda: cfg)

        body = SchedulerConfig(
            enabled=True,
            schedule_mode="daily",
            daily_time="11:44",
            audit_run_mode="discharge_final",
            audit_type_codes=["surgery_chain"],
        )
        result = config_router._save_scheduler_section(
            "scheduler_discharge", "discharge_push", body, SimpleNamespace(username="tester", id=1)
        )
        assert result.success is True
        assert "生效性告警" in result.message
        assert result.data["effectiveness_warnings"][0]["code"] == "surgery_chain"
