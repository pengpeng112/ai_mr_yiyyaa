from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import audit_types
from app.schemas import AuditTypeConfig


def _build_audit_type(code: str = "progress_vs_nursing", name: str = "病程 vs 护理") -> AuditTypeConfig:
    return AuditTypeConfig.model_validate(
        {
            "code": code,
            "name": name,
            "description": f"{name} 描述",
            "enabled": True,
            "sort_order": 10,
            "default_for_schedule": code == "progress_vs_nursing",
            "sources": {
                "primary": {
                    "type": "sql",
                    "query_sql": "SELECT 1 FROM dual",
                    "field_mapping": {"patient_id": "PATIENT_ID", "visit_number": "VISIT_NO"},
                    "required": True,
                },
                "reference": {
                    "type": "sql",
                    "query_sql": "SELECT 2 FROM dual",
                    "field_mapping": {},
                    "required": False,
                },
            },
            "group_key": ["patient_id", "visit_number"],
            "payload": {"builder": "generic_multi_source"},
            "dify": {
                "base_url": "http://example.com/v1",
                "workflow_input_variable": "mr_txt",
                "workflow_output_key": "aa",
                "user_identifier": "med-audit-system",
                "timeout_seconds": 90,
                "extra_inputs": {},
                "targets": [],
            },
            "response": {"parse_strategy": "hybrid"},
            "display": {"summary_blocks": [], "detail_blocks": []},
        }
    )


class _DummyDb:
    def __init__(self, role_name: str = "admin"):
        self.role_name = role_name

    def query(self, _model):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return SimpleNamespace(name=self.role_name)


class _FakeRegistry:
    def __init__(self, items=None):
        self.items = {item.code: item for item in (items or [])}
        self.config = {"audit_types": [item.model_dump() for item in self.items.values()]}
        self.saved_args = None
        self.deleted_code = None

    def list_all(self):
        return list(self.items.values())

    def list_enabled(self):
        return [item for item in self.items.values() if item.enabled]

    def get(self, code: str):
        if code not in self.items:
            raise KeyError(code)
        return self.items[code]

    def to_masked_dict(self, item: AuditTypeConfig):
        return item.model_dump()

    def save(self, cfg: AuditTypeConfig, existing_code: str | None = None):
        self.saved_args = (cfg, existing_code)
        self.items[cfg.code] = cfg
        return cfg

    def delete(self, code: str):
        if code == "progress_vs_nursing":
            raise ValueError("progress_vs_nursing cannot be deleted")
        self.deleted_code = code
        self.items.pop(code, None)


def _make_client(role_name: str = "admin") -> TestClient:
    app = FastAPI()
    app.include_router(audit_types.router, prefix="/api/audit-types")
    app.dependency_overrides[audit_types.get_current_user] = lambda: SimpleNamespace(id=1, role_id=1)
    app.dependency_overrides[audit_types.get_db] = lambda: _DummyDb(role_name=role_name)
    return TestClient(app)


def test_list_audit_types_returns_items(monkeypatch):
    registry = _FakeRegistry([_build_audit_type(), _build_audit_type("order_vs_nursing", "医嘱 vs 护理")])
    monkeypatch.setattr(audit_types, "AuditTypeRegistry", lambda: registry)

    client = _make_client()
    response = client.get("/api/audit-types")

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["items"][0]["code"] == "progress_vs_nursing"


def test_list_audit_types_forbidden_when_not_admin():
    client = _make_client(role_name="doctor")
    response = client.get("/api/audit-types")

    assert response.status_code == 403
    assert "detail" in response.json()


def test_list_audit_type_options_allowed_for_non_admin(monkeypatch):
    registry = _FakeRegistry([_build_audit_type(), _build_audit_type("order_vs_nursing", "医嘱 vs 护理")])
    monkeypatch.setattr(audit_types, "AuditTypeRegistry", lambda: registry)

    client = _make_client(role_name="doctor")
    response = client.get("/api/audit-types/options")

    assert response.status_code == 200
    data = response.json()
    assert data["items"] == [
        {"code": "progress_vs_nursing", "name": "病程 vs 护理", "default_for_schedule": True},
        {"code": "order_vs_nursing", "name": "医嘱 vs 护理", "default_for_schedule": False},
    ]
    assert "sources" not in data["items"][0]


def test_update_audit_type_merges_existing_payload(monkeypatch):
    original = _build_audit_type("labexam_vs_progress", "检验检查 vs 病程")
    registry = _FakeRegistry([original])
    monkeypatch.setattr(audit_types, "AuditTypeRegistry", lambda: registry)

    client = _make_client()
    response = client.put(
        "/api/audit-types/labexam_vs_progress",
        json={
            "name": "检验检查 vs 病程（更新）",
            "description": "新的描述",
            "enabled": False,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["code"] == "labexam_vs_progress"
    assert data["name"] == "检验检查 vs 病程（更新）"
    saved_cfg, existing_code = registry.saved_args
    assert existing_code == "labexam_vs_progress"
    assert saved_cfg.sources["primary"].query_sql == "SELECT 1 FROM dual"


def test_update_audit_type_unwraps_full_config_pasted_into_sources(monkeypatch):
    original = _build_audit_type("ss_vs_scbc", "首页手术 vs 术后首次病程")
    pasted = _build_audit_type("ss_vs_scbc", "首页手术 vs 术后首次病程").model_dump()
    pasted["sources"] = {
        "frontpage": {
            "type": "sql",
            "query_sql": "SELECT 1 FROM dual",
            "field_mapping": {"patient_id": "患者ID", "visit_number": "次数"},
            "required": True,
        },
        "first_progress": {
            "type": "sql",
            "query_sql": "SELECT 2 FROM dual",
            "field_mapping": {"patient_id": "患者ID", "visit_number": "次数"},
            "required": True,
        },
    }
    pasted["group_key"] = ["patient_id", "visit_number", "operation_date"]
    pasted["payload"] = {"builder": "frontpage_surgery_first_progress"}
    registry = _FakeRegistry([original])
    monkeypatch.setattr(audit_types, "AuditTypeRegistry", lambda: registry)

    client = _make_client()
    response = client.put(
        "/api/audit-types/ss_vs_scbc",
        json={
            "sources": pasted,
            "payload": {"builder": "legacy_progress_nursing"},
        },
    )

    assert response.status_code == 200
    saved_cfg, existing_code = registry.saved_args
    assert existing_code == "ss_vs_scbc"
    assert set(saved_cfg.sources.keys()) == {"frontpage", "first_progress"}
    assert saved_cfg.payload["builder"] == "frontpage_surgery_first_progress"
    assert saved_cfg.group_key == ["patient_id", "visit_number", "operation_date"]


def test_delete_builtin_audit_type_returns_422(monkeypatch):
    registry = _FakeRegistry([_build_audit_type()])
    monkeypatch.setattr(audit_types, "AuditTypeRegistry", lambda: registry)

    client = _make_client()
    response = client.delete("/api/audit-types/progress_vs_nursing")

    assert response.status_code == 422
    assert "cannot be deleted" in response.json()["detail"]


def test_clone_audit_type_creates_new_disabled_schedule_default(monkeypatch):
    registry = _FakeRegistry([_build_audit_type()])
    monkeypatch.setattr(audit_types, "AuditTypeRegistry", lambda: registry)

    client = _make_client()
    response = client.post(
        "/api/audit-types/progress_vs_nursing/clone",
        json={"new_code": "progress_vs_nursing_copy", "new_name": "病程 vs 护理 - 副本"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["code"] == "progress_vs_nursing_copy"
    assert data["default_for_schedule"] is False


def test_test_source_returns_bundle_statistics(monkeypatch):
    registry = _FakeRegistry([_build_audit_type("labexam_vs_progress", "检验检查 vs 病程")])
    monkeypatch.setattr(audit_types, "AuditTypeRegistry", lambda: registry)

    def _mock_load_bundles(**kwargs):
        bundles = [
            SimpleNamespace(bundle_id="bundle-1", sources={"primary": [1, 2], "reference": [3]}, group_values={"patient_id": "p1", "visit_number": "1"}),
            SimpleNamespace(bundle_id="bundle-2", sources={"primary": [4], "reference": []}, group_values={"patient_id": "p2", "visit_number": "1"}),
        ]
        if kwargs.get("return_diagnostics"):
            return bundles, {"source_row_counts": {"primary": 4, "reference": 2}, "skipped_records": 0, "missing_required_bundles": 0}
        return bundles

    monkeypatch.setattr(audit_types, "load_patient_bundles", _mock_load_bundles)

    client = _make_client()
    response = client.post(
        "/api/audit-types/labexam_vs_progress/test-source",
        json={"query_date": "2026-04-17", "date_dimension": "query_date", "dept_filter": ["内科"]},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["bundle_count"] == 2
    assert data["sample_bundle"] == "bundle-1"
    assert data["source_counts"]["primary"] == 3
    assert data["source_counts"]["reference"] == 1


def test_test_dify_returns_parsed_summary(monkeypatch):
    registry = _FakeRegistry([_build_audit_type("order_vs_nursing", "医嘱 vs 护理")])
    monkeypatch.setattr(audit_types, "AuditTypeRegistry", lambda: registry)
    monkeypatch.setattr(
        audit_types,
        "push_to_dify",
        lambda *_args, **_kwargs: {
            "status": "success",
            "inconsistency": True,
            "severity": "high",
            "risk_score": 88,
            "parsed_output": {"overall_conclusion": "存在问题"},
        },
    )

    client = _make_client()
    response = client.post(
        "/api/audit-types/order_vs_nursing/test-dify",
        json={"mr_txt_sample": "sample text"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["audit_type_code"] == "order_vs_nursing"
    assert data["status"] == "success"
    assert data["inconsistency"] is True
    assert data["parsed_output"]["overall_conclusion"] == "存在问题"
