"""043 R2 门禁聚合唯一入口：--quick 冒烟 / --full 全量（043 §3.3 裁定）。

行为要点：
- --quick = compileall(app tests scripts prearchive_service) + naming + isolation + sidecar --check；
- --full  = quick 全部 + 主 pytest + prearchive pytest + typecheck + unit + build + e2e
            + 可选 legacy 规则中心 E2E（只探测 18080 主服务在听才跑；sidecar 由本脚本自管：
              18600 未在听则拉起，正向轮通过后杀树跑降级轮；外部 sidecar 占用 18600 时
              只跑正向并记 SKIPPED(external-sidecar)，不终止外部进程）；
- 锚比较：显式传 --anchor-file 且文件存在才比锚退出（低于锚=非零）；未传/文件不存在只出表；
- 摘要解析二进制安全（bytes + errors=replace）；每项完整输出落 review/gate-runs/<时间戳>/；
- e2e 前探测 4173：空闲则用 4173；被占用时先核验服务身份（对照 frontend/dist 构建资产指纹），
  同构建则复用；旧构建/外来服务则自动改用空闲备选端口并注入 PLAYWRIGHT_BASE_URL
  （046 ST-002：4173 历史占用进程只报不杀）；--strict-ports 时任何占用直接 fail。

最终结论以脚本打印的 Markdown 门禁表为准。
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

ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "review" / "gate-runs"
DEFAULT_ANCHOR_FILE = ROOT / "docs" / "reference" / "gate_anchors.json"

DEMO_MAIN_PORT = 18080
SIDECAR_PORT = 18600
PREVIEW_PORT = 4173
# 046 ST-002：4173 被外来服务/旧构建占用且不能复用时，依次尝试的备选预览端口段
PREVIEW_FALLBACK_PORTS = tuple(range(4273, 4283))

# 门禁子进程统一注入的本地回环 no_proxy：Windows 系统代理（注册表 ProxyServer）会被
# urllib 的 getproxies_registry() 拾取，而其 ProxyOverride 通配（127.*）不被 Python 的
# bypass 匹配支持 → 127.0.0.1 上的本地 mock receiver 请求被代理劫持回 502（044 卡点 F 实录）。
# proxy_bypass_environment() 优先于注册表，注入 NO_PROXY 即可让本地回环直连。
LOCAL_NO_PROXY = "127.0.0.1,localhost"


def child_env_with_local_no_proxy(extra: dict | None = None) -> dict[str, str]:
    """构造子进程环境：继承当前环境 + 强制本地回环 no_proxy（保留用户已有 no_proxy 条目）。"""
    env = os.environ.copy()
    for key in ("NO_PROXY", "no_proxy"):
        existing = env.get(key, "")
        items = [i.strip() for i in existing.split(",") if i.strip()]
        for item in LOCAL_NO_PROXY.split(","):
            if item not in items:
                items.append(item)
        env[key] = ",".join(items)
    if extra:
        env.update({k: str(v) for k, v in extra.items()})
    return env


# ---------------------------------------------------------------- 工具函数（单测覆盖）


def decode_stream(data: bytes | None) -> str:
    """二进制安全解码：后台任务/管道输出可能混 UTF-8 与本地编码。"""
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    return data.decode("utf-8", errors="replace")


PASSED_RE = re.compile(r"(\d+)\s+passed")
FAILED_RE = re.compile(r"(\d+)\s+failed")
SKIPPED_RE = re.compile(r"(\d+)\s+skipped")
ERROR_RE = re.compile(r"(\d+)\s+error")


def parse_counts(text: str) -> dict[str, int]:
    """从 pytest/vitest/playwright 输出解析 passed/failed/skipped/error 计数（取全文最大值，兼容多行摘要）。"""

    def _max(pattern: re.Pattern[str]) -> int:
        return max((int(m.group(1)) for m in pattern.finditer(text)), default=0)

    return {"passed": _max(PASSED_RE), "failed": _max(FAILED_RE), "skipped": _max(SKIPPED_RE), "error": _max(ERROR_RE)}


def is_port_listening(host: str, port: int, timeout: float = 1.0) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def should_run_legacy_demo_e2e(main_port: int = DEMO_MAIN_PORT, sidecar_port: int = SIDECAR_PORT) -> tuple[bool, str]:
    """legacy 规则中心 E2E 需要 demo 主服务与 sidecar 双进程在听（可注入端口便于单测）。"""
    main_ok = is_port_listening("127.0.0.1", main_port)
    sidecar_ok = is_port_listening("127.0.0.1", sidecar_port)
    if main_ok and sidecar_ok:
        return True, ""
    missing = []
    if not main_ok:
        missing.append(str(main_port))
    if not sidecar_ok:
        missing.append(str(sidecar_port))
    return False, f"no-demo(端口未听: {','.join(missing)})"


# ---------------------------------------------------------------- ST-002 预览端口身份核验


def fetch_preview_html(url: str, timeout: float = 3.0) -> str:
    """拉取预览服务页面 HTML（任何失败返回空串；只读探测，不杀任何进程）。"""
    import urllib.request

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "run-gates-probe"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(65536).decode("utf-8", errors="replace")
    except Exception:
        return ""


def expected_build_markers(dist_index: Path) -> set:
    """从 frontend/dist/index.html 提取构建身份指纹（assets/*.js|css 文件名集合）。"""
    if not dist_index.exists():
        return set()
    html = dist_index.read_text(encoding="utf-8", errors="replace")
    return set(re.findall(r"(?:src|href)=\"([^\"]+assets/[^\"]+\.(?:js|css))\"", html))


def preview_identity_matches(served_html: str, markers: set) -> bool:
    """服务端页面必须引用当前 dist 的全部资源指纹才算同构建（旧构建/外来服务都不匹配）。"""
    if not served_html or not markers:
        return False
    return all(marker in served_html for marker in markers)


def resolve_preview_port(*, default_port: int = PREVIEW_PORT,
                         is_busy=None, fetch=None, markers=None,
                         fallback_ports=PREVIEW_FALLBACK_PORTS,
                         is_free=None) -> tuple:
    """决定 e2e 用的预览端口。返回 (port, note, base_url_env)。

    - 4173 空闲 → (4173, "", None)；
    - 4173 被占用且身份=当前构建 → 复用 (4173, "reuse:identity-verified", None)；
    - 4173 被占用且身份不符/不可探测 → 第一个空闲备选端口 + PLAYWRIGHT_BASE_URL 注入；
      备选全部被占 → (None, "no-free-preview-port", None) 由调用方按 FAIL 处理。
    is_busy/fetch/markers/is_free 可注入便于单测。
    """
    busy = is_busy or (lambda p: is_port_listening("127.0.0.1", p))
    free = is_free or (lambda p: not busy(p))
    if not busy(default_port):
        return default_port, "", None
    _fetch = fetch or (lambda: fetch_preview_html(f"http://127.0.0.1:{default_port}/ui-next/"))
    served = _fetch()
    _markers = markers if markers is not None else expected_build_markers(
        ROOT / "frontend" / "dist" / "index.html")
    if preview_identity_matches(served, _markers):
        return default_port, "reuse:identity-verified(current build)", None
    for port in fallback_ports or ():
        if free(port):
            return port, (f"fallback:{default_port} 被旧构建/外来服务占用"
                          f"(服务身份不符，只报不杀)，改用空闲端口 {port}"), \
                   f"http://127.0.0.1:{port}/ui-next/"
    return None, f"no-free-preview-port(候选 {list(fallback_ports or [])} 全被占用)", None


def load_anchor_file(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("anchors"), dict):
        raise ValueError("anchor 文件缺 anchors 节")
    return data["anchors"]


def compare_with_anchors(results: dict[str, dict], anchors: dict) -> list[str]:
    """比锚：只比本轮实际跑过的门（quick 不含 pytest 时不比 pytest）。

    口径：passed 不得低于锚；skipped 只登记不比较；门禁 FAIL 本身已由退出码处理。
    """
    problems: list[str] = []
    mapping = {
        "main_pytest": "主 pytest",
        "prearchive_pytest": "prearchive pytest",
        "frontend_unit": "前端 unit",
        "frontend_e2e": "前端 e2e",
    }
    for key, label in mapping.items():
        anchor = anchors.get(key)
        actual = results.get(key)
        if not anchor or not actual or actual.get("status") != "PASS":
            continue
        anchor_passed = int(anchor.get("passed", 0))
        actual_passed = int(actual.get("counts", {}).get("passed", 0))
        if actual_passed < anchor_passed:
            problems.append(f"{label}: passed {actual_passed} 低于锚 {anchor_passed}")
    if anchors.get("sidecar_check", {}).get("status") == "PASS" and results.get("sidecar_check", {}).get("status") not in ("PASS",):
        gate = results.get("sidecar_check", {})
        if gate.get("status") == "FAIL":
            problems.append("sidecar --check: FAIL（锚=PASS）")
    return problems


# ---------------------------------------------------------------- 门禁执行


def _resolve_tool(name: str) -> str:
    which = shutil.which(name)
    if which:
        return which
    return name  # 交给系统报错，便于诊断


class GateResult:
    def __init__(self, name: str, command: str, status: str, counts: dict[str, int] | None = None,
                 note: str = "", duration: float = 0.0):
        self.name = name
        self.command = command
        self.status = status  # PASS / FAIL / SKIPPED
        self.counts = counts or {}
        self.note = note
        self.duration = duration

    def to_dict(self) -> dict:
        return {
            "name": self.name, "command": self.command, "status": self.status,
            "counts": self.counts, "note": self.note, "duration_sec": round(self.duration, 1),
        }


def run_command(name: str, cmd: list[str], cwd: Path, run_dir: Path, env: dict | None = None,
                parse_counts_flag: bool = False, timeout: int = 3600) -> GateResult:
    """执行单个门禁：完整输出落 run_dir/<name>.log；退出码即 PASS/FAIL。"""
    started = time.monotonic()
    merged = child_env_with_local_no_proxy(env)
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, timeout=timeout,
            env=merged, shell=False,
        )
        out, err, code = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        out, err = (exc.stdout or b""), (exc.stderr or b"")
        code = -1
    except FileNotFoundError as exc:
        (run_dir / f"{name}.log").write_text(f"命令不存在: {exc}\n", encoding="utf-8")
        return GateResult(name, " ".join(cmd), "FAIL", note=f"命令不存在: {exc}", duration=time.monotonic() - started)

    text = decode_stream(out) + "\n" + decode_stream(err)
    (run_dir / f"{name}.log").write_text(
        f"$ {' '.join(cmd)}\n(cwd={cwd})\n[exit={code}]\n{text}", encoding="utf-8", errors="replace"
    )
    counts = parse_counts(text) if parse_counts_flag else {}
    status = "PASS" if code == 0 else "FAIL"
    return GateResult(name, " ".join(cmd), status, counts=counts, duration=time.monotonic() - started)


def build_gate_specs(mode: str) -> list[dict]:
    """组装门禁清单。compileall 范围以 041 §8 为准（含 prearchive_service）。"""
    py = sys.executable
    quick: list[dict] = [
        {"name": "compileall", "cmd": [py, "-m", "compileall", "app", "tests", "scripts", "prearchive_service"], "cwd": ROOT},
        {"name": "naming", "cmd": [py, "scripts/check_naming_convention.py"], "cwd": ROOT},
        {"name": "isolation", "cmd": [py, "prearchive_service/check_isolation.py"], "cwd": ROOT},
        {"name": "sidecar_check", "cmd": [py, "scripts/run_prearchive_demo_sidecar_20260904.py", "--check"], "cwd": ROOT},
    ]
    if mode == "quick":
        return quick
    npm = _resolve_tool("npm")
    return quick + [
        {"name": "main_pytest", "cmd": [py, "-m", "pytest"], "cwd": ROOT, "counts": True, "timeout": 7200},
        {"name": "prearchive_pytest", "cmd": [py, "-m", "pytest", "prearchive_service/tests"], "cwd": ROOT, "counts": True, "timeout": 3600},
        {"name": "typecheck", "cmd": [npm, "--prefix", "frontend", "run", "typecheck"], "cwd": ROOT, "timeout": 1800},
        {"name": "frontend_unit", "cmd": [npm, "--prefix", "frontend", "run", "test:unit"], "cwd": ROOT, "counts": True, "timeout": 1800},
        {"name": "build", "cmd": [npm, "--prefix", "frontend", "run", "build"], "cwd": ROOT, "timeout": 1800},
        {"name": "frontend_e2e", "cmd": [npm, "--prefix", "frontend", "run", "test:e2e"], "cwd": ROOT, "counts": True, "timeout": 3600},
    ]


def _kill_process_tree(pid: int) -> None:
    """Windows taskkill /T /F 杀整树；POSIX killpg（仅自建子进程才会传进来）。"""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=60)
    else:
        import signal
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except ProcessLookupError:
            pass


def _spawn_sidecar(run_dir: Path):
    """拉起 sidecar（--serve --import-rules），返回 (proc, 是否本脚本所有)。"""
    py = sys.executable
    cmd = [py, "scripts/run_prearchive_demo_sidecar_20260904.py", "--serve", "--import-rules"]
    log_file = open(run_dir / "legacy_sidecar_serve.log", "wb")
    proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=log_file, stderr=subprocess.STDOUT,
                            env=child_env_with_local_no_proxy(),
                            start_new_session=(sys.platform != "win32"))
    return proc


def _wait_port(port: int, want_listening: bool, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_port_listening("127.0.0.1", port) == want_listening:
            return True
        time.sleep(0.5)
    return False


def run_legacy_rule_center_e2e(run_dir: Path) -> GateResult:
    """可选步骤（042 T6 口径；048 Q1 扩展=规则中心+核查工作台双 spec）。

    demo 主服务在听才跑。正向轮：sidecar 在听（外部已在听则复用；否则本脚本
    拉起）→ 跑 rule-center.spec.ts + workbench.spec.ts（工作台造数由 spec 内
    调 scripts/seed_workbench_demo_20260915.py，幂等）。
    降级轮：前置=sidecar 不在听（spec 头注「停掉终端 A」）——自建 sidecar 杀树
    后跑；外部 sidecar 占用 18600 时不能杀，降级轮记 SKIPPED(external-sidecar)。
    """
    if not is_port_listening("127.0.0.1", DEMO_MAIN_PORT):
        return GateResult("legacy_rule_center_e2e", "(探测 18080)", "SKIPPED", note=f"no-demo(端口未听: {DEMO_MAIN_PORT})")

    npx = _resolve_tool("npx")
    frontend = ROOT / "frontend"
    spec_cmd = [npx, "playwright", "test", "-c", "playwright.legacy.config.ts",
                "tests/e2e-legacy/rule-center.spec.ts",
                "tests/e2e-legacy/workbench.spec.ts"]
    notes: list[str] = []

    sidecar_proc = None
    sidecar_killed = False   # 杀树幂等：正常路径杀过一次后 finally 不再重复杀

    def _kill_owned_sidecar() -> None:
        nonlocal sidecar_killed
        if sidecar_proc is not None and not sidecar_killed:
            _kill_process_tree(sidecar_proc.pid)
            sidecar_killed = True

    try:
        if not is_port_listening("127.0.0.1", SIDECAR_PORT):
            sidecar_proc = _spawn_sidecar(run_dir)
            if not _wait_port(SIDECAR_PORT, True):
                notes.append("sidecar 拉起失败(18600 未在听)")
                # D2（045）：拉起失败也必须清理本脚本自建的进程树，不留孤儿
                _kill_owned_sidecar()
                return GateResult("legacy_rule_center_e2e", " ".join(spec_cmd), "FAIL", note=";".join(notes))

        positive = run_command("legacy_rule_center_e2e_正向", spec_cmd, frontend, run_dir,
                               env={"LEGACY_E2E": "true"}, parse_counts_flag=True, timeout=1800)
        notes.append(f"正向:{positive.status}({positive.counts.get('passed', 0)} passed)")
        if positive.status != "PASS":
            _kill_owned_sidecar()
            return GateResult("legacy_rule_center_e2e", positive.command, "FAIL", note=";".join(notes),
                              duration=positive.duration)

        _kill_owned_sidecar()
        if sidecar_proc is not None:
            if not _wait_port(SIDECAR_PORT, False, timeout=15):
                notes.append("sidecar 杀树后 18600 仍在听")
                return GateResult("legacy_rule_center_e2e", positive.command, "FAIL", note=";".join(notes),
                                  duration=positive.duration)
            degraded = run_command("legacy_rule_center_e2e_降级", spec_cmd, frontend, run_dir,
                                   env={"LEGACY_E2E": "true", "RULE_CENTER_SIDECAR": "0"},
                                   parse_counts_flag=True, timeout=1800)
            notes.append(f"降级:{degraded.status}({degraded.counts.get('passed', 0)} passed)")
            if degraded.status != "PASS":
                return GateResult("legacy_rule_center_e2e", degraded.command, "FAIL", counts=degraded.counts,
                                  note=";".join(notes), duration=positive.duration + degraded.duration)
        else:
            notes.append("降级:SKIPPED(external-sidecar 占用 18600，不能杀；正向已 PASS)")
            return GateResult("legacy_rule_center_e2e", "playwright rule-center+workbench 双轮", "SKIPPED",
                              note=";".join(notes), duration=positive.duration)

        # D1（045）：双轮全 PASS 的耗时=正向+降级（此前漏加显示 0s）
        return GateResult("legacy_rule_center_e2e", "playwright rule-center+workbench 双轮", "PASS",
                          note=";".join(notes), duration=positive.duration + degraded.duration)
    finally:
        # D2（045）：任何异常路径退出前，本脚本自建的 sidecar 进程树必须回收
        try:
            _kill_owned_sidecar()
        except Exception:
            pass


def render_markdown_table(results: list[GateResult], mode: str, anchor_note: str) -> str:
    lines = [
        f"# 门禁表（run_gates --{mode}，{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}）",
        "",
        "| 门禁 | 结果 | 计数 | 耗时(s) | 备注 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in results:
        counts = " ".join(f"{k}={v}" for k, v in r.counts.items() if v) if r.counts else "-"
        note = r.note or ""
        lines.append(f"| {r.name} | {r.status} | {counts} | {r.duration:.0f} | {note} |")
    overall = "PASS" if all(r.status in ("PASS", "SKIPPED") for r in results) else "FAIL"
    lines += ["", f"**整体：{overall}**（SKIPPED 不算失败；FAIL 任一项即整体 FAIL）"]
    if anchor_note:
        lines.append(f"锚比较：{anchor_note}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="043 聚合门禁（--quick 冒烟 / --full 全量）")
    parser.add_argument("--quick", action="store_true", help="冒烟：compileall+naming+isolation+sidecar --check")
    parser.add_argument("--full", action="store_true", help="全量：quick 全部 + pytest/typecheck/unit/build/e2e + 可选 legacy 规则中心")
    parser.add_argument("--anchor-file", type=Path, default=None,
                        help="锚 json（缺省不比锚；传了且文件存在才比锚，低于锚退出非零）")
    parser.add_argument("--strict-ports", action="store_true", help="e2e 前 4173 被占用时直接 fail（默认警告并复用）")
    parser.add_argument("--timeout", type=int, default=None, help="单门禁超时秒数（缺省按门禁内置）")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.quick == args.full:
        build_parser().error("--quick 与 --full 必须二选一")
    mode = "full" if args.full else "quick"

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = RUNS_DIR / stamp
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"[run_gates] mode={mode} 输出目录={run_dir}")

    results: list[GateResult] = []
    for spec in build_gate_specs(mode):
        e2e_extra_env = None
        if spec["name"] == "frontend_e2e" and is_port_listening("127.0.0.1", PREVIEW_PORT):
            if args.strict_ports:
                # 原契约保持：strict 模式下 4173 任何占用（含历史进程，只报不杀）都判 FAIL
                results.append(GateResult("frontend_e2e", "(预检)", "FAIL", note="4173 占用且 --strict-ports"))
                print("[warn] 4173 已被占用 → --strict-ports 判 FAIL")
                continue
            # 046 ST-002：占用先核验服务身份；旧构建/外来服务改用空闲备选端口（只报不杀）
            port, note, base_url_env = resolve_preview_port()
            if port is None:
                results.append(GateResult("frontend_e2e", "(预检)", "FAIL", note=note))
                print(f"[warn] {note} → frontend_e2e 判 FAIL")
                continue
            if base_url_env is not None:
                e2e_extra_env = {"PLAYWRIGHT_BASE_URL": base_url_env}
            print(f"[warn] 4173 已被占用：{note}"
                  + (f"；注入 PLAYWRIGHT_BASE_URL={base_url_env}" if base_url_env else "（复用）"))
        timeout = args.timeout or spec.get("timeout", 3600)
        results.append(run_command(
            spec["name"], spec["cmd"], spec["cwd"], run_dir,
            parse_counts_flag=spec.get("counts", False), timeout=timeout,
            env=e2e_extra_env,
        ))
        print(f"[gate] {results[-1].name}: {results[-1].status} {results[-1].counts or ''}")

    if mode == "full":
        legacy = run_legacy_rule_center_e2e(run_dir)
        results.append(legacy)
        print(f"[gate] {legacy.name}: {legacy.status} {legacy.note}")

    # 锚比较（可选）：传了且文件存在才比
    anchor_problems: list[str] = []
    anchor_note = "未比锚（未传 --anchor-file）"
    if args.anchor_file is not None:
        if args.anchor_file.exists():
            try:
                anchors = load_anchor_file(args.anchor_file)
                by_name = {r.name: r.to_dict() for r in results}
                anchor_problems = compare_with_anchors(by_name, anchors)
                anchor_note = f"低于锚 {len(anchor_problems)} 项" if anchor_problems else "全部不低于锚"
            except (ValueError, json.JSONDecodeError) as exc:
                anchor_note = f"锚文件解析失败({exc})，按未比锚处理"
        else:
            anchor_note = f"未比锚（{args.anchor_file} 不存在，只出表）"

    table = render_markdown_table(results, mode, anchor_note)
    print()
    print(table)
    (run_dir / "summary.md").write_text(table + "\n", encoding="utf-8", errors="replace")
    result_json = {
        "mode": mode, "timestamp": stamp, "anchor_note": anchor_note,
        "results": {r.name: r.to_dict() for r in results},
    }
    (run_dir / "result.json").write_text(
        json.dumps(result_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    failed = [r.name for r in results if r.status == "FAIL"]
    exit_code = 1 if (failed or anchor_problems) else 0
    if failed:
        print(f"[exit 1] FAIL 门禁：{', '.join(failed)}")
    elif anchor_problems:
        print(f"[exit 1] 低于锚：{'; '.join(anchor_problems)}")
    else:
        print("[exit 0]")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
