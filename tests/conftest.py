import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# 043 R4：os.environ 快照/恢复守卫（autouse 兜底）。
# 背景（041 T9 实录）：被测代码/测试直写 os.environ 的泄漏只在全量跑时暴露（隔离跑单文件不触发）。
# monkeypatch 只覆盖它自己管理的键；本守卫在每个用例后把环境整体恢复到用例前快照，
# 拦住跨文件泄漏，同时不影响测试进程启动前的既有环境变量。
def _restore_env(snapshot: dict[str, str]) -> None:
    current = os.environ
    for key in list(current.keys()):
        if key not in snapshot:
            del current[key]
        elif current[key] != snapshot[key]:
            current[key] = snapshot[key]
    for key, value in snapshot.items():
        if key not in current:
            current[key] = value


@pytest.fixture(autouse=True)
def _os_environ_snapshot_guard():
    """043 R4 守卫：每个用例前快照 os.environ，用例后整体恢复（直写泄漏兜底）。"""
    snapshot = os.environ.copy()
    yield
    _restore_env(snapshot)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "env_guard: 043 R4 conftest os.environ 守卫相关用例（同文件内 A 直写→B 断言已恢复）"
    )
