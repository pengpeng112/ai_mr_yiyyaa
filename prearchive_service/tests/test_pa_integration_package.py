# -*- coding: utf-8 -*-
"""046 T7 联调包契约测试（prearchive_service/integration/jhemr/）。

- 包文件与 INDEX 一致（新增/删除文件必须同步登记）；
- openapi.json 结构有效且覆盖五外部接口 + redeem 载体；
- examples 纯 TEST（TEST 前缀患者、零 PHI 哨兵）；
- mock_client 签名与主服务实现逐字节一致（跨包对拍）；
- 签名向量可复算；
- summary schema 的 T7.1 字段全集与算术约束描述在位。
"""

import importlib.util
import json
import sys
from pathlib import Path

PACKAGE_DIR = (Path(__file__).resolve().parent.parent
               / "integration" / "jhemr")


def _load_mock_client():
    spec = importlib.util.spec_from_file_location(
        "jhemr_mock_client", PACKAGE_DIR / "mock_client.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _reference_signature(secret: str, client_id: str, method: str, path: str,
                         body: bytes, timestamp: str, nonce: str) -> str:
    """参考实现（隔离约束：预检包不得 import app.*；主服务侧
    tests/test_jhemr_integration.py 用同一公式锁定 app 实现——两侧对同一
    向量集互拍即证明逐字节一致）。"""
    import hashlib
    import hmac
    body_hash = hashlib.sha256(body or b"").hexdigest()
    message = "\n".join([client_id, method.upper(), path, body_hash,
                         timestamp, nonce])
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def test_index_covers_all_package_files():
    index = (PACKAGE_DIR / "INDEX.md").read_text(encoding="utf-8")
    for path in sorted(PACKAGE_DIR.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            assert path.name in index, f"包内文件未登记 INDEX：{path.name}"


def test_openapi_covers_five_external_interfaces():
    spec = json.loads((PACKAGE_DIR / "openapi.json").read_text(encoding="utf-8"))
    paths = set(spec["paths"])
    assert {
        "/api/integrations/jhemr/submission-checks",
        "/api/integrations/jhemr/submission-checks/{check_id}",
        "/api/integrations/jhemr/view-tickets",
        "/api/integrations/jhemr/view-tickets/{nonce}/redeem",
        "/api/integrations/jhemr/issues/{issue_id}/feedback",
        "/api/integrations/jhemr/rechecks",
    } <= paths
    # 提交检查=202；幂等复用=200
    create = spec["paths"]["/api/integrations/jhemr/submission-checks"]["post"]
    assert "202" in create["responses"] and "200" in create["responses"]
    # GET schema 引用 T7.1 完整模型
    get_view = spec["paths"]["/api/integrations/jhemr/submission-checks/"
                             "{check_id}"]["get"]
    assert "CheckView" in json.dumps(get_view)


def test_summary_schema_t71_fields_and_arithmetic():
    schema = json.loads((PACKAGE_DIR / "schemas" /
                         "submission-check-summary.schema.json")
                        .read_text(encoding="utf-8"))
    required = set(schema["required"])
    t71 = {"schema_version", "check_id", "run_id", "run_revision", "subject",
           "trigger_type", "checked_at", "data_snapshot_at",
           "ruleset_revision", "summary", "issues", "source_health",
           "submission_policy"}
    assert t71 <= required
    summary_props = schema["properties"]["summary"]["required"]
    for field in ("catalog_count", "mapped_catalog_count",
                  "rule_instance_count", "applicable_count", "evaluated_count",
                  "pass_count", "fail_count", "unknown_count", "pending_count",
                  "excluded_count", "exclusion_reasons", "issue_count",
                  "evaluation_coverage_pct", "required_source_checks",
                  "ready_source_checks", "data_coverage_pct", "status",
                  "provisional", "freshness"):
        assert field in summary_props, f"summary 缺 T7.1 字段 {field}"


def test_examples_are_test_only_no_phi():
    examples = json.loads((PACKAGE_DIR / "examples" / "test-samples.json")
                          .read_text(encoding="utf-8"))
    blob = json.dumps(examples, ensure_ascii=False)
    assert "TEST0002" in blob                      # 纯 TEST 合成患者
    assert examples["submission-checks/create-request.json"]["patient_id"] \
        .startswith("TEST")
    # queued 视图：计数 null + provisional（不用全 0 伪装）
    queued = examples["submission-checks/get-queued.json"]
    assert queued["summary"]["fail_count"] is None
    assert queued["summary"]["provisional"] is True
    assert queued["issues"] is None
    # completed 视图：算术守恒
    done = examples["submission-checks/get-completed.json"]
    summary = done["summary"]
    assert summary["applicable_count"] == (summary["pass_count"]
                                           + summary["fail_count"]
                                           + summary["unknown_count"]
                                           + summary["pending_count"])
    assert summary["rule_instance_count"] == (summary["applicable_count"]
                                              + summary["excluded_count"])
    assert summary["evaluated_count"] == (summary["pass_count"]
                                          + summary["fail_count"])


def test_mock_client_signature_matches_reference():
    """mock_client.build_signature 与参考实现逐字节一致
    （主服务侧 test_jhemr_integration.py 用同一公式+同一向量集锁定 app 实现）。"""
    mock = _load_mock_client()
    cases = [
        ("POST", "/api/integrations/jhemr/submission-checks",
         b'{"patient_id":"TEST0002"}', "1760000000", "nonce-0001"),
        ("GET", "/api/integrations/jhemr/submission-checks/abc123",
         b"", "1760000100", "nonce-0002"),
    ]
    for method, path, body, ts, nonce in cases:
        assert mock.build_signature("s", "c", method, path, body, ts, nonce) \
            == _reference_signature("s", "c", method, path, body, ts, nonce)


def test_signature_vectors_recomputable():
    vectors = json.loads((PACKAGE_DIR / "SIGNATURE_VECTORS.json")
                         .read_text(encoding="utf-8"))
    mock = _load_mock_client()
    import hashlib
    for vector in vectors["vectors"]:
        signature = mock.build_signature(
            vector["secret"], vector["client_id"], vector["method"],
            vector["path"], vector["body"].encode(), vector["timestamp"],
            vector["nonce"])
        assert signature == vector["signature"] == _reference_signature(
            vector["secret"], vector["client_id"], vector["method"],
            vector["path"], vector["body"].encode(), vector["timestamp"],
            vector["nonce"])
        assert vector["body_sha256"] == hashlib.sha256(
            vector["body"].encode()).hexdigest()


def test_readme_registers_capability_levels():
    readme = (PACKAGE_DIR / "README.md").read_text(encoding="utf-8")
    assert "L1 本地 Mock" in readme and "已验收" in readme
    assert "L2 真实测试 JHEMR" in readme and "L3 生产试点" in readme
    assert "未开始" in readme
