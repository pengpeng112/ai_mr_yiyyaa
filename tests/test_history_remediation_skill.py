from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from scripts.qc_production_readonly_audit import script_source_readonly_guards


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents/skills/med-audit-history-remediation/scripts/production_readonly_baseline.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("production_readonly_baseline", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _row(**overrides):
    values = {
        "dimension_code": "diagnosis_consistency",
        "dimension": "诊断一致性",
        "status": "fail",
        "severity": "high",
        "alert_level": "red",
        "confidence": 0.9,
        "medical_evidence_json": "[]",
        "nursing_evidence_json": "[]",
        "medical_content": "",
        "nursing_content": "",
        "extra_json": "{}",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_script_runs_directly_without_pythonpath():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_dim_restore_falls_back_to_issue_evidence():
    module = _load_module()
    row = _row(extra_json='{"issues":[{"evidence_a":"入院证据","evidence_b":"病程证据"}]}')
    dim = module._dim_dict_from_orm(row)
    assert dim["medical_evidence"] == ["入院证据"]
    assert dim["nursing_evidence"] == ["病程证据"]


def test_dim_restore_falls_back_to_mapper_legacy_extra():
    module = _load_module()
    row = _row(
        extra_json='{"medical_evidence_legacy":["A"],"nursing_evidence_legacy":["B"]}'
    )
    dim = module._dim_dict_from_orm(row)
    assert dim["medical_evidence"] == ["A"]
    assert dim["nursing_evidence"] == ["B"]


def test_content_precedes_extra_fallback():
    module = _load_module()
    row = _row(
        medical_content="内容A",
        nursing_content="内容B",
        extra_json='{"issues":[{"evidence_a":"issueA","evidence_b":"issueB"}]}',
    )
    dim = module._dim_dict_from_orm(row)
    assert dim["medical_evidence"] == ["内容A"]
    assert dim["nursing_evidence"] == ["内容B"]


def test_apply_is_always_rejected():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--apply"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "禁止 --apply" in result.stderr


def test_script_passes_readonly_static_guard():
    assert script_source_readonly_guards(SCRIPT.read_text(encoding="utf-8")) == []
