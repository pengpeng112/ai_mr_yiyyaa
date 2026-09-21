"""043 R2 demo 端口清理：默认 dry-run，--yes 才执行（043 §3 裁定 7）。

- 默认可杀端口 = 18080/18081/18082/18600（demo 主服务 + sidecar）；
- 4173 只报告不杀（REPORT-ONLY）：Playwright preview webServer 归属，reuseExistingServer 设计为复用；
- netstat 解析同时匹配 LISTENING 与 侦听（中文 Windows 本地化）；
- Windows 用 taskkill /PID <pid> /T /F 杀进程树；POSIX 只杀本脚本自建进程组（start_new_session），
  不误伤任何外部进程（本脚本不创建进程，POSIX 下因此恒为空操作）。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

KILLABLE_PORTS = (18080, 18081, 18082, 18600)
REPORT_ONLY_PORTS = (4173,)  # Playwright preview；只报不杀
LISTENING_STATES = ("LISTENING", "侦听")


@dataclass
class PortEntry:
    port: int
    pid: int
    state: str


def classify_port(port: int, killable: tuple[int, ...] = KILLABLE_PORTS) -> str:
    if port in REPORT_ONLY_PORTS:
        return "report-only"
    if port in killable:
        return "killable"
    return "ignored"


def parse_netstat_output(text: str) -> list[PortEntry]:
    """解析 netstat -ano 输出；只认 TCP 且状态为 LISTENING/侦听 的行（中英文双关键词）。"""
    entries: list[PortEntry] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        state = parts[-2]
        if state not in LISTENING_STATES:
            continue
        local = parts[1]
        match = re.search(r":(\d+)$", local)
        if not match:
            continue
        pid_text = parts[-1]
        if not pid_text.isdigit():
            continue
        entries.append(PortEntry(port=int(match.group(1)), pid=int(pid_text), state=state))
    return entries


def collect_entries(killable: tuple[int, ...] = KILLABLE_PORTS) -> list[PortEntry]:
    """netstat -ano 输出在中文 Windows 为本地编码（GBK），先本地编码解码，无监听关键词再退 utf-8。"""
    proc = subprocess.run(["netstat", "-ano"], capture_output=True, timeout=60)
    text = proc.stdout.decode(locale_encoding(), errors="replace")
    if "侦听" not in text and "LISTENING" not in text:
        text = proc.stdout.decode("utf-8", errors="replace")
    return [e for e in parse_netstat_output(text) if classify_port(e.port, killable) != "ignored"]


def locale_encoding() -> str:
    import locale
    return locale.getpreferredencoding(False) or "gbk"


def kill_pid_tree(pid: int) -> bool:
    """Windows：taskkill /PID <pid> /T /F；POSIX：仅当 pid 属于本脚本自建进程组才杀（当前恒无）。"""
    if sys.platform == "win32":
        proc = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=60)
        return proc.returncode == 0
    # POSIX 红线：不误伤父进程/外部进程；本脚本未以 start_new_session 创建任何进程组
    print(f"[skip] POSIX 模式只杀本脚本自建进程组，pid={pid} 非自建，跳过")
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="043 demo 端口清理（默认 dry-run）")
    parser.add_argument("--yes", action="store_true", help="真杀（缺省只打印计划）")
    parser.add_argument("--ports", type=str, default=None,
                        help="覆盖可杀端口列表（逗号分隔；4173 恒为只报不杀）")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    killable = tuple(int(p) for p in args.ports.split(",")) if args.ports else KILLABLE_PORTS
    mode = "EXECUTE" if args.yes else "DRY-RUN"
    print(f"[clean_demo_ports] mode={mode} 可杀={list(killable)} 只报不杀={list(REPORT_ONLY_PORTS)}")

    entries = collect_entries(killable)
    if not entries:
        print("[clean_demo_ports] none（无 demo 端口残留）")
        return 0

    exit_code = 0
    for entry in entries:
        kind = classify_port(entry.port, killable)
        if kind == "report-only":
            print(f"REPORT-ONLY 端口 {entry.port} 被 pid={entry.pid} 占用（Playwright preview 归属，不杀）")
            continue
        action = "KILL" if args.yes else "would-kill"
        print(f"{action} 端口 {entry.port} pid={entry.pid} (state={entry.state})")
        if args.yes:
            if not kill_pid_tree(entry.pid):
                print(f"[warn] pid={entry.pid} 杀失败（可能已退出）")
                exit_code = 0  # 端口竞争退出不算失败
    print(f"[clean_demo_ports] done（{mode}）")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
