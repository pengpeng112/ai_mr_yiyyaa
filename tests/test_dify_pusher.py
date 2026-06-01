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
