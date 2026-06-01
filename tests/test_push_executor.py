from types import SimpleNamespace

from app.services.push_executor import PushConfig, PushExecutor, with_audit_type_mr_type


def test_enforce_authoritative_patient_fields_overrides_parsed_output():
    executor = PushExecutor(
        dify_config={},
        field_mapping={
            "patient_id": "patient_id",
            "visit_number": "visit_number",
            "patient_name": "patient_name",
            "dept": "dept",
            "admission_no": "admission_no",
        },
    )
    dify_result = {
        "parsed_output": {
            "patient_id": "llm_id",
            "visit_number": "llm_visit",
            "patient_name": "llm_name",
            "dept": "llm_dept",
            "audit_date": "1999-01-01",
        }
    }
    payload = {
        "audit_date": "2026-04-05",
        "patient_info": {
            "patient_id": "p001",
            "visit_number": "2",
            "patient_name": "张三",
            "department": "耳鼻喉科",
        },
    }
    records = [
        {
            "patient_id": "p001",
            "visit_number": "2",
            "patient_name": "张三",
            "dept": "耳鼻喉科",
            "admission_no": "zyh-1",
        }
    ]

    executor._enforce_authoritative_patient_fields(
        dify_result=dify_result,
        payload=payload,
        patient_records=records,
        query_date="2026-04-05",
        patient_id="p001",
    )

    parsed = dify_result["parsed_output"]
    assert parsed["patient_id"] == "p001"
    assert parsed["visit_number"] == "2"
    assert parsed["patient_name"] == "张三"
    assert parsed["dept"] == "耳鼻喉科"
    assert parsed["audit_date"] == "2026-04-05"


def test_create_skipped_push_log_contains_skip_reason_and_source_key():
    executor = PushExecutor(
        dify_config={},
        field_mapping={
            "patient_name": "patient_name",
            "admission_no": "admission_no",
            "visit_number": "visit_number",
            "dept": "dept",
        },
    )
    config = PushConfig(trigger_type="auto", query_date="2026-04-05")
    records = [
        {
            "mrid": "mr-001",
            "patient_name": "张三",
            "admission_no": "a1",
            "visit_number": "1",
            "dept": "耳鼻喉科",
        }
    ]

    log = executor._create_skipped_push_log(
        patient_id="p001_1",
        patient_records=records,
        push_config=config,
        skip_reason="unreviewed_pending",
        skip_message="已推送但未复核",
    )

    assert log.patient_id == "p001"
    assert log.status == "skipped"
    assert log.pushed_flag == 0
    assert log.audit_type_code == "progress_vs_nursing"
    assert log.skip_reason == "unreviewed_pending"
    assert log.error_msg == "已推送但未复核"
    assert log.source_record_key == "mrid::mr-001"


def test_create_push_log_sets_source_record_key_from_mrid():
    executor = PushExecutor(
        dify_config={},
        field_mapping={
            "patient_name": "patient_name",
            "admission_no": "admission_no",
            "visit_number": "visit_number",
            "dept": "dept",
        },
    )
    config = PushConfig(trigger_type="manual", query_date="2026-04-06")
    records = [
        {
            "mrid": "mr-002",
            "patient_name": "李四",
            "admission_no": "zyh-1",
            "visit_number": "2",
            "dept": "测试科室",
        }
    ]
    dify_result = {
        "status": "success",
        "workflow_run_id": "wf-1",
        "task_id": "task-1",
        "result": {"ok": True},
        "parsed_output": {"parse_success": True, "version": "1.0"},
    }

    log = executor._create_push_log(
        patient_id="p001_2",
        patient_records=records,
        dify_result=dify_result,
        payload={"patient_info": {"patient_id": "p001"}},
        mr_text="mock",
        push_config=config,
    )

    assert log.patient_id == "p001"
    assert log.source_record_key == "mrid::mr-002"
    assert log.audit_type_code == "progress_vs_nursing"
    assert log.status == "success"


def test_with_audit_type_mr_type_injects_legacy_progress_type():
    audit_type = SimpleNamespace(
        code="progress_vs_nursing",
        name="病程 vs 护理",
        payload={"builder": "legacy_progress_nursing"},
        dify={"extra_inputs": {}},
    )

    cfg = with_audit_type_mr_type({"extra_inputs": {"hospital_id": "h1"}}, audit_type)

    assert cfg["extra_inputs"]["hospital_id"] == "h1"
    assert cfg["extra_inputs"]["mr_type"] == "医嘱与病程及护理核查"


def test_with_audit_type_mr_type_keeps_configured_value():
    audit_type = SimpleNamespace(
        code="progress_vs_nursing",
        name="病程 vs 护理",
        payload={"builder": "legacy_progress_nursing"},
        dify={"extra_inputs": {"mr_type": "自定义核查类型"}},
    )

    cfg = with_audit_type_mr_type({"extra_inputs": {"mr_type": "自定义核查类型"}}, audit_type)

    assert cfg["extra_inputs"]["mr_type"] == "自定义核查类型"


def test_lab_exam_skip_when_progress_nursing_context_empty():
    payload = {
        "abnormal_labs": {"items": [{"item_name": "白细胞", "result": "20"}]},
        "abnormal_exams": {"reports": []},
        "progress_context": {"records": []},
        "nursing_context": {"records": []},
    }

    reason = PushExecutor._get_empty_lab_exam_skip_reason(payload)

    assert reason == "病程和护理记录均为空，跳过 Dify 推送"


def test_lab_exam_allows_when_both_sides_have_data():
    payload = {
        "abnormal_labs": {"items": []},
        "abnormal_exams": {"reports": [{"exam_no": "E1", "summary": "异常"}]},
        "progress_context": {"records": [{"content": "已关注检查结果"}]},
        "nursing_context": {"records": []},
    }

    assert PushExecutor._get_empty_lab_exam_skip_reason(payload) == ""
