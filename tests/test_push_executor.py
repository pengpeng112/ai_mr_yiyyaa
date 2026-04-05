from app.services.push_executor import PushExecutor, PushConfig


def test_enforce_authoritative_patient_fields_overrides_parsed_output():
    executor = PushExecutor(dify_config={})
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
    records = [{"患者ID": "p001", "次数": "2", "患者姓名": "张三", "所在科室名称": "耳鼻喉科"}]

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


def test_create_skipped_push_log_contains_skip_reason():
    executor = PushExecutor(dify_config={})
    config = PushConfig(trigger_type="auto", query_date="2026-04-05")
    records = [{"患者姓名": "张三", "住院号": "a1", "次数": "1", "所在科室名称": "耳鼻喉科"}]

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
