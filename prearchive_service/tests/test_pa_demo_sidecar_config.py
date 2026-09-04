# -*- coding: utf-8 -*-
"""041 T1 demo sidecar 配置/脚本契约测试。

覆盖：config.demo.json 解析通过、无真实内网 IP、三开关（push/delivery/insurance）
全 false、端口 18600、假 admin token、真实源全关、--check 探测头 HMAC 向量
与 prearchive.admin_api.actor_signature 一致。
"""
import importlib.util
import json
import re
from pathlib import Path

from prearchive.admin_api import actor_signature
from prearchive.config import load_config

PREARCHIVE_ROOT = Path(__file__).resolve().parents[1]
DEMO_CONFIG_PATH = PREARCHIVE_ROOT / "config.demo.json"
SCRIPT_PATH = PREARCHIVE_ROOT.parent / "scripts" / "run_prearchive_demo_sidecar_20260904.py"

REAL_IP_PATTERN = re.compile(r"(10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)")


def _load_script():
    """按文件路径加载 scripts/run_prearchive_demo_sidecar_20260904.py（零 import app.*）。"""
    spec = importlib.util.spec_from_file_location("run_prearchive_demo_sidecar_20260904", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_demo_config_parses_and_uses_port_18600():
    config = load_config(str(DEMO_CONFIG_PATH))
    assert int(config["api"]["port"]) == 18600
    assert str(config["api"]["host"]) == "127.0.0.1"


def test_demo_config_has_no_real_internal_ips():
    raw = DEMO_CONFIG_PATH.read_text(encoding="utf-8")
    # 注释键（_comment/_registry_note）之外的正文不得出现真实内网 IP
    config = json.loads(raw)
    searchable = json.dumps(
        {k: v for k, v in config.items() if not k.startswith("_")},
        ensure_ascii=False)
    match = REAL_IP_PATTERN.search(searchable)
    assert not match, f"demo 配置出现真实内网 IP: {match.group(0) if match else ''}"


def test_demo_config_switches_all_off():
    config = load_config(str(DEMO_CONFIG_PATH))
    assert config["push"]["enabled"] is False
    assert config["result_delivery"]["enabled"] is False
    assert config["insurance_qc"]["enabled"] is False
    assert config["rule_registry"]["mode"] in ("file", "compare", "registry")


def test_demo_config_admin_token_is_explicit_fake():
    config = load_config(str(DEMO_CONFIG_PATH))
    assert config["admin_api"]["enabled"] is True
    assert config["admin_api"]["admin_token"] == "demo-admin-token"
    assert config["admin_api"]["signing_secret"] == "demo-admin-signing-secret"


def test_demo_config_all_real_sources_disabled_and_loopback():
    config = load_config(str(DEMO_CONFIG_PATH))
    for name, source in config["sources"].items():
        assert source.get("enabled") is False, name
        assert str(source.get("host", "")).startswith("<") or \
            str(source.get("host")) in ("127.0.0.1", "localhost"), name


def test_demo_config_result_store_is_demo_sqlite():
    config = load_config(str(DEMO_CONFIG_PATH))
    assert config["result_store"]["type"] == "sqlite"
    assert "demo" in str(config["result_store"]["sqlite_path"])


def test_probe_headers_hmac_matches_admin_api_vector():
    """--check 的签名组装必须与 sidecar 验签口径逐字节一致（含 percent-encode）。"""
    module = _load_script()
    headers = module.build_probe_headers(
        "demo-admin-token", "demo-admin-signing-secret",
        actor_id="demo-probe", actor_name="探测员",
        permissions=("prearchive_rule_view", "prearchive_rule_edit"),
        request_id="req-test-1")
    assert headers["X-Admin-Token"] == "demo-admin-token"
    assert headers["X-Actor-Permissions"] == "prearchive_rule_edit,prearchive_rule_view"
    expected = actor_signature(
        "demo-admin-signing-secret", "demo-probe",
        headers["X-Actor-Name"],       # 服务端按线上原始（encoded）值验签
        headers["X-Actor-Permissions"], "req-test-1")
    assert headers["X-Actor-Signature"] == expected
