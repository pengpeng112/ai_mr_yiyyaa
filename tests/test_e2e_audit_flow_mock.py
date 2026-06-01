from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import AuditConclusion, AuditDimensionResult, PushLog
from app.services.push_executor import PushConfig, PushExecutor


def test_mock_audit_flow_persists_structured_results(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    def fake_push_to_dify(*_args, **_kwargs):
        return {
            "status": "success",
            "workflow_run_id": "wf-001",
            "task_id": "task-001",
            "result": {"aa": "mock"},
            "raw_response": {"dimensions": []},
            "elapsed_ms": 12,
            "inconsistency": True,
            "severity": "high",
            "risk_score": 88,
            "parsed_output": {
                "version": "1.0",
                "patient_id": "p001",
                "visit_number": "1",
                "patient_name": "张三",
                "dept": "心内科",
                "audit_date": "2026-04-27",
                "inconsistency": True,
                "severity": "high",
                "risk_score": 88,
                "overall_conclusion": "存在高风险异常未记录闭环。",
                "focus_items": ["肌钙蛋白异常"],
                "dimensions": [
                    {
                        "dimension_code": "lab_abnormal_followup",
                        "dimension": "异常检验随访",
                        "status": "fail",
                        "severity": "high",
                        "confidence": 0.91,
                        "issue_summary": "检验异常未见病程评估。",
                        "recommendation": "补充病程记录和处理措施。",
                        "medical_evidence": ["肌钙蛋白升高"],
                        "nursing_evidence": [],
                    }
                ],
            },
        }

    monkeypatch.setattr("app.services.push_executor.push_to_dify", fake_push_to_dify)
    executor = PushExecutor(
        dify_config={"base_url": "http://dify.local/v1", "api_key": "k", "workflow_input_variable": "mr_txt"},
        field_mapping={
            "patient_id": "patient_id",
            "visit_number": "visit_number",
            "patient_name": "patient_name",
            "dept": "dept",
            "admission_no": "admission_no",
        },
    )
    result = executor.execute(
        db,
        {
            "p001_1": [
                {
                    "patient_id": "p001",
                    "visit_number": "1",
                    "patient_name": "张三",
                    "dept": "心内科",
                    "admission_no": "zy001",
                    "病历文书_内容": "患者胸痛，待复查。",
                    "护理记录_内容": "生命体征平稳。",
                }
            ]
        },
        PushConfig(trigger_type="manual", query_date="2026-04-27", audit_type_code="progress_vs_nursing", interval_ms=0),
    )

    assert result.success == 1
    log = db.query(PushLog).one()
    assert log.status == "success"
    assert log.patient_id == "p001"
    assert log.inconsistency == 1
    assert log.risk_score == 88
    dimension = db.query(AuditDimensionResult).one()
    assert dimension.push_log_id == log.id
    assert dimension.dimension_code == "lab_abnormal_followup"
    conclusion = db.query(AuditConclusion).one()
    assert conclusion.push_log_id == log.id
    assert conclusion.risk_score == 88

    db.close()
