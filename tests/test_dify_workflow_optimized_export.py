import json
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "docs" / "3一致性核查正式版-质控门禁影子V2.yml"


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


def test_all_output_branches_use_only_down_high_gates():
    _, nodes = _workflow_graph()

    generic_gate_ids = {
        "1783000000101",
        "1783000000102",
        "1783000000103",
        "1783000000104",
        "1783000000106",
        "1783000000107",
    }
    for node_id in generic_gate_ids:
        code = nodes[node_id]["code"]
        assert "formal_high_gate_v2" in code
        assert "只降不升" in code
        assert "no_qualified_high_issue" in code
        assert "input_combo_not_fail_high_red_no_upgrade" in code

    admission_gate = nodes["1783000000105"]["code"]
    assert "admission_fact_gate_v2" in admission_gate
    assert "required_source_status_missing_or_invalid" in admission_gate
    assert "cdb_shadow_requires_clinical_confirmation" in admission_gate
    assert "input_combo_not_fail_high_red_no_upgrade" in admission_gate


def test_admission_prompt_requires_fact_evidence_closure_and_cdb_confirmation():
    _, nodes = _workflow_graph()

    fact = nodes["1781274793096"]["prompt_template"][0]["text"]
    convert = nodes["17813464293260"]["prompt_template"][0]["text"]
    gate = nodes["1783000000105"]["code"]

    for field in (
        "fact_key",
        "value_a",
        "value_b",
        "time_comparable",
        "relation",
        "event_key",
        "clinical_confirmation_required",
    ):
        assert field in fact
        assert field in convert

    assert 'critical_diagnosis_basis：本影子阶段一律 level="general"' in fact
    assert "sourceStatus.admission_record_present !== true" in gate
    assert "canonicalEventKey" in gate
    assert "canonicalSafetyCategory" in gate
    assert "hasOppositeSides" in gate
    assert "promoteDirectWrongSideCandidate" in gate
    assert "deterministic_wrong_site_candidate" in gate
    assert "direct_wrong_site_candidate_v1" in gate
    assert "safety_category_original" in gate
    assert "禁止误标为 critical_diagnosis_basis" in fact
    assert "severe+high_eligible contradiction→fail/high/red 候选" in convert
    assert "不得把 severe 候选提前降成 medium" in convert
    assert "supplied" not in gate


def _run_admission_gate(payload):
    if shutil.which("node") is None:
        pytest.skip("node is required to execute the Dify code node")
    _, nodes = _workflow_graph()
    code = nodes["1783000000105"]["code"]
    invocation = (
        "\nconst output = main({llmjson: JSON.stringify("
        + json.dumps(payload, ensure_ascii=False)
        + "), patient_id: '', patient_name: '', visit_number: ''});"
        + "\nconsole.log(output.result);"
    )
    completed = subprocess.run(
        ["node", "-e", code + invocation],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(completed.stdout)


def _admission_payload(issue):
    return {
        "source_status": {
            "admission_record_present": True,
            "first_progress_record_present": True,
            "missing_sources": [],
        },
        "dimensions": [{
            "dimension_code": "physical_examination",
            "status": "warn",
            "severity": "medium",
            "alert_level": "yellow",
            "confidence": 0.98,
            "extra": {"issues": [issue], "manual_review": []},
        }],
    }


def test_admission_gate_promotes_only_closed_direct_wrong_side_candidate():
    issue = {
        "primary_dimension_code": "physical_examination",
        "dimension_code": "physical_examination",
        "issue_mode": "contradiction",
        "relation": "contradiction",
        "fact_key": "exam.eardrum.side",
        "value_a": "左侧",
        "value_b": "右侧",
        "time_comparable": True,
        "level": "general",
        "high_eligible": False,
        "safety_category": "wrong_site_or_side",
        "direct_patient_safety_impact": False,
        "source_a": "admission_record",
        "evidence_a": "查体见左侧鼓膜穿孔",
        "source_b": "first_progress_record",
        "evidence_b": "查体见右侧鼓膜穿孔",
        "confidence": 0.98,
    }
    result = _run_admission_gate(_admission_payload(issue))
    dim = next(d for d in result["dimensions"] if d["dimension_code"] == "physical_examination")
    promoted = dim["extra"]["issues"][0]

    assert (dim["status"], dim["severity"], dim["alert_level"]) == ("fail", "high", "red")
    assert promoted["level"] == "severe"
    assert promoted["high_eligible"] is True
    assert promoted["deterministic_wrong_site_candidate"]["rule_version"] == "direct_wrong_site_candidate_v1"
    assert dim["extra"]["high_gate"][0]["passed"] is True


def test_admission_gate_does_not_promote_cdb_or_omission():
    issue = {
        "primary_dimension_code": "physical_examination",
        "dimension_code": "physical_examination",
        "issue_mode": "omission",
        "relation": "omission",
        "fact_key": "diagnosis.primary",
        "value_a": "诊断甲",
        "value_b": "",
        "time_comparable": False,
        "level": "general",
        "high_eligible": False,
        "safety_category": "critical_diagnosis_basis",
        "source_a": "admission_record",
        "evidence_a": "初步诊断为诊断甲",
        "source_b": "first_progress_record",
        "evidence_b": "未提及",
        "confidence": 0.98,
    }
    result = _run_admission_gate(_admission_payload(issue))
    dim = next(d for d in result["dimensions"] if d["dimension_code"] == "physical_examination")

    assert dim["severity"] == "medium"
    assert dim["alert_level"] == "yellow"
    assert "deterministic_wrong_site_candidate" not in dim["extra"]["issues"][0]
