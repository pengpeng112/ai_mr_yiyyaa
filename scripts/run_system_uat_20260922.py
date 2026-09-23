# -*- coding: utf-8 -*-
"""054 §13 U6 编排：uat054 全系统模拟人 UAT 一次性入口（只编排，不替代门禁）。

- 默认合成隔离：要求 demo 主服务 127.0.0.1:18080 在听，并核对 demo config 的
  dify/relay 目标均为回环；出现生产网段即中止该测试。
- 显式开启各 spec 环境门（UAT054_E2E/WORKBENCH_E2E/SYNTHETIC_DEMO_E2E/ONESHOT_E2E/LEGACY_E2E），
  串行（--workers=1）执行：共享 demo 库的并行=假失败（054 §9.1）。
- sidecar 自管：未占用则拉起（--serve --import-rules）；正向轮后停掉跑降级轮；
  外部已在听的 sidecar 不擅杀（复用跑正向，降级轮标 SKIPPED 汇总上报）。
- 检查实际执行数量（解析 playwright 汇总），低于该套件下限=缺失上报；
  任何失败 exit 非零；finally 停自有进程。
- 可选 --with-gates：最后调用正式门禁入口 run_gates_20260906 --full --anchor-file
  （默认关：U6 单独跑门禁，本脚本不替代）。

用法（仓库根）::

    python scripts/run_system_uat_20260922.py                    # 默认 run-id=uat054
    python scripts/run_system_uat_20260922.py --run-id uat054
    python scripts/run_system_uat_20260922.py --with-gates       # 附带全量门禁
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def _resolve_tool(name: str) -> str:
    """与 run_gates 同法解析 npm/npx（Windows 下为 .cmd）"""
    which = shutil.which(name)
    return which if which else name


NPX = _resolve_tool("npx")

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
OUT_DIR = ROOT / "review" / "uat054-20260922" / "orchestrator"
MAIN_PORT = 18080
SIDECAR_PORT = 18600

# (套件名, spec 选择器, 环境变量, 项目, 最低执行数, 是否 legacy 配置)
SUITES: list[tuple[str, str, dict[str, str], list[str], int, bool]] = [
    ("uat054-perm-session", "uat054-perm-session",
     {"UAT054_E2E": "true"}, ["desktop-1366"], 5, False),
    # synthetic 必须在 journeys 之前：旅程② 会推送同批 fixture 记录，
    # 使其进入 unreviewed_pending，后跑 synthetic 的 push 会被跳过（skip 语义正确但互踩）
    ("synthetic-demo-real", "synthetic-demo-real",
     {"SYNTHETIC_DEMO_E2E": "true"}, ["desktop-1366"], 2, False),
    ("uat054-journeys", "uat054-journeys",
     {"UAT054_E2E": "true"}, ["desktop-1366"], 3, False),
    ("workbench-real", "workbench-real",
     {"WORKBENCH_E2E": "true"}, ["desktop-1366", "mobile-390"], 3, False),
    ("oneshot-uinext-sweep", "oneshot-uinext-sweep",
     {"ONESHOT_E2E": "true"}, ["desktop-1366"], 1, False),
    ("legacy-workbench-正向", "workbench",
     {"LEGACY_E2E": "true"}, ["legacy-desktop-1366"], 1, True),
    ("legacy-workbench-降级", "workbench",
     {"LEGACY_E2E": "true", "RULE_CENTER_SIDECAR": "0"}, ["legacy-desktop-1366"], 1, True),
]

PROD_NET = re.compile(r"//10\.\d+\.\d+\.\d+")


def log(msg: str) -> None:
    print(f"[uat054] {msg}", flush=True)


def is_listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_port(port: int, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_listening(port):
            return True
        time.sleep(1.0)
    return False


def check_demo_isolation(run_id: str) -> tuple[bool, str]:
    cfg_path = ROOT / "config" / "demo" / run_id / "config.json"
    if not cfg_path.exists():
        return False, f"demo 配置缺失: {cfg_path}"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    # demo 配置的 dify/relay 目标必须是回环（合成隔离红线）
    for section in ("dify", "relay_alert"):
        blob = json.dumps(cfg.get(section, {}), ensure_ascii=False)
        hits = PROD_NET.findall(blob)
        if hits:
            return False, f"demo config {section} 出现生产网段: {hits}"
    return True, "ok"


def run_npx(selector: str, env_extra: dict[str, str], projects: list[str],
            legacy: bool) -> tuple[int, dict[str, int], str]:
    """返回 (returncode, 计数, 原始输出)。计数来自 playwright 汇总行。"""
    cmd = [NPX, "playwright", "test", selector]
    for p in projects:
        cmd += ["--project", p]
    cmd += ["--workers", "1"]
    if legacy:
        cmd += ["-c", "playwright.legacy.config.ts"]
    env = {**os.environ, **env_extra,
           "PLAYWRIGHT_SKIP_WEBSERVER": "1",
           "PLAYWRIGHT_BASE_URL": f"http://127.0.0.1:{MAIN_PORT}/ui-next/"}
    proc = subprocess.run(cmd, cwd=str(FRONTEND), env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=1800)
    out = (proc.stdout or "") + (proc.stderr or "")
    counts = {"passed": 0, "failed": 0, "skipped": 0, "did_not_run": 0}
    for key in counts:
        m = re.search(rf"(\d+)\s+{key.replace('_', ' ')}", out)
        if m:
            counts[key] = int(m.group(1))
    executed = counts["passed"] + counts["failed"] + counts["skipped"]
    counts["executed"] = executed
    return proc.returncode, counts, out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="054 uat054 全系统 UAT 编排")
    parser.add_argument("--run-id", default="uat054", help="demo 环境 run-id")
    parser.add_argument("--with-gates", action="store_true",
                        help="最后调用正式门禁入口 run_gates --full --anchor-file")
    args = parser.parse_args(argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    overall_ok = True
    sidecar_proc: subprocess.Popen | None = None
    sidecar_self_managed = False

    try:
        # ---- 预检：demo 主服务 + 隔离核验 ----
        if not is_listening(MAIN_PORT):
            log(f"FAIL: demo 主服务 127.0.0.1:{MAIN_PORT} 未在听。"
                f"请先: python scripts/demo_env.py serve --run-id {args.run_id}")
            return 2
        ok, why = check_demo_isolation(args.run_id)
        if not ok:
            log(f"FAIL: 隔离核验不通过（{why}）——生产网段出现在测试配置，按 §9.1 中止")
            return 2
        log(f"预检通过：demo 主服务 {MAIN_PORT} 在听，config 隔离核验 {why}")

        # ---- 造数（幂等） ----
        seed = subprocess.run([sys.executable, "scripts/seed_workbench_demo_20260915.py"],
                              cwd=str(ROOT), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=300)
        if seed.returncode != 0:
            log(f"WARN: seed_workbench_demo 退出码 {seed.returncode}（继续，若用例缺数据将如实失败）")

        # ---- sidecar：自管优先 ----
        if is_listening(SIDECAR_PORT):
            log(f"sidecar {SIDECAR_PORT} 已被外部进程占用：正向轮复用，降级轮将标 SKIPPED（不擅杀）")
        else:
            log("拉起自管 sidecar（--serve --import-rules）…")
            sidecar_proc = subprocess.Popen(
                [sys.executable, "scripts/run_prearchive_demo_sidecar_20260904.py",
                 "--serve", "--import-rules"],
                cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            sidecar_self_managed = True
            if not wait_port(SIDECAR_PORT, 90):
                log("FAIL: 自管 sidecar 90s 未就绪")
                return 2

        # ---- 逐套件串行执行 ----
        for name, selector, env_extra, projects, minimum, legacy in SUITES:
            if "降级" in name and not sidecar_self_managed:
                results.append({"suite": name, "status": "SKIPPED",
                                "reason": "外部 sidecar 占用，不擅杀（§端口治理）",
                                "counts": {}})
                log(f"[{name}] SKIPPED（外部 sidecar 占用）")
                continue
            if "降级" in name and sidecar_self_managed:
                sidecar_proc.terminate() if sidecar_proc else None
                try:
                    sidecar_proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    sidecar_proc.kill()
                sidecar_proc = None
                sidecar_self_managed = False
                # 等端口释放
                deadline = time.time() + 30
                while is_listening(SIDECAR_PORT) and time.time() < deadline:
                    time.sleep(1.0)
                log("自管 sidecar 已停，进入降级轮")
            rc, counts, out = run_npx(selector, env_extra, projects, legacy)
            log(f"[{name}] rc={rc} counts={counts}")
            (OUT_DIR / f"{name}.log").write_text(out, encoding="utf-8")
            suite_ok = rc == 0 and counts["failed"] == 0 and counts["executed"] >= minimum
            results.append({"suite": name, "status": "PASS" if suite_ok else "FAIL",
                            "rc": rc, "counts": counts, "minimum": minimum})
            if not suite_ok:
                overall_ok = False

        # ---- 可选：正式门禁入口 ----
        if args.with_gates:
            log("调用正式门禁入口 run_gates --full --anchor-file …")
            g = subprocess.run([sys.executable, "scripts/run_gates_20260906.py", "--full",
                                "--anchor-file", "docs/reference/gate_anchors.json"],
                               cwd=str(ROOT), timeout=3600)
            results.append({"suite": "run_gates_full", "status": "PASS" if g.returncode == 0 else "FAIL",
                            "rc": g.returncode, "counts": {}, "minimum": 0})
            if g.returncode != 0:
                overall_ok = False
    finally:
        if sidecar_proc is not None:
            sidecar_proc.terminate()
            try:
                sidecar_proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                sidecar_proc.kill()
            log("finally：自管 sidecar 已停")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    payload = {"run_id": args.run_id, "stamp": stamp, "overall": "PASS" if overall_ok else "FAIL",
               "results": results}
    (OUT_DIR / f"summary_{stamp}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [f"# uat054 编排汇总（{stamp}）", "",
             f"整体：{'PASS' if overall_ok else 'FAIL'}", "",
             "| 套件 | 状态 | 执行 | 失败 | 下限 |", "| --- | --- | --- | --- | --- |"]
    for r in results:
        c = r.get("counts", {}) or {}
        lines.append(f"| {r['suite']} | {r['status']} | {c.get('executed', '-')} | "
                     f"{c.get('failed', '-')} | {r.get('minimum', '-')} |")
    (OUT_DIR / f"summary_{stamp}.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
