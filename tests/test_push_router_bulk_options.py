from app.routers import push as push_router
from app.models import PushLog
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


def test_filter_grouped_records_by_selected_record_keys():
    grouped = {
        "mrid::a": [{"mrid": "a"}],
        "mrid::b": [{"mrid": "b"}],
    }

    filtered = push_router._filter_grouped_records(grouped, ["mrid::b"])

    assert list(filtered.keys()) == ["mrid::b"]


def test_build_query_preview_rows_marks_existing_push_log():
    grouped = {
        "mrid::a": [
            {
                "MRID": "a",
                push_router.KEY_PATIENT_ID: "p001",
                push_router.KEY_VISIT_NO: "1",
                push_router.KEY_PATIENT_NAME: "张三",
                "住院号": "zyh-001",
                push_router.KEY_DEPT: "耳鼻喉科",
                push_router.KEY_MR_FINISH_TIME: "2026-04-06 08:00:00",
                "病历文书_名称": "首次病程记录",
                push_router.KEY_NURSE_CREATE_TIME: "2026-04-06 09:00:00",
                "护理记录_文书类型": "护理记录",
            }
        ]
    }
    latest_push_map = {
        "mrid::a": PushLog(id=9, source_record_key="mrid::a", status="success", reviewed_flag=1)
    }

    rows = push_router._build_query_preview_rows(
        grouped=grouped,
        field_mapping={"patient_name": push_router.KEY_PATIENT_NAME, "admission_no": "住院号", "visit_number": push_router.KEY_VISIT_NO},
        dept_field=push_router.KEY_DEPT,
        latest_push_map=latest_push_map,
    )

    assert len(rows) == 1
    assert rows[0]["record_key"] == "mrid::a"
    assert rows[0]["pushed_before"] is True
    assert rows[0]["latest_log_id"] == 9
    assert rows[0]["latest_push_status"] == "success"


def test_manual_push_request_selected_record_keys_limit():
    keys = [f"k{i}" for i in range(5001)]
    try:
        ManualPushRequest(query_date="2026-04-06", selected_record_keys=keys)
    except ValueError as exc:
        assert "selected_record_keys cannot exceed 5000" in str(exc)
    else:
        raise AssertionError("expected selected_record_keys validation error")


def test_query_preview_pagination_meta_without_paging():
    rows = [{"record_key": f"k{i}"} for i in range(3)]

    page_rows, meta = push_router._paginate_query_preview_rows(rows, page=None, page_size=None)

    assert page_rows == rows
    assert meta["paged"] is False
    assert meta["page"] == 1
    assert meta["page_size"] == 3
    assert meta["total_rows"] == 3
    assert meta["total_pages"] == 1


def test_query_preview_pagination_meta_with_paging():
    rows = [{"record_key": f"k{i}"} for i in range(25)]

    page_rows, meta = push_router._paginate_query_preview_rows(rows, page=2, page_size=10)

    assert len(page_rows) == 10
    assert page_rows[0]["record_key"] == "k10"
    assert meta["paged"] is True
    assert meta["page"] == 2
    assert meta["page_size"] == 10
    assert meta["total_rows"] == 25
    assert meta["total_pages"] == 3


def test_query_preview_pagination_page_overflow_clamped():
    rows = [{"record_key": f"k{i}"} for i in range(5)]

    page_rows, meta = push_router._paginate_query_preview_rows(rows, page=9, page_size=2)

    assert meta["page"] == 3
    assert len(page_rows) == 1
    assert page_rows[0]["record_key"] == "k4"
