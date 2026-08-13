from pathlib import Path


def test_rbac_bootstrap_contains_no_predictable_credentials():
    text = Path("scripts/init_rbac.py").read_text(encoding="utf-8")
    for secret in ("admin123", "manager123", "doctor123", "auditor123"):
        assert secret not in text
    assert "User(" not in text


def test_quick_start_delegates_to_isolated_demo_environment():
    text = Path("scripts/quick_start.py").read_text(encoding="utf-8")
    assert "scripts/demo_env.py" in text
    assert "config\" / \"demo\"" in text
