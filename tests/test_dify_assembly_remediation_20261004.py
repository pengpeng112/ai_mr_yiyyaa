# -*- coding: utf-8 -*-
"""2026-10-04 059 AUD-A1/A2/A3 组装层缺陷回归测试。

来源：docs/ACTIVE/059 §11（09-30 组装层疑点独立复现坐实）。
- AUD-A1 status 语义翻转：normalize_status 否定语义必须先于肯定语义
  （"不一致"包含"一致"、"未通过"包含"通过"，顺序错误会把失败翻成 pass）。
- AUD-A2 缺省结论字面量：非护理对照类型不得出现"护理记录"字样缺省结论。
- AUD-A3 问题维度缺说明：warn/fail 维度无 explanation/issue_summary 时
  必须打 problem_dimension_missing_explanation 可观测标记。
060 绑定：B08/B09/Q12/Q16。
"""
import json

from app.dify_pusher import parse_dify_structured_output
from app.services.dify_result_normalizer import normalize_status


def _payload(dim_status: str, *, severity: str = "high", issue_summary: str = "诊断矛盾",
             nursing_evidence: list | None = None, audit_type: str = "admission_vs_first_progress") -> dict:
    return {
        "patient_summary": {"patient_id": "P001", "visit_number": "1", "patient_name": "测试", "query_date": "2026-10-04"},
        "audit_summary": {"has_inconsistency": True, "severity": severity, "overall_conclusion": ""},
        "dimensions": [{
            "dimension_code": "diagnosis_consistency", "dimension": "诊断一致性",
            "status": dim_status, "severity": severity, "confidence": 0.9,
            "issue_summary": issue_summary,
            "medical_evidence": ["入院记录: 诊断A"],
            "nursing_evidence": nursing_evidence if nursing_evidence is not None else ["首次病程: 诊断B"],
        }],
    }


def _parse(payload: dict, audit_type: str = "admission_vs_first_progress") -> dict:
    return parse_dify_structured_output({"aa": json.dumps(payload, ensure_ascii=False)}, "aa", audit_type_code=audit_type)


class TestNormalizeStatusNegationFirst:
    """AUD-A1：否定语义先于肯定语义。"""

    def test_negation_phrases_map_to_fail(self):
        for raw in ["不一致", "未通过", "不符合", "诊断不一致", "时间线不一致", "失败"]:
            assert normalize_status(raw) == "fail", raw

    def test_affirmation_phrases_still_map_to_pass(self):
        for raw in ["一致", "通过", "基本一致", "✅", "通过核查"]:
            assert normalize_status(raw) == "pass", raw

    def test_canonical_and_emoji_unchanged(self):
        assert normalize_status("pass") == "pass"
        assert normalize_status("fail") == "fail"
        assert normalize_status("warn") == "warn"
        assert normalize_status("unknown") == "unknown"
        assert normalize_status("❌") == "fail"
        assert normalize_status("⚠ 警告") == "warn"
        assert normalize_status("mismatch") == "fail"

    def test_e2e_flip_repaired(self):
        """端到端：模型输出 status='不一致' 时问题信号必须保留。"""
        result = _parse(_payload("不一致"))
        assert result["inconsistency"] is True
        assert result["severity"] in {"medium", "high"}
        assert "发现需要关注的维度" in result["overall_conclusion"]


class TestDefaultConclusionTypeAware:
    """AUD-A2：缺省结论与审计类型相称。"""

    def test_non_nursing_type_gets_generic_conclusion(self):
        for audit_type in ["admission_vs_first_progress", "discharge_vs_frontpage", "surgery_chain", "syssvsscbc"]:
            payload = {
                "patient_summary": {"patient_id": "P002", "visit_number": "1", "patient_name": "测试", "query_date": "2026-10-04"},
                "audit_summary": {"has_inconsistency": False, "severity": "", "overall_conclusion": ""},
                "dimensions": [
                    {"dimension_code": "chief_complaint", "dimension": "主诉一致性", "status": "pass", "severity": "low", "confidence": 0.9, "issue_summary": ""},
                ],
            }
            result = _parse(payload, audit_type)
            assert "护理" not in result["overall_conclusion"], (audit_type, result["overall_conclusion"])
            assert result["overall_conclusion"], audit_type
            assert result["reasoning_brief"] == result["overall_conclusion"]

    def test_nursing_side_type_keeps_existing_literal(self):
        payload = {
            "patient_summary": {"patient_id": "P003", "visit_number": "1", "patient_name": "测试", "query_date": "2026-10-04"},
            "audit_summary": {"has_inconsistency": False, "severity": "", "overall_conclusion": ""},
            "dimensions": [
                {"dimension_code": "diagnosis", "dimension": "诊断一致性", "status": "pass", "severity": "low", "confidence": 0.9, "issue_summary": ""},
            ],
        }
        result = _parse(payload, "progress_vs_nursing")
        assert result["overall_conclusion"] == "病历文书与护理记录整体基本一致。"

    def test_problem_dims_conclusion_unchanged(self):
        payload = _payload("fail")
        payload["dimensions"][0]["dimension"] = "诊断一致性"
        result = _parse(payload)
        assert result["overall_conclusion"].startswith("发现需要关注的维度：诊断一致性。")


class TestProblemDimensionMissingExplanationWarning:
    """AUD-A3：问题维度缺说明的可观测标记。"""

    def test_fail_dim_without_note_flags_warning(self):
        payload = _payload("fail", issue_summary="")
        result = _parse(payload)
        assert "problem_dimension_missing_explanation" in str(result.get("parse_warning") or "")

    def test_fail_dim_with_note_not_flagged(self):
        payload = _payload("fail", issue_summary="诊断矛盾")
        result = _parse(payload)
        assert "problem_dimension_missing_explanation" not in str(result.get("parse_warning") or "")

    def test_pass_dim_without_note_not_flagged(self):
        payload = {
            "patient_summary": {"patient_id": "P004", "visit_number": "1", "patient_name": "测试", "query_date": "2026-10-04"},
            "audit_summary": {"has_inconsistency": False, "severity": "", "overall_conclusion": ""},
            "dimensions": [
                {"dimension_code": "chief_complaint", "dimension": "主诉一致性", "status": "pass", "severity": "low", "confidence": 0.9, "issue_summary": ""},
            ],
        }
        result = _parse(payload)
        assert "problem_dimension_missing_explanation" not in str(result.get("parse_warning") or "")
