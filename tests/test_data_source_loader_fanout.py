"""测试 data_source_loader 的 fanout 加载策略。"""
import pytest

from app.schemas import AuditTypeConfig

pytest.importorskip("cryptography")

from app.services import data_source_loader


def test_fanout_source_attaches_to_existing_bundles(monkeypatch):
    audit_type = AuditTypeConfig.model_validate({
        "code": "lab_exam_vs_progress_nursing",
        "name": "检验检查 vs 病程护理",
        "sources": {
            "lab": {
                "type": "sql",
                "query_sql": "SELECT 'lab' AS source_name",
                "field_mapping": {"patient_id": "患者ID", "visit_number": "次数"},
                "required": False,
            },
            "exam": {
                "type": "sql",
                "query_sql": "SELECT 'exam' AS source_name",
                "field_mapping": {"patient_id": "患者ID", "visit_number": "次数"},
                "required": False,
            },
            "progress": {
                "type": "sql",
                "query_sql": "SELECT 'progress' AS source_name",
                "field_mapping": {"patient_id": "患者ID", "visit_number": "次数"},
                "required": False,
            },
            "nursing": {
                "type": "sql",
                "load_strategy": "fanout",
                "fanout_max_workers": 2,
                "query_sql": "SELECT 护理内容 FROM ydhl.v_hljl WHERE 患者ID = :patient_key",
                "field_mapping": {"patient_id": "患者ID", "visit_number": "次数"},
                "required": False,
            },
        },
        "group_key": ["patient_id", "visit_number", "audit_date"],
        "payload": {"builder": "lab_exam_structured_progress_nursing"},
        "dify": {"base_url": "http://example.com/v1"},
    })

    records_by_source = {
        "lab": [{"患者ID": "P001", "次数": "1", "audit_date": "2026-04-29", "检验单号": "LAB-001"}],
        "exam": [{"患者ID": "P001", "次数": "1", "audit_date": "2026-04-29", "检查号": "EXAM-001"}],
    }

    def fake_fetch_source_records(*, source_cfg, **_kwargs):
        sql = source_cfg.get("query_sql", "")
        for source_name, records in records_by_source.items():
            if f"'{source_name}'" in sql:
                return records
        return []

    def fake_oracle_fanout_worker(_root_config, _source_cfg, _sql, bundles, _query_date):
        results = []
        for bundle in bundles:
            results.append((
                bundle.bundle_id,
                [{"患者ID": bundle.group_values["patient_id"], "次数": bundle.group_values["visit_number"], "audit_date": "2026-04-29", "护理内容": "护理记录"}],
                "",
                1,
                False,
            ))
        return results

    monkeypatch.setattr(data_source_loader, "_fetch_source_records", fake_fetch_source_records)
    monkeypatch.setattr(data_source_loader, "_oracle_fanout_worker", fake_oracle_fanout_worker)

    bundles, diagnostics = data_source_loader.load_patient_bundles(
        audit_type=audit_type,
        root_config={"data_source": {"type": "oracle"}, "oracle": {"field_mapping": {}}},
        query_date="2026-04-29",
        return_diagnostics=True,
    )

    assert len(bundles) == 1
    bundle = bundles[0]
    assert bundle.bundle_id == "P001::1::2026-04-29"
    assert bundle.sources["nursing"][0]["护理内容"] == "护理记录"
    assert diagnostics["source_row_counts"]["nursing"] == 1
    assert diagnostics["fanout"]["nursing"]["success"] == 1
    assert diagnostics["fanout"]["nursing"]["failed"] == 0


def test_build_fanout_params_date_window_default():
    bundle = data_source_loader.PatientBundle(
        bundle_id="P001::1",
        group_values={"patient_id": "P001", "visit_number": "1"},
        query_date="2026-06-01",
    )
    source_cfg = {"fanout_date_window_days": 61}
    params = data_source_loader._build_fanout_params(bundle, source_cfg, "2026-06-01")
    assert params["date_from"] == "2026-04-01"
    assert params["date_to"] == "2026-06-01"
    assert params["query_date"] == "2026-06-01"
    assert params["patient_key"] == "P001_1"


def test_build_fanout_params_custom_date_window():
    bundle = data_source_loader.PatientBundle(
        bundle_id="P001::1",
        group_values={"patient_id": "P001", "visit_number": "1"},
        query_date="2026-06-01",
    )
    source_cfg = {"fanout_date_window_days": 30}
    params = data_source_loader._build_fanout_params(bundle, source_cfg, "2026-06-01")
    assert params["date_from"] == "2026-05-02"
    assert params["date_to"] == "2026-06-01"


def test_build_fanout_params_invalid_query_date():
    bundle = data_source_loader.PatientBundle(
        bundle_id="P001::1",
        group_values={"patient_id": "P001", "visit_number": "1"},
        query_date="invalid",
    )
    source_cfg = {"fanout_date_window_days": 61}
    params = data_source_loader._build_fanout_params(bundle, source_cfg, "invalid")
    assert params["date_from"] == "invalid"
    assert params["date_to"] == "invalid"


def test_fanout_source_failure_isolated(monkeypatch):
    audit_type = AuditTypeConfig.model_validate({
        "code": "jyjc_vs_bcnursing",
        "name": "检验检查 vs 病程护理",
        "sources": {
            "lab": {
                "type": "sql",
                "query_sql": "SELECT 'lab' AS source_name",
                "field_mapping": {"patient_id": "患者ID", "visit_number": "次数"},
                "required": False,
            },
            "nursing": {
                "type": "sql",
                "load_strategy": "fanout",
                "fanout_max_workers": 1,
                "query_sql": "SELECT 护理内容 FROM ydhl.v_hljl WHERE 患者ID = :patient_key",
                "field_mapping": {"patient_id": "患者ID", "visit_number": "次数"},
                "required": False,
            },
        },
        "group_key": ["patient_id", "visit_number"],
        "payload": {"builder": "generic_multi_source"},
        "dify": {"base_url": "http://example.com/v1"},
    })

    def fake_fetch_source_records(*, source_cfg, **_kwargs):
        sql = source_cfg.get("query_sql", "")
        if "'lab'" in sql:
            return [
                {"患者ID": "P001", "次数": "1", "检验单号": "LAB-001"},
                {"患者ID": "P002", "次数": "2", "检验单号": "LAB-002"},
            ]
        return []

    def fake_oracle_fanout_worker(_root_config, _source_cfg, _sql, bundles, _query_date):
        results = []
        for bundle in bundles:
            pid = bundle.group_values["patient_id"]
            if pid == "P001":
                results.append((bundle.bundle_id, [], "ORA-xxx timeout", 120000, False))
            else:
                results.append((
                    bundle.bundle_id,
                    [{"患者ID": pid, "次数": bundle.group_values["visit_number"], "护理内容": "ok"}],
                    "",
                    1,
                    False,
                ))
        return results

    monkeypatch.setattr(data_source_loader, "_fetch_source_records", fake_fetch_source_records)
    monkeypatch.setattr(data_source_loader, "_oracle_fanout_worker", fake_oracle_fanout_worker)

    bundles = data_source_loader.load_patient_bundles(
        audit_type=audit_type,
        root_config={"data_source": {"type": "oracle"}, "oracle": {"field_mapping": {}}},
        query_date="2026-04-29",
        return_diagnostics=False,
    )

    assert len(bundles) == 2
    ids = {b.bundle_id for b in bundles}
    assert ids == {"P001::1", "P002::2"}
    p002 = next(b for b in bundles if b.bundle_id == "P002::2")
    assert p002.sources["nursing"][0]["护理内容"] == "ok"
    p001 = next(b for b in bundles if b.bundle_id == "P001::1")
    assert not p001.sources.get("nursing")


def test_no_fanout_config_uses_bulk(monkeypatch):
    audit_type = AuditTypeConfig.model_validate({
        "code": "jyjc_vs_bcnursing",
        "name": "检验检查 vs 病程护理",
        "sources": {
            "nursing": {
                "type": "sql",
                "query_sql": "SELECT 护理内容 FROM ydhl.v_hljl",
                "field_mapping": {"patient_id": "患者ID", "visit_number": "次数"},
                "required": False,
            },
        },
        "group_key": ["patient_id", "visit_number"],
        "payload": {"builder": "generic_multi_source"},
        "dify": {"base_url": "http://example.com/v1"},
    })

    call_counter = [0]

    def fake_fetch_source_records(*, source_cfg, **_kwargs):
        call_counter[0] += 1
        return [{"患者ID": "P001", "次数": "1", "护理内容": "ok"}]

    monkeypatch.setattr(data_source_loader, "_fetch_source_records", fake_fetch_source_records)

    bundles = data_source_loader.load_patient_bundles(
        audit_type=audit_type,
        root_config={"data_source": {"type": "oracle"}, "oracle": {"field_mapping": {}}},
        query_date="2026-04-29",
        return_diagnostics=False,
    )

    assert len(bundles) == 1
    assert call_counter[0] == 1


def test_fanout_truncated_flag(monkeypatch):
    audit_type = AuditTypeConfig.model_validate({
        "code": "jyjc_vs_bcnursing",
        "name": "检验检查 vs 病程护理",
        "sources": {
            "lab": {
                "type": "sql",
                "query_sql": "SELECT 'lab' AS source_name",
                "field_mapping": {"patient_id": "患者ID", "visit_number": "次数"},
                "required": False,
            },
            "nursing": {
                "type": "sql",
                "load_strategy": "fanout",
                "fanout_max_workers": 1,
                "fanout_max_records_per_bundle": 2,
                "query_sql": "SELECT 护理内容 FROM ydhl.v_hljl WHERE 患者ID = :patient_key",
                "field_mapping": {"patient_id": "患者ID", "visit_number": "次数"},
                "required": False,
            },
        },
        "group_key": ["patient_id", "visit_number"],
        "payload": {"builder": "generic_multi_source"},
        "dify": {"base_url": "http://example.com/v1"},
    })

    def fake_fetch_source_records(*, source_cfg, **_kwargs):
        sql = source_cfg.get("query_sql", "")
        if "'lab'" in sql:
            return [{"患者ID": "P001", "次数": "1", "检验单号": "LAB-001"}]
        return []

    def fake_oracle_fanout_worker(_root_config, _source_cfg, _sql, bundles, _query_date):
        results = []
        for bundle in bundles:
            records = [
                {"患者ID": bundle.group_values["patient_id"], "次数": bundle.group_values["visit_number"], "护理内容": f"内容{i}"}
                for i in range(5)
            ]
            results.append((bundle.bundle_id, records, "", 1, False))
        return results

    monkeypatch.setattr(data_source_loader, "_fetch_source_records", fake_fetch_source_records)
    monkeypatch.setattr(data_source_loader, "_oracle_fanout_worker", fake_oracle_fanout_worker)

    bundles, diagnostics = data_source_loader.load_patient_bundles(
        audit_type=audit_type,
        root_config={"data_source": {"type": "oracle"}, "oracle": {"field_mapping": {}}},
        query_date="2026-04-29",
        return_diagnostics=True,
    )

    assert diagnostics["fanout"]["nursing"]["truncated"] == 0
    assert diagnostics["fanout"]["nursing"]["rows"] == 5
