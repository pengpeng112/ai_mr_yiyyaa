"""docker-compose.demo.yml 的单容器入口。"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def main() -> None:
    workspace = Path(__file__).resolve().parent.parent
    run_id = os.getenv("DEMO_RUN_ID", "demo-showcase")
    profile = os.getenv("DEMO_PROFILE", "showcase")
    app_port = os.getenv("DEMO_APP_PORT", "18080")
    dify_port = os.getenv("DEMO_DIFY_PORT", "18081")
    relay_port = os.getenv("DEMO_RELAY_PORT", "18082")
    state_path = workspace / "config" / "demo" / run_id / "runtime.json"
    if not state_path.exists():
        subprocess.check_call(
            [
                sys.executable,
                str(workspace / "scripts" / "demo_env.py"),
                "create",
                "--run-id", run_id,
                "--profile", profile,
                "--app-port", app_port,
                "--dify-port", dify_port,
                "--relay-port", relay_port,
            ],
            cwd=workspace,
        )
    os.execv(
        sys.executable,
        [sys.executable, str(workspace / "scripts" / "demo_env.py"), "serve", "--run-id", run_id],
    )


if __name__ == "__main__":
    main()
