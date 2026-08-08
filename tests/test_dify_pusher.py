"""Dify pusher 安全网测试 —— 覆盖 sanitize、解析、请求构造核心行为。"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.dify_pusher import (
    _merge_safe_extra_inputs,
    _sanitize_extra_inputs,
    apply_response_paths,
    parse_dify_structured_output,
    push_to_dify,
    sanitize_extra_inputs,
)


# ── sanitize_extra_inputs ──────────────────────────────────────────────────


class TestSanitizeExtraInputs:
    def test_filters_reserved_keys(self):
        extra = {
            "inputs": {"nested": 1},
            "response_mode": "blocking",
            "user": "u1",
            "files": [],
            "hospital_id": "H1",
        }
        result = sanitize_extra_inputs(extra, "mr_txt")
        assert result["hospital_id"] == "H1"
        assert "response_mode" not in result
        assert "user" not in result
        assert "files" not in result
        assert "inputs" not in result
        # nested inputs are flattened (top-level reserved keys filtered, but nested values are merged)
        assert result["nested"] == 1

    def test_filters_main_input_variable(self):
        extra = {"mr_txt": "should_be_removed", "hospital_id": "H1"}
        result = sanitize_extra_inputs(extra, "mr_txt")
        assert "mr_txt" not in result
        assert result["hospital_id"] == "H1"

    def test_filters_custom_main_input_variable(self):
        extra = {"custom_var": "removed", "hospital_id": "H1"}
        result = sanitize_extra_inputs(extra, "custom_var")
        assert "custom_var" not in result
        assert result["hospital_id"] == "H1"

    def test_flattens_nested_inputs(self):
        extra = {
            "hospital_id": "H1",
            "inputs": {"mr_type": "检验检查与病历护理核查", "extra_param": "v2"},
        }
        result = sanitize_extra_inputs(extra, "mr_txt")
        assert result["hospital_id"] == "H1"
        assert result["mr_type"] == "检验检查与病历护理核查"
        assert result["extra_param"] == "v2"

    def test_nested_does_not_override_existing(self):
        extra = {
            "mr_type": "top_level",
            "inputs": {"mr_type": "nested_level"},
        }
        result = sanitize_extra_inputs(extra, "mr_txt")
        assert result["mr_type"] == "top_level"

    def test_returns_empty_for_non_dict(self):
        assert sanitize_extra_inputs(None, "mr_txt") == {}
        assert sanitize_extra_inputs("string", "mr_txt") == {}
        assert sanitize_extra_inputs([], "mr_txt") == {}

    def test_strips_empty_keys(self):
        extra = {"": "val", "  ": "val2", "hospital_id": "H1"}
        result = sanitize_extra_inputs(extra, "mr_txt")
        assert result == {"hospital_id": "H1"}


class TestSanitizeExtraInputsPrivateWrapper:
    def test_delegates_to_public_function(self):
        extra = {"mr_type": "test", "inputs": {"a": 1}}
        assert _sanitize_extra_inputs(extra) == sanitize_extra_inputs(extra)


class TestMergeSafeExtraInputs:
    def test_main_input_not_overridden_by_extra(self):
        config = {"extra_inputs": {"mr_txt": "should_be_ignored", "hospital_id": "H1"}}
        inputs, ignored = _merge_safe_extra_inputs("mr_txt", "main_payload", config)
        assert inputs["mr_txt"] == "main_payload"
        assert inputs["hospital_id"] == "H1"
        # sanitize_extra_inputs filters mr_txt from extra, so it never reaches merge loop
        # the ignored list tracks keys that survived sanitize but conflict at merge time
        assert "mr_txt" not in inputs or inputs["mr_txt"] == "main_payload"

    def test_extra_keys_merged_safely(self):
        config = {"extra_inputs": {"mr_type": "检验检查", "hospital_id": "H1"}}
        inputs, ignored = _merge_safe_extra_inputs("mr_txt", "payload", config)
        assert inputs["mr_txt"] == "payload"
        assert inputs["mr_type"] == "检验检查"
        assert inputs["hospital_id"] == "H1"
        assert ignored == []


# ── parse_dify_structured_output ───────────────────────────────────────────


class TestParseNewSchema:
    def test_parses_patient_summary_and_dimensions(self):
        outputs = {
            "aa": json.dumps(
                {
                    "version": "2.0",
                    "patient_summary": {
                        "patient_id": "P001",
                        "visit_number": "1",
                        "patient_name": "张三",
                        "dept": "内科",
                        "query_date": "2026-05-01",
                    },
                    "audit_summary": {
                        "inconsistency": True,
                        "severity": "high",
                        "risk_score": 90,
                        "overall_conclusion": "存在高风险不一致",
                        "alert_level": "red",
                        "closure_hours": 24,
                        "push_strategy": "immediate",
                        "outcome_bucket": "primary",
                    },
                    "dimensions": [
                        {
                            "dimension_code": "lab_abnormal_followup",
                            "dimension": "异常检验结果关注",
                            "status": "fail",
                            "severity": "high",
                            "confidence": 0.95,
                            "issue_summary": "白细胞异常未记录处置",
                            "recommendation": "补充病程记录",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        }
        result = parse_dify_structured_output(outputs, "aa")
        assert result["parse_success"] is True
        assert result["patient_id"] == "P001"
        assert result["patient_name"] == "张三"
        assert result["inconsistency"] is True
        assert result["severity"] == "high"
        assert result["risk_score"] == 90
        assert len(result["dimensions"]) == 1
        assert result["dimensions"][0]["dimension_code"] == "lab_abnormal_followup"

    def test_dimension_problem_overrides_conflicting_safe_summary(self):
        outputs = {
            "aa": json.dumps(
                {
                    "audit_summary": {
                        "has_inconsistency": False,
                        "severity": "low",
                        "overall_conclusion": "未见明确冲突",
                    },
                    "dimensions": [
                        {
                            "dimension_code": "treatment_measure_consistency",
                            "dimension": "治疗措施一致性",
                            "status": "unknown",
                            "severity": "high",
                            "issue_summary": "病程记录为全麻，护理记录为局麻",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        }

        result = parse_dify_structured_output(outputs, "aa")

        assert result["inconsistency"] is True
        assert result["severity"] == "high"
        assert result["alert_level"] == "red"
        assert "summary_dimension_inconsistency_conflict" in result["parse_warning"]

    def test_admission_dimension_code_is_canonicalized_with_raw_value_retained(self):
        outputs = {
            "aa": json.dumps(
                {
                    "audit_summary": {"has_inconsistency": True, "severity": "high"},
                    "dimensions": [
                        {
                            "dimension_code": "physical_exam_consistency",
                            "dimension": "体格检查一致性",
                            "status": "fail",
                            "severity": "high",
                            "issue_summary": "两份记录体征不一致",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        }

        result = parse_dify_structured_output(
            outputs,
            "aa",
            audit_type_code="admission_vs_first_progress",
        )

        dimension = result["dimensions"][0]
        assert dimension["dimension_code"] == "physical_examination"
        assert dimension["extra"]["raw_dimension_code"] == "physical_exam_consistency"

    def test_new_schema_preserves_dimension_extra_and_reasoning(self):
        outputs = {
            "aa": json.dumps(
                {
                    "audit_summary": {"has_inconsistency": False, "severity": "low"},
                    "dimensions": [
                        {
                            "dimension_code": "text_quality",
                            "dimension_name": "文本质量",
                            "status": "unknown",
                            "severity": "low",
                            "reasoning": "原文不足以判断是否存在模板残留。",
                            "extra": {"manual_review": [{"review_type": "template_check"}]},
                        }
                    ],
                },
                ensure_ascii=False,
            )
        }

        result = parse_dify_structured_output(outputs, "aa")

        dimension = result["dimensions"][0]
        assert dimension["reasoning"] == "原文不足以判断是否存在模板残留。"
        assert dimension["extra"]["manual_review"][0]["review_type"] == "template_check"

    def test_admission_high_without_both_evidence_is_downgraded(self):
        outputs = {
            "aa": json.dumps(
                {
                    "audit_summary": {
                        "has_inconsistency": True,
                        "severity": "high",
                        "risk_score": 90,
                        "alert_level": "red",
                    },
                    "dimensions": [
                        {
                            "dimension_code": "diagnosis_consistency",
                            "dimension_name": "诊断一致性",
                            "status": "fail",
                            "severity": "high",
                            "confidence": 0.9,
                            "alert_level": "red",
                            "issue_summary": "诊断记录不一致",
                            "medical_evidence": ["入院记录诊断 A"],
                            "nursing_evidence": [],
                        }
                    ],
                },
                ensure_ascii=False,
            )
        }

        result = parse_dify_structured_output(
            outputs,
            "aa",
            audit_type_code="admission_vs_first_progress",
        )

        dimension = result["dimensions"][0]
        assert dimension["status"] == "unknown"
        assert dimension["severity"] == "low"
        assert dimension["alert_level"] == "gray"
        assert dimension["extra"]["manual_review"][0]["review_type"] == "high_risk_evidence_insufficient"
        assert result["inconsistency"] is False
        assert result["severity"] == "low"
        assert result["alert_level"] == "gray"
        assert "high_risk_guard_downgraded" in result["parse_warning"]

    def test_admission_high_with_both_evidence_is_preserved(self):
        outputs = {
            "aa": json.dumps(
                {
                    "audit_summary": {
                        "has_inconsistency": True,
                        "severity": "high",
                        "risk_score": 90,
                        "alert_level": "red",
                    },
                    "dimensions": [
                        {
                            "dimension_code": "diagnosis_consistency",
                            "dimension_name": "诊断一致性",
                            "status": "fail",
                            "severity": "high",
                            "confidence": 0.9,
                            "alert_level": "red",
                            "issue_summary": "诊断记录不一致",
                            "medical_evidence": ["入院记录诊断 A"],
                            "nursing_evidence": ["首次病程诊断 B"],
                            "extra": {
                                "issues": [{
                                    "level": "severe",
                                    "high_eligible": True,
                                    "issue_mode": "contradiction",
                                    "safety_category": "critical_diagnosis_basis",
                                    "source_a": "admission_record",
                                    "evidence_a": "入院记录诊断 A",
                                    "source_b": "first_progress_record",
                                    "evidence_b": "首次病程诊断 B",
                                    "confidence": 0.9,
                                }]
                            },
                        }
                    ],
                },
                ensure_ascii=False,
            )
        }

        result = parse_dify_structured_output(
            outputs,
            "aa",
            audit_type_code="admission_vs_first_progress",
        )

        dimension = result["dimensions"][0]
        assert dimension["status"] == "fail"
        assert dimension["severity"] == "high"
        assert result["severity"] == "high"
        assert result["alert_level"] == "red"

    def test_other_dimension_cannot_be_high_even_with_complete_metadata(self):
        outputs = {
            "aa": json.dumps(
                {
                    "audit_summary": {
                        "has_inconsistency": True,
                        "severity": "high",
                        "risk_score": 90,
                        "alert_level": "red",
                    },
                    "dimensions": [
                        {
                            "dimension_code": "other",
                            "dimension_name": "其他",
                            "status": "fail",
                            "severity": "high",
                            "confidence": 0.9,
                            "alert_level": "red",
                            "issue_summary": "模型输出了白名单外维度",
                            "medical_evidence": ["入院记录原文 A"],
                            "nursing_evidence": ["首次病程原文 B"],
                            "extra": {
                                "issues": [{
                                    "level": "severe",
                                    "high_eligible": True,
                                    "issue_mode": "contradiction",
                                    "safety_category": "critical_diagnosis_basis",
                                    "source_a": "admission_record",
                                    "evidence_a": "入院记录原文 A",
                                    "source_b": "first_progress_record",
                                    "evidence_b": "首次病程原文 B",
                                    "confidence": 0.9,
                                }]
                            },
                        }
                    ],
                },
                ensure_ascii=False,
            )
        }

        result = parse_dify_structured_output(
            outputs,
            "aa",
            audit_type_code="admission_vs_first_progress",
        )

        dimension = result["dimensions"][0]
        assert dimension["severity"] == "medium"
        assert dimension["alert_level"] == "yellow"
        assert (
            "dimension_code_other_not_high_eligible"
            in dimension["extra"]["manual_review"][0]["reason_codes"]
        )
        assert result["severity"] == "medium"
        assert result["alert_level"] == "yellow"

    @pytest.mark.parametrize(
        "audit_type_code",
        [
            "admission_vs_first_progress",
            "discharge_vs_frontpage",
            "surgery_chain",
            "progress_vs_nursing",
            "jyjc_vs_bcnursing",
            "syssvsscbc",
        ],
    )
    def test_all_six_types_downgrade_one_sided_high(self, audit_type_code):
        outputs = {
            "aa": json.dumps({
                "audit_summary": {
                    "has_inconsistency": True,
                    "severity": "high",
                    "risk_score": 90,
                    "alert_level": "red",
                },
                "dimensions": [{
                    "dimension_code": "timeline_consistency",
                    "dimension_name": "时间一致性",
                    "status": "fail",
                    "severity": "high",
                    "confidence": 0.95,
                    "alert_level": "red",
                    "issue_summary": "仅有一侧记录",
                    "medical_evidence": ["来源A原文"],
                    "nursing_evidence": [],
                }],
            }, ensure_ascii=False)
        }

        result = parse_dify_structured_output(outputs, "aa", audit_type_code=audit_type_code)

        assert result["severity"] == "low"
        assert result["alert_level"] == "gray"
        assert result["inconsistency"] is False
        assert result["dimensions"][0]["status"] == "unknown"
        assert "high_risk_guard_downgraded" in result["parse_warning"]

    def test_bilateral_issue_without_complete_high_metadata_is_kept_as_medium(self):
        outputs = {
            "aa": json.dumps({
                "audit_summary": {"has_inconsistency": True, "severity": "high", "alert_level": "red"},
                "dimensions": [{
                    "dimension_code": "condition_consistency",
                    "dimension_name": "病情描述一致性",
                    "status": "fail",
                    "severity": "high",
                    "confidence": 0.9,
                    "alert_level": "red",
                    "issue_summary": "双方存在明确差异，但不属于受控高危类别",
                    "medical_evidence": ["病程记录：患者清醒"],
                    "nursing_evidence": ["护理记录：患者嗜睡"],
                }],
            }, ensure_ascii=False)
        }

        result = parse_dify_structured_output(
            outputs, "aa", audit_type_code="progress_vs_nursing"
        )

        assert result["severity"] == "medium"
        assert result["alert_level"] == "yellow"
        assert result["inconsistency"] is True
        assert result["dimensions"][0]["status"] == "warn"
        assert result["dimensions"][0]["push_strategy"] == "batch"

    def test_warn_cannot_remain_high_even_with_bilateral_evidence(self):
        outputs = {
            "aa": json.dumps({
                "audit_summary": {"has_inconsistency": True, "severity": "high", "alert_level": "red"},
                "dimensions": [{
                    "dimension_code": "condition_consistency",
                    "dimension_name": "病情描述一致性",
                    "status": "warn",
                    "severity": "high",
                    "confidence": 0.9,
                    "alert_level": "red",
                    "issue_summary": "一般差异",
                    "medical_evidence": ["病程原文"],
                    "nursing_evidence": ["护理原文"],
                }],
            }, ensure_ascii=False)
        }

        result = parse_dify_structured_output(
            outputs, "aa", audit_type_code="progress_vs_nursing"
        )

        assert result["severity"] == "medium"
        assert result["dimensions"][0]["status"] == "warn"

    def test_unstructured_fallback_never_infers_high(self):
        result = parse_dify_structured_output(
            {"aa": "存在严重不一致 high，建议立即处理"},
            "aa",
            audit_type_code="surgery_chain",
        )

        assert result["parse_success"] is False
        assert result["severity"] == "medium"
        assert "fallback_high_suppressed" in result["parse_warning"]


class TestParseLegacySchema:
    def test_parses_chinese_field_names(self):
        outputs = {
            "aa": json.dumps(
                {
                    "患者姓名": "李四",
                    "患者ID": "P002",
                    "核查结果": [
                        {
                            "维度": "诊断一致性",
                            "状态": "✅",
                            "说明": "一致",
                        }
                    ],
                    "总体结论": "无不一致",
                    "重点关注项": [],
                },
                ensure_ascii=False,
            )
        }
        result = parse_dify_structured_output(outputs, "aa")
        assert result["parse_success"] is True
        assert result["patient_name"] == "李四"
        assert result["patient_id"] == "P002"
        assert len(result["dimensions"]) == 1
        assert result["inconsistency"] is False


class TestOutputKeyFallback:
    def test_falls_back_to_result_key(self):
        outputs = {"result": json.dumps({"总体结论": "test", "核查结果": []})}
        result = parse_dify_structured_output(outputs, "aa")
        assert result["parse_success"] is True

    def test_falls_back_to_single_key(self):
        outputs = {"only_one": json.dumps({"总体结论": "single", "核查结果": []})}
        result = parse_dify_structured_output(outputs, "aa")
        assert result["parse_success"] is True

    def test_returns_empty_when_no_keys_and_multiple(self):
        outputs = {"a": "x", "b": "y"}
        result = parse_dify_structured_output(outputs, "aa")
        assert result["parse_success"] is False
        assert result["raw_text"]


class TestJsonCodeFence:
    def test_strips_code_fence_and_parses(self):
        json_content = json.dumps({"总体结论": "ok", "核查结果": []}, ensure_ascii=False)
        outputs = {"aa": f"```json\n{json_content}\n```"}
        result = parse_dify_structured_output(outputs, "aa")
        assert result["parse_success"] is True


class TestEmptyJsonResult:
    def test_empty_json_marks_parse_failure(self):
        outputs = {"aa": "{}"}
        result = parse_dify_structured_output(outputs, "aa")
        assert result["parse_success"] is False
        assert "empty_after_json_parse" in result["parse_warning"]


class TestKeywordFallback:
    def test_inconsistency_keyword_triggers_fallback(self):
        outputs = {"aa": '{"text": "存在不一致，需要关注"}'}
        result = parse_dify_structured_output(outputs, "aa")
        assert result["inconsistency"] is True
        assert result["fallback_inference"] is True

    def test_negative_inconsistency_does_not_trigger(self):
        outputs = {"aa": '{"text": "无不一致，检查正常"}'}
        result = parse_dify_structured_output(outputs, "aa")
        assert result["inconsistency"] is False


# ── push_to_dify ──────────────────────────────────────────────────────────


class TestPushToDify:
    def test_main_input_is_string(self, monkeypatch):
        captured = {}

        def mock_post(url, headers=None, json=None, timeout=None):
            captured["payload"] = json
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {
                "workflow_run_id": "wr-1",
                "task_id": "t-1",
                "data": {"outputs": {"aa": '{"总体结论":"ok","核查结果":[]}'}},
            }
            return resp

        monkeypatch.setattr("app.dify_pusher.requests.post", mock_post)
        config = {
            "base_url": "http://dify.local/v1",
            "api_key": "k1",
            "workflow_input_variable": "mr_txt",
            "workflow_output_key": "aa",
            "timeout_seconds": 30,
        }
        result = push_to_dify("test_mr_text", config, "P001")
        assert result["status"] == "success"
        main_input = captured["payload"]["inputs"]["mr_txt"]
        assert isinstance(main_input, str)

    def test_extra_inputs_do_not_override_main_input(self, monkeypatch):
        captured = {}

        def mock_post(url, headers=None, json=None, timeout=None):
            captured["payload"] = json
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {
                "workflow_run_id": "wr-1",
                "task_id": "t-1",
                "data": {"outputs": {"aa": '{"总体结论":"ok","核查结果":[]}'}},
            }
            return resp

        monkeypatch.setattr("app.dify_pusher.requests.post", mock_post)
        config = {
            "base_url": "http://dify.local/v1",
            "api_key": "k1",
            "workflow_input_variable": "mr_txt",
            "workflow_output_key": "aa",
            "timeout_seconds": 30,
            "extra_inputs": {"mr_txt": "should_be_ignored", "hospital_id": "H1"},
        }
        result = push_to_dify("real_payload", config, "P001")
        assert result["status"] == "success"
        inputs = captured["payload"]["inputs"]
        assert inputs["mr_txt"] == "real_payload"
        assert inputs["hospital_id"] == "H1"
def test_push_to_dify_passes_expected_dimension_override(monkeypatch):
    from app import dify_pusher

    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "workflow_run_id": "wf-1",
                "task_id": "task-1",
                "data": {"outputs": {"hcjg": '{"dimensions":[{"dimension_code":"chief_complaint"}]}' }},
            }

    monkeypatch.setattr(dify_pusher.requests, "post", lambda *args, **kwargs: Response())
    monkeypatch.setattr(
        dify_pusher,
        "parse_dify_structured_output",
        lambda *args, **kwargs: {
            "parse_success": True,
            "dimensions": [{"dimension_code": "chief_complaint"}],
        },
    )

    def validate(result, audit_type_code, expected_dimensions_override=None):
        captured["code"] = audit_type_code
        captured["dimensions"] = expected_dimensions_override
        return True, []

    import app.services.result_contract_validator as validator
    monkeypatch.setattr(validator, "validate_result_contract", validate)

    result = dify_pusher.push_to_dify(
        "sample",
        {
            "base_url": "http://dify.invalid/v1",
            "api_key": "test-key",
            "workflow_output_key": "hcjg",
        },
        "test-patient",
        audit_type_code="admission_vs_first_progress",
        expected_dimensions_override=["chief_complaint"],
    )

    assert result["contract_valid"] is True
    assert captured == {
        "code": "admission_vs_first_progress",
        "dimensions": ["chief_complaint"],
    }
