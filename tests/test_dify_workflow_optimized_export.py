from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "docs" / "一致性核查_1_六类质控优化_谨慎版_20260716.yml"


def _workflow_graph():
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    graph = data["workflow"]["graph"]
    nodes = {str(node["id"]): node["data"] for node in graph["nodes"]}
    return graph, nodes


def test_main_route_has_fail_closed_default_path():
    graph, nodes = _workflow_graph()

    assert nodes["1782000000001"]["type"] == "code"
    assert "unsupported_mr_type" in nodes["1782000000001"]["code"]
    assert "dimensions" not in nodes["1782000000001"]["code"]
    assert any(
        str(edge["source"]) == "1777257269263"
        and edge.get("sourceHandle") == "false"
        and str(edge["target"]) == "1782000000001"
        for edge in graph["edges"]
    )
    assert {item["variable"] for item in nodes["1782000000002"]["outputs"]} == {
        "aa",
        "hcjg",
    }


def test_json_only_repair_conversion_is_deterministic():
    _, nodes = _workflow_graph()

    assert (
        nodes["17756942025590"]["model"]["completion_params"]["temperature"]
        == 0.0
    )


def test_jyjc_validator_checks_structure_without_clinical_severity_binding():
    _, nodes = _workflow_graph()
    code = nodes["17772577215180"]["code"]

    assert "lab_abnormal_followup" in code
    assert "high_risk_response_consistency" in code
    assert "patient_summary" in code
    assert "STATUS_TO_SEVERITY" not in code
    assert "STATUS_TO_ALERT" not in code
    assert "validateSummaryConsistency" not in code
    assert "severity=high" not in code


def test_every_end_supports_both_current_output_keys():
    _, nodes = _workflow_graph()

    ends = [node for node in nodes.values() if node.get("type") == "end"]
    assert len(ends) == 8
    for end in ends:
        outputs = end["outputs"]
        assert {item["variable"] for item in outputs} == {"aa", "hcjg"}
        assert outputs[0]["value_selector"] == outputs[1]["value_selector"]


def test_surgery_prompts_allow_two_sources_but_fail_closed_for_one_source():
    _, nodes = _workflow_graph()
    fact = nodes["1781275566701"]["prompt_template"][0]["text"]
    convert = nodes["1781275664826"]["prompt_template"][0]["text"]

    assert "少于两类存在" in fact
    assert "恰有两类来源存在时可以核查" in fact
    assert "第三类缺失本身不得判问题、不得 high" in fact
    assert "少于两类来源" in convert
    assert "恰有两类来源存在" in convert
    assert "第三类缺失本身不得映射为问题" in convert
