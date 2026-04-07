from app.routers import push as push_router
from app.schemas import ManualPushRequest


def test_should_use_bulk_executor_by_parallel_workers():
    body = ManualPushRequest(query_date="2026-04-06", parallel_workers=2)
    assert push_router._should_use_bulk_executor(body) is True


def test_should_use_bulk_executor_by_empty_retry():
    body = ManualPushRequest(query_date="2026-04-06", empty_retry_max=1)
    assert push_router._should_use_bulk_executor(body) is True


def test_should_use_bulk_executor_by_dify_targets():
    body = ManualPushRequest(
        query_date="2026-04-06",
        dify_targets=[
            {
                "name": "a",
                "base_url": "http://dify-a/v1",
                "api_key": "k1",
                "workflow_input_variable": "mr_txt",
                "workflow_output_key": "aa",
                "user_identifier": "u1",
                "timeout_seconds": 30,
                "weight": 1,
                "enabled": True,
            }
        ],
    )
    assert push_router._should_use_bulk_executor(body) is True


def test_should_not_use_bulk_executor_when_no_bulk_options():
    body = ManualPushRequest(query_date="2026-04-06")
    assert push_router._should_use_bulk_executor(body) is False


def test_effective_parallel_workers_capped_in_sqlite(monkeypatch):
    monkeypatch.setattr(push_router, "get_app_db_type", lambda: "sqlite")
    workers, note = push_router._effective_parallel_workers(32)
    assert workers == 4
    assert "sqlite mode" in note


def test_effective_parallel_workers_not_capped_in_other_db(monkeypatch):
    monkeypatch.setattr(push_router, "get_app_db_type", lambda: "oracle")
    workers, note = push_router._effective_parallel_workers(16)
    assert workers == 16
    assert note == ""


def test_build_manual_dify_targets_merges_default_config():
    body = ManualPushRequest(
        query_date="2026-04-06",
        dify_targets=[
            {
                "name": "a",
                "base_url": "http://dify-a/v1",
                "api_key": "k-a",
                "workflow_input_variable": "mr_txt",
                "workflow_output_key": "aa",
                "user_identifier": "user-a",
                "timeout_seconds": 20,
                "weight": 1,
                "enabled": True,
            }
        ],
    )
    base_dify_cfg = {
        "base_url": "http://default/v1",
        "api_key": "k-default",
        "workflow_input_variable": "mr_txt",
        "workflow_output_key": "aa",
        "user_identifier": "default-user",
        "timeout_seconds": 90,
        "extra_inputs": {"hospital_id": "x"},
    }

    targets = push_router._build_manual_dify_targets(body, base_dify_cfg)
    assert isinstance(targets, list)
    assert len(targets) == 1
    assert targets[0]["name"] == "a"
    assert targets[0]["base_url"] == "http://dify-a/v1"
    assert targets[0]["api_key"] == "k-a"
    assert targets[0]["extra_inputs"] == {"hospital_id": "x"}


def test_build_query_diagnostics_for_cybr_and_inner_join():
    body = ManualPushRequest(query_date="2026-04-06", date_dimension="discharge_date")
    diagnostics = push_router._build_query_diagnostics(
        body,
        {
            "query_sql": (
                "SELECT * FROM jhemr.v_cybr a "
                "INNER JOIN ydhl_202501 c ON c.患者ID = a.患者ID "
                "WHERE a.所在科室名称 IN (:d0)"
            )
        },
        raw_rows=0,
        filtered_rows=0,
    )
    text = "\n".join(diagnostics)
    assert "已出院患者" in text
    assert "INNER JOIN" in text
    assert "ydhl_202501" in text


def test_build_query_diagnostics_empty_when_rows_found():
    body = ManualPushRequest(query_date="2026-04-06")
    diagnostics = push_router._build_query_diagnostics(body, {"query_sql": "SELECT 1 FROM dual"}, raw_rows=1, filtered_rows=1)
    assert diagnostics == []
