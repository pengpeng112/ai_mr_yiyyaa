"""R4 守卫用例：模拟 041 T9 类跨用例 env 直写泄漏，验证 conftest autouse 快照守卫生效。

两个用例按文件顺序执行：A 直写（不经 monkeypatch）→ B 断言已恢复。
若 tests/conftest.py 的 `_os_environ_snapshot_guard` 缺失或失效，B 必红（全量跑才暴露的泄漏在本地即可见）。
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.env_guard

PROBE_KEY = "MED_AUDIT_ENV_GUARD_PROBE_20260907"


def test_guard_a_direct_write_without_monkeypatch():
    os.environ[PROBE_KEY] = "leaked-by-design"
    assert os.environ[PROBE_KEY] == "leaked-by-design"


def test_guard_b_environment_restored_after_previous_case():
    assert PROBE_KEY not in os.environ, (
        "上一个用例直写的 env 键泄漏到本用例：tests/conftest.py 的 autouse 快照守卫未生效"
    )
