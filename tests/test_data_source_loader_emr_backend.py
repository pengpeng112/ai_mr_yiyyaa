"""测试 data_source_loader 对 per-source backend 的路由。"""
import copy
import pytest

pytest.importorskip("cryptography")

from app.services import data_source_loader


def test_fetch_source_records_emr_backend_calls_fetch_emr(monkeypatch):
    """backend=emr_vastbase 应调用 fetch_emr_records。"""
    called_with = {}

    def fake_fetch_emr(cfg, dept_list, query_date, document_kind="", source_name="", kind_filter=""):
        called_with["cfg"] = cfg
        called_with["dept_list"] = dept_list
        called_with["query_date"] = query_date
        called_with["document_kind"] = document_kind
        called_with["source_name"] = source_name
        called_with["kind_filter"] = kind_filter
        return [{"patient_id": "P1", "visit_number": "1"}]

    def fake_parse_emr(config):
        return {"enabled": True, "host": "10.0.0.1", "database": "testdb"}

    monkeypatch.setattr(data_source_loader, "fetch_emr_records", fake_fetch_emr)
    monkeypatch.setattr(
        data_source_loader.ConfigParser, "parse_emr_vastbase_config",
        staticmethod(fake_parse_emr),
    )

    root_cfg = {"data_source": {"type": "oracle"}}
    source_cfg = {"type": "sql", "backend": "emr_vastbase", "query_sql": "ignored"}

    records = data_source_loader._fetch_source_records("oracle", root_cfg, source_cfg, ["外科"], "2026-05-01")

    assert len(records) == 1
    assert records[0]["patient_id"] == "P1"
    assert called_with["dept_list"] == ["外科"]
    assert called_with["query_date"] == "2026-05-01"


def test_fetch_source_records_emr_backend_disabled_returns_empty(monkeypatch):
    """backend=emr_vastbase 但 emr 未启用时返回空列表。"""
    def fake_parse_emr(config):
        return {"enabled": False}

    monkeypatch.setattr(
        data_source_loader.ConfigParser, "parse_emr_vastbase_config",
        staticmethod(fake_parse_emr),
    )

    root_cfg = {"data_source": {"type": "oracle"}}
    source_cfg = {"type": "sql", "backend": "emr_vastbase"}

    records = data_source_loader._fetch_source_records("oracle", root_cfg, source_cfg, [], "2026-05-01")
    assert records == []


def test_fetch_source_records_default_backend_uses_global(monkeypatch):
    """backend=default 应使用全局 data_source.type 路由。"""
    called_with = {}

    def fake_fetch_records(cfg, dept_list, query_date):
        called_with["called"] = True
        return []

    monkeypatch.setattr(data_source_loader, "fetch_records", fake_fetch_records)

    def fake_parse_oracle(config):
        return {"host": "test"}

    monkeypatch.setattr(
        data_source_loader.ConfigParser, "parse_oracle_config",
        staticmethod(fake_parse_oracle),
    )
    monkeypatch.setattr(
        data_source_loader.ConfigParser, "get_field_mapping",
        staticmethod(lambda config, ds: {}),
    )

    root_cfg = {"data_source": {"type": "oracle"}}
    source_cfg = {"type": "sql", "backend": "default", "query_sql": "SELECT 1"}

    data_source_loader._fetch_source_records("oracle", root_cfg, source_cfg, [], "2026-05-01")
    assert called_with.get("called") is True


def test_fetch_source_records_oracle_backend_forces_oracle(monkeypatch):
    """backend=oracle 应强制使用 Oracle，即使全局是 postgresql。"""
    called_with = {}

    def fake_fetch_records(cfg, dept_list, query_date):
        called_with["called"] = True
        return []

    monkeypatch.setattr(data_source_loader, "fetch_records", fake_fetch_records)

    def fake_parse_oracle(config):
        return {"host": "test"}

    monkeypatch.setattr(
        data_source_loader.ConfigParser, "parse_oracle_config",
        staticmethod(fake_parse_oracle),
    )
    monkeypatch.setattr(
        data_source_loader.ConfigParser, "get_field_mapping",
        staticmethod(lambda config, ds: {}),
    )

    root_cfg = {"data_source": {"type": "postgresql"}}
    source_cfg = {"type": "sql", "backend": "oracle", "query_sql": "SELECT 1"}

    data_source_loader._fetch_source_records("postgresql", root_cfg, source_cfg, [], "2026-05-01")
    assert called_with.get("called") is True


def test_record_group_values_canonical_fallback():
    """field_mapping 配中文键但 record 含英文 canonical 字段时，应能回退取值。"""
    record = {"patient_id": "P001", "visit_number": "2", "audit_date": "2026-05-28"}
    field_mapping = {"patient_id": "患者ID", "visit_number": "次数", "audit_date": "审计日期"}
    group_key = ["patient_id", "visit_number", "audit_date"]
    values = data_source_loader._record_group_values(record, field_mapping, group_key)
    assert values["patient_id"] == "P001"
    assert values["visit_number"] == "2"
    assert values["audit_date"] == "2026-05-28"
