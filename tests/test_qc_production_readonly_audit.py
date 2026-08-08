"""003 P0：只读生产质控聚合脚本测试。"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from scripts.qc_production_readonly_audit import (
    SIX_AUDIT_TYPES,
    aggregate_push_logs,
    build_high_clinical_review_list,
    build_report,
    classify_parse_error,
    compare_to_documented_baseline,
    is_qc_usable,
    main,
    mask_identifier,
    probe_local_gates,
    reconcile_discharge_final,
    script_source_readonly_guards,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "qc_production_readonly_audit.py"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "qc_p0_20260714_synthetic.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_script_file_exists():
    assert SCRIPT_PATH.is_file()


def test_fixture_exists_and_has_six_types_shape():
    data = _load_fixture()
    assert data["query_date"] == "2026-07-14"
    assert set(data["configured_discharge_audit_types"]) == set(SIX_AUDIT_TYPES)
    assert "mr_text" not in json.dumps(data)
    assert "request_json" not in json.dumps(data)
    assert "response_json" not in json.dumps(data)


def test_qc_usable_frozen_rule():
    assert is_qc_usable("success", "success") is True
    assert is_qc_usable("success", "failed") is False
    assert is_qc_usable("success", "fallback") is False
    assert is_qc_usable("skipped", "success") is False
    assert is_qc_usable("failed", "failed") is False


def test_mask_identifier_is_stable_and_not_plaintext():
    token = mask_identifier("SYNTH0001")
    assert token.startswith("pid_")
    assert "SYNTH0001" not in token
    assert mask_identifier("SYNTH0001") == token


def test_classify_parse_error_categories():
    assert (
        classify_parse_error("parsed_json_missing_dimensions_and_conclusion")
        == "parsed_json_missing_dimensions_and_conclusion"
    )
    assert classify_parse_error("JSON decode error: Expecting value") == "json_syntax_error"
    assert classify_parse_error("") == "empty_parse_error"


def test_aggregate_push_logs_counts_and_modes():
    data = _load_fixture()
    agg = aggregate_push_logs(data["push_logs"], query_date="2026-07-14")
    assert agg["row_count"] == 12
    assert agg["status"]["success"] == 8
    assert agg["status"]["skipped"] == 4
    assert agg["parse_status"]["failed"] == 2
    assert agg["parse_status"]["fallback"] == 1
    assert agg["qc_usable"] == 5  # success+parse success only
    assert agg["transport_success"] == 8
    # daily + discharge both present
    modes = {b["audit_run_mode"] for b in agg["by_audit_type_and_mode"]}
    assert "daily_increment" in modes
    assert "discharge_final" in modes
    assert agg["parse_error_categories"]["parsed_json_missing_dimensions_and_conclusion"] == 1
    assert agg["parse_error_categories"]["json_syntax_error"] == 1


def test_reconcile_discharge_final_marks_jyjc_type_level_failure():
    data = _load_fixture()
    recon = reconcile_discharge_final(
        query_date="2026-07-14",
        configured_codes=data["configured_discharge_audit_types"],
        history_rows=data["scheduler_history"],
        push_logs=data["push_logs"],
        oracle_discharge_patient_count=None,
    )
    by_code = {t["audit_type_code"]: t for t in recon["types"]}
    jyjc = by_code["jyjc_vs_bcnursing"]
    assert jyjc["in_scheduler_config"] is True
    assert jyjc["scheduler_history_present"] is True
    assert "failed" in jyjc["scheduler_history_statuses"]
    assert jyjc["push_log_count"] == 0
    assert "type_level_failure_before_pushlog" in jyjc["interpretation_flags"]
    assert "jyjc_vs_bcnursing" in recon["summary"]["type_level_failures"]

    # 零候选且无 Oracle 交叉核对时不得解释为当天无患者
    # jyjc history total_records=0 also needs crosscheck flag path when not failed-before-push?
    # failed with 0 push already covered; admission has candidates
    admission = by_code["admission_vs_first_progress"]
    assert admission["push_log_count"] >= 1
    assert admission["uses_discharge_date_filter_expected"] is True


def test_zero_candidates_requires_oracle_crosscheck_flag():
    history = [
        {
            "audit_type_code": "surgery_chain",
            "query_date": "2026-07-14",
            "status": "completed",
            "total_records": 0,
            "success_count": 0,
            "failed_count": 0,
        }
    ]
    recon = reconcile_discharge_final(
        query_date="2026-07-14",
        configured_codes=["surgery_chain"],
        history_rows=history,
        push_logs=[],
        oracle_discharge_patient_count=None,
    )
    flags = recon["types"][0]["interpretation_flags"]
    assert "zero_candidates_needs_oracle_crosscheck" in flags
    assert "surgery_chain" in recon["summary"]["needs_oracle_crosscheck"]


def test_high_clinical_review_list_masks_patient_and_has_required_fields():
    data = _load_fixture()
    items = build_high_clinical_review_list(
        data["push_logs"], data["dimensions"], data["alerts"]
    )
    assert len(items) == 2
    for item in items:
        assert item["patient_token"].startswith("pid_")
        assert "SYNTH" not in item["patient_token"]
        assert "dimension_code" in item
        assert "medical_evidence_masked" in item
        assert "nursing_evidence_masked" in item
        assert "alert_filter_reason" in item
        assert item["alert_filter_reason"] == "dept_filtered"


def test_build_report_checksum_and_no_forbidden_body_fields():
    data = _load_fixture()
    report = build_report(data)
    assert report["checksum_sha256"]
    assert len(report["checksum_sha256"]) == 64
    dumped = json.dumps(report, ensure_ascii=False)
    for banned in ("mr_text", "request_json", "response_json", "payload_json"):
        assert f'"{banned}"' not in dumped
    assert "SYNTH0001" not in dumped
    cmp = compare_to_documented_baseline(report, data["expected_baseline"])
    assert cmp["compared"] is True
    assert cmp["match"] is True


def test_cli_fixture_mode_success(tmp_path, capsys):
    out_json = tmp_path / "report.json"
    out_csv = tmp_path / "summary.csv"
    rc = main(
        [
            "--fixture",
            str(FIXTURE_PATH),
            "--output-json",
            str(out_json),
            "--output-csv-summary",
            str(out_csv),
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert summary["query_date"] == "2026-07-14"
    assert summary["push_log_row_count"] == 12
    assert out_json.is_file()
    assert out_csv.is_file()
    report = json.loads(out_json.read_text(encoding="utf-8"))
    assert "discharge_final_reconciliation" in report
    assert report["gates"]["002_summary"]["code_status"] == "withdrawn_pending_reimplementation"


def test_cli_rejects_allow_db(capsys):
    rc = main(["--fixture", str(FIXTURE_PATH), "--allow-db"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "拒绝" in err or "allow-db" in err.lower() or "授权" in err


def test_script_source_readonly_static_guards():
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    violations = script_source_readonly_guards(source)
    assert violations == [], f"readonly violations: {violations}"

    # AST: no calls to commit/flush
    tree = ast.parse(source)
    banned_calls = {"commit", "flush"}
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = None
            if isinstance(func, ast.Attribute):
                name = func.attr
            elif isinstance(func, ast.Name):
                name = func.id
            if name in banned_calls:
                found.append(name)
    assert found == []


def test_script_source_has_no_network_imports():
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module.split(".")[0])
    forbidden = {"requests", "httpx", "paramiko", "urllib3", "aiohttp"}
    assert imported.isdisjoint(forbidden)


def test_probe_local_gates_returns_001_002_structure():
    gates = probe_local_gates()
    assert "001_summary" in gates
    assert "002_summary" in gates
    assert gates["002_summary"]["design_status"] == "confirmed"
    assert gates["001_jwt_production_gate"]["status"] in {
        "implemented_local",
        "incomplete_local",
        "probe_error",
    }


def test_documented_production_baseline_numbers_are_recorded_separately():
    """
    生产 1362 条等数字来自 003 文档；本 P0 无生产连接授权，
    只能固化为常量说明，不得伪装为已复跑生产。
    """
    documented = {
        "push_log_total": 1362,
        "status_success": 918,
        "status_skipped": 444,
        "status_failed": 0,
        "parse_success": 754,
        "parse_fallback": 2,
        "parse_failed": 162,
        "high_push_logs": 42,
        "high_dimensions": 50,
        "admission_parse_failed_share_note": "162/298 admission transport success",
        "jyjc_discharge_type_level_timeout": True,
        "alerts_all_dept_filtered": True,
    }
    assert documented["parse_failed"] == 162
    assert documented["jyjc_discharge_type_level_timeout"] is True
    # 合成 fixture 不得宣称等于生产全量
    data = _load_fixture()
    assert data["expected_baseline"]["push_log_total"] != documented["push_log_total"]
