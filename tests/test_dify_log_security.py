import json

from app.services.dify_log_utils import _summarize_dify_payload, _summarize_dify_outputs


def test_dify_summaries_never_include_raw_content():
    secret_text = "患者张三 诊断内容"
    payload = {"inputs": {"mr_txt": secret_text, "mr_type": "admission"}, "user": "patient-123"}
    summary = _summarize_dify_payload(payload, "mr_txt")
    output_summary = _summarize_dify_outputs({"aa": secret_text})
    encoded = json.dumps({"payload": summary, "outputs": output_summary}, ensure_ascii=False)
    assert secret_text not in encoded
    assert "main_input_preview" not in summary
    assert "output_preview" not in output_summary
    assert summary["main_input_sha256"]

