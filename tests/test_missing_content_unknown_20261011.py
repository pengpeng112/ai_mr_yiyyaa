"""W5：送模文本含正文缺失标记时，结果层不得给出假 pass。

送模文本本身不改。后处理把维度改为 unknown，结论走全 unknown 文案，
并在 skip/说明 标注文书正文缺失。
"""

from app.services.dify_schema_parser import _post_process_result


def _pass_result():
    return {
        "dimensions": [
            {
                "dimension": "诊断一致性",
                "dimension_code": "diagnosis_consistency",
                "status": "pass",
                "severity": "low",
                "explanation": "模型给出通过",
                "issue_summary": "模型给出通过",
            },
            {
                "dimension": "病史一致性",
                "dimension_code": "history_consistency",
                "status": "pass",
                "severity": "low",
                "explanation": "",
                "issue_summary": "",
            },
        ],
        "overall_conclusion": "各核查维度整体基本一致。",
        "reasoning_brief": "各核查维度整体基本一致。",
        "inconsistency": False,
        "severity": "low",
        "focus_items": [],
        "parse_warning": "",
        "risk_score": 20,
    }


def test_missing_content_marker_forces_unknown_and_no_consistency_word():
    result = _pass_result()
    mr_text = "- 2026-10-11 [日常病程] 病程记录（正文缺失）\n（正文缺失）"
    _post_process_result(result, audit_type_code="progress_vs_nursing", source_text=mr_text)
    assert result["dimensions"]
    assert all(dim["status"] == "unknown" for dim in result["dimensions"])
    assert "一致" not in str(result.get("overall_conclusion") or "")
    assert result.get("inconsistency") is False
    assert result.get("skip_reason") == "文书正文缺失"
    assert all("文书正文缺失" in str(dim.get("explanation") or "") for dim in result["dimensions"])


def test_push_to_dify_applies_missing_content_guard(monkeypatch):
    """送模文本里的正文缺失标记必须穿过 push_to_dify，不能停在未被调用的参数上。"""
    from unittest.mock import MagicMock

    from app.dify_pusher import push_to_dify

    def mock_post(url, headers=None, json=None, timeout=None):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "workflow_run_id": "wr-w5",
            "task_id": "t-w5",
            "data": {
                "outputs": {
                    "aa": (
                        '{"核查结果":[{"维度":"诊断一致性","状态":"✅","说明":"模型给出通过"}],'
                        '"总体结论":"各核查维度整体基本一致。"}'
                    )
                }
            },
        }
        return resp

    monkeypatch.setattr("app.dify_pusher.requests.post", mock_post)
    result = push_to_dify(
        "病程记录（正文缺失）",
        {
            "base_url": "http://dify.local/v1",
            "api_key": "synthetic",
            "workflow_output_key": "aa",
            "timeout_seconds": 5,
        },
        "SYN-W5",
        audit_type_code="progress_vs_nursing",
    )
    parsed = result["parsed_output"]
    assert parsed["dimensions"]
    assert all(dim["status"] == "unknown" for dim in parsed["dimensions"])
    assert parsed.get("skip_reason") == "文书正文缺失"
    assert "一致" not in str(parsed.get("overall_conclusion") or "")
    assert parsed.get("inconsistency") is False


def test_text_without_marker_does_not_apply_missing_guard():
    result = _pass_result()
    _post_process_result(
        result,
        audit_type_code="progress_vs_nursing",
        source_text="病程记录正文完整，未见缺失标记。",
    )
    assert not result.get("skip_reason")
    assert "文书正文缺失" not in str(result.get("overall_conclusion") or "")
    assert all("文书正文缺失" not in str(dim.get("explanation") or "") for dim in result["dimensions"])
