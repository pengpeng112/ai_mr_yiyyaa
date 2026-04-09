from app.services.push_executor import PushConfig, PushExecutor


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
    assert log.status == "success"
