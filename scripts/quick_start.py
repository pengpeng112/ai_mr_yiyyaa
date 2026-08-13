"""兼容入口：创建安全的 12 科室脱敏合成 smoke 环境。

旧版脚本会直接写默认 SQLite，且使用已不存在的 ``PushLog.dept_id``。
现在统一委托给 ``scripts/demo_env.py``，避免误写现役数据目录。
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="兼容的 Med-Audit 本地快速测试入口")
    parser.add_argument("--run-id", default="quick-start-smoke")
    parser.add_argument("--profile", choices=["smoke", "showcase"], default="smoke")
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parent.parent
    state = workspace / "config" / "demo" / args.run_id / "runtime.json"
    if not state.exists():
        subprocess.check_call(
            [sys.executable, str(workspace / "scripts" / "demo_env.py"), "create", "--run-id", args.run_id, "--profile", args.profile],
            cwd=workspace,
        )
    print(f"隔离测试环境已就绪：{args.run_id}")
    print(f"启动：python scripts/demo_env.py serve --run-id {args.run_id}")
    print(f"销毁：python scripts/demo_env.py destroy --run-id {args.run_id} --force")


if __name__ == "__main__":
    main()
