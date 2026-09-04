# -*- coding: utf-8 -*-
"""041 T1 归档前规则中心 demo sidecar 启动/探测/编排脚本（2026-09-04）。

在本机隔离环境把 039 规则中心的管理 API（prearchive.admin_api）拉到
127.0.0.1:18600：fixture 源、sqlite 规则六表、假 admin token、推送关闭。

用法（仓库根运行）::

    # 前台常驻（先幂等导入 14 条正式规则再监听）
    python scripts/run_prearchive_demo_sidecar_20260904.py --serve --import-rules

    # 自检：自动拉起 sidecar → healthz → 带 HMAC 四件套探测 settings → 退出杀整进程树
    python scripts/run_prearchive_demo_sidecar_20260904.py --check

    # 只导入规则（sqlite 规则仓），不起服务
    python scripts/run_prearchive_demo_sidecar_20260904.py --import-rules

    # 编排（T6）：sidecar + demo 主服务 18080，Ctrl+C 一起清理
    python scripts/run_prearchive_demo_sidecar_20260904.py --with-demo-e2e --demo-run-id rulecenter

安全边界：只绑 127.0.0.1；真实业务源全关（dry-run 走 demo fixtures）；
token/密钥为 config.demo.json 中的显式假值；不读生产 config、不扫局域网。
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parents[1]
PREARCHIVE_DIR = REPO_ROOT / "prearchive_service"
DEMO_CONFIG = PREARCHIVE_DIR / "config.demo.json"

HOST = "127.0.0.1"
PORT = 18600
HEALTHZ_URL = f"http://{HOST}:{PORT}/healthz"
SETTINGS_URL = f"http://{HOST}:{PORT}/api/admin/settings"

HEALTHZ_RETRIES = 10
HEALTHZ_INTERVAL_SECONDS = 1.0


def _load_prearchive():
    """把 prearchive_service/ 加入 sys.path 并返回 prearchive 包（只在此脚本进程内）。"""
    if str(PREARCHIVE_DIR) not in sys.path:
        sys.path.insert(0, str(PREARCHIVE_DIR))
    import prearchive  # noqa: F401 — 确保 preload
    return prearchive


def build_probe_headers(admin_token: str, signing_secret: str,
                        actor_id: str = "demo-probe",
                        actor_name: str = "demo-probe",
                        permissions: tuple[str, ...] = ("prearchive_rule_view",),
                        request_id: str | None = None) -> dict:
    """组装与 sidecar 契约一致的探测头（Admin-Token + Actor 四件套 + HMAC）。

    与主服务 BFF `prearchive_admin_client._headers`、预检 `admin_api.actor_signature`
    同口径：actor_name percent-encode 后参与签名，permissions 逗号拼接排序去重。
    """
    request_id = request_id or f"probe-{uuid.uuid4().hex[:12]}"
    encoded_name = quote(str(actor_name), safe="")
    perms = ",".join(sorted(set(permissions)))
    signature = hmac.new(
        signing_secret.encode("utf-8"),
        f"{actor_id}|{encoded_name}|{perms}|{request_id}".encode("utf-8"),
        hashlib.sha256).hexdigest()
    return {
        "X-Admin-Token": admin_token,
        "X-Actor-Id": actor_id,
        "X-Actor-Name": encoded_name,
        "X-Actor-Permissions": perms,
        "X-Request-Id": request_id,
        "X-Actor-Signature": signature,
    }


def port_open(port: int, host: str = HOST, timeout: float = 0.4) -> bool:
    """探测端口是否已有监听（不 bind，不占用）。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_get(url: str, headers: dict | None = None, timeout: float = 5.0):
    """极简 GET（urllib，避免为本脚本引入 requests 依赖差异）。"""
    import urllib.request
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:   # 4xx/5xx 也要拿到状态码
        return exc.code, exc.read().decode("utf-8", "replace")


def wait_healthz(retries: int = HEALTHZ_RETRIES,
                 interval: float = HEALTHZ_INTERVAL_SECONDS) -> bool:
    for _ in range(retries):
        if port_open(PORT):
            try:
                status, _ = _http_get(HEALTHZ_URL, timeout=2.0)
                if status == 200:
                    return True
            except OSError:
                pass
        time.sleep(interval)
    return False


def kill_process_tree(proc: subprocess.Popen) -> None:
    """杀整进程树：Windows 用 taskkill /T（uvicorn 可能再拉子进程），POSIX 杀进程组。"""
    if proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, check=False)
        else:
            import signal
            import os
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
    finally:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def spawn_sidecar(extra_args: list[str] | None = None) -> subprocess.Popen:
    """以后台子进程方式拉起本脚本的 --serve（独立进程组，便于整树回收）。"""
    command = [sys.executable, str(Path(__file__).resolve()), "--serve"]
    command.extend(extra_args or [])
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        import os
        creationflags = 0  # POSIX 走 killpg；start_new_session 由 Popen 参数控制
    kwargs = {"cwd": str(REPO_ROOT)}
    if sys.platform != "win32":
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(command, creationflags=creationflags, **kwargs)
    return proc


def _demo_admin_credentials() -> tuple[str, str]:
    config = json.loads(DEMO_CONFIG.read_text(encoding="utf-8"))
    admin_cfg = config.get("admin_api") or {}
    return str(admin_cfg.get("admin_token") or ""), str(admin_cfg.get("signing_secret") or "")


def do_import_rules() -> int:
    """幂等导入 14 条正式规则到 sqlite 规则仓（等价 rule_admin import-files --apply）。"""
    _load_prearchive()
    from prearchive import rule_admin
    report = rule_admin.main(["--config", str(DEMO_CONFIG),
                              "import-files", "--apply"])
    return int(report or 0)


def build_demo_app():
    """组装 demo sidecar 应用：healthz（心跳线程）+ 规则中心 admin API。"""
    _load_prearchive()
    from prearchive.config import load_config, resolve_base_dir, resolve_path
    from prearchive.heartbeat import Heartbeat
    from prearchive.models import build_session_factory, build_sqlite_engine
    from prearchive.rule_repository import RuleRepository
    from prearchive.rule_service import RuleService, rule_registry_settings
    from prearchive.store import ResultRepository
    from prearchive.api import create_app

    config = load_config(str(DEMO_CONFIG))
    base_dir = resolve_base_dir(str(DEMO_CONFIG))
    store_cfg = config.get("result_store") or {}
    db_path = resolve_path(base_dir, store_cfg.get("sqlite_path")
                           or "data/demo/prearchive_result.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    session_factory = build_session_factory(build_sqlite_engine(str(db_path)))

    registry_settings = rule_registry_settings(config)
    rule_repo = RuleRepository(session_factory)
    rule_service = RuleService(
        rule_repo,
        require_separate_approver=registry_settings["require_separate_approver"])
    result_repo = ResultRepository(session_factory)

    heartbeat = Heartbeat(resolve_path(
        base_dir, (config.get("service") or {}).get("heartbeat_file")
        or "data/demo/heartbeat.json"))
    heartbeat.write({"note": "demo sidecar boot"})

    stop = threading.Event()

    def _heartbeat_loop():
        while not stop.wait(60):
            heartbeat.write({"note": "demo sidecar"})

    threading.Thread(target=_heartbeat_loop, name="demo-heartbeat",
                     daemon=True).start()

    application = create_app(
        config=config,
        repository=result_repo,
        heartbeat=heartbeat,
        watermark_provider=lambda: None,
        poller=None,
        rule_center={"repository": rule_repo, "service": rule_service},
    )
    return application


def do_serve() -> int:
    do_import_rules()
    application = build_demo_app()
    import uvicorn
    uvicorn.run(application, host=HOST, port=PORT, log_level="info")
    return 0


def do_check() -> int:
    """门禁自检：拉起（或复用已占端口的现存服务）→ healthz → HMAC settings 200。"""
    admin_token, signing_secret = _demo_admin_credentials()
    if not admin_token or not signing_secret:
        print("[check] config.demo.json 缺少假 admin token/signing_secret", file=sys.stderr)
        return 2

    already_running = port_open(PORT)
    proc = None
    try:
        if already_running:
            print(f"[check] 端口 {PORT} 已被占用，视为服务已在，只探测不二次 bind")
        else:
            print(f"[check] 端口 {PORT} 空闲，拉起 demo sidecar 子进程 ...")
            proc = spawn_sidecar()
        if not wait_healthz():
            print(f"[check] healthz 探测失败（{HEALTHZ_RETRIES} 次重试）", file=sys.stderr)
            return 2
        status, _ = _http_get(HEALTHZ_URL, timeout=3.0)
        print(f"[check] healthz -> {status}")
        if status != 200:
            return 2

        headers = build_probe_headers(admin_token, signing_secret)
        status, body = _http_get(SETTINGS_URL, headers=headers, timeout=5.0)
        print(f"[check] settings(带 Admin-Token+Actor 四件套+HMAC) -> {status}")
        if status != 200:
            print(f"[check] settings 响应: {body[:300]}", file=sys.stderr)
            return 2
        print("[check] PASS：sidecar 可用且签名链路通过")
        return 0
    finally:
        if proc is not None:
            print("[check] 退出：清理本脚本拉起的 sidecar 进程树")
            kill_process_tree(proc)
            print("[check] 进程树已回收")


def do_with_demo_e2e(demo_run_id: str, app_port: int = 18080) -> int:
    """T6 编排：sidecar（后台）+ demo 主服务（复用 scripts/demo_env.py，不另造协议）。"""
    print(f"[e2e] 启动 demo sidecar（{HOST}:{PORT}）...")
    sidecar = spawn_sidecar()
    demo_started = False
    try:
        if not wait_healthz():
            print("[e2e] sidecar healthz 超时", file=sys.stderr)
            return 2
        print(f"[e2e] sidecar 就绪 -> {HEALTHZ_URL}")

        if port_open(app_port):
            print(f"[e2e] 主服务 {app_port} 已在运行，复用现有 demo serve")
        else:
            state_file = REPO_ROOT / "data" / "demo" / demo_run_id / "state.json"
            workspace_root = REPO_ROOT / "data" / "demo" / demo_run_id
            # demo_env.py 的 run 目录约定：<workspace>/data|config|logs/demo/<run_id>
            marker = REPO_ROOT / "data" / "demo" / demo_run_id / "data" / "demo" / demo_run_id
            if not marker.exists():
                print(f"[e2e] demo run_id={demo_run_id} 不存在，先 create（showcase 默认造数）...")
                created = subprocess.run(
                    [sys.executable, str(REPO_ROOT / "scripts" / "demo_env.py"),
                     "create", "--run-id", demo_run_id],
                    cwd=str(REPO_ROOT))
                if created.returncode != 0:
                    print("[e2e] demo create 失败", file=sys.stderr)
                    return 2
            print(f"[e2e] 启动 demo 主服务（demo_env.py serve，端口 {app_port}）...")
            demo = subprocess.Popen(
                [sys.executable, str(REPO_ROOT / "scripts" / "demo_env.py"),
                 "serve", "--run-id", demo_run_id],
                cwd=str(REPO_ROOT))
            demo_started = True
            for _ in range(30):
                if port_open(app_port):
                    break
                if demo.poll() is not None:
                    print("[e2e] demo serve 子进程异常退出", file=sys.stderr)
                    return 2
                time.sleep(1.0)
            if not port_open(app_port):
                print(f"[e2e] 主服务 {app_port} 未就绪", file=sys.stderr)
                return 2
        print(f"[e2e] 编排就绪：sidecar={HOST}:{PORT} 主服务=127.0.0.1:{app_port}")
        print("[e2e] Ctrl+C 结束并清理 ...")
        try:
            while True:
                time.sleep(1.0)
                if sidecar.poll() is not None:
                    print("[e2e] sidecar 进程退出，编排结束", file=sys.stderr)
                    return 2
        except KeyboardInterrupt:
            print("[e2e] 收到 Ctrl+C，清理 ...")
            return 0
    finally:
        print("[e2e] 回收 sidecar 进程树")
        kill_process_tree(sidecar)
        if demo_started:
            print(f"[e2e] 停止 demo 主服务（demo_env.py stop --run-id {demo_run_id}）")
            subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts" / "demo_env.py"),
                 "stop", "--run-id", demo_run_id],
                cwd=str(REPO_ROOT), capture_output=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="041 规则中心隔离 demo sidecar（仅 127.0.0.1:18600，零生产）")
    parser.add_argument("--serve", action="store_true",
                        help="前台常驻：先幂等导入规则再监听")
    parser.add_argument("--import-rules", action="store_true",
                        help="导入 14 条正式规则到 sqlite 规则仓（--serve 时自动先做）")
    parser.add_argument("--check", action="store_true",
                        help="自检：拉起→healthz→HMAC settings 200→杀整进程树")
    parser.add_argument("--with-demo-e2e", action="store_true",
                        help="编排：sidecar + demo 主服务 18080（复用 demo_env.py）")
    parser.add_argument("--demo-run-id", default="rulecenter",
                        help="--with-demo-e2e 使用的 demo run_id（默认 rulecenter）")
    args = parser.parse_args(argv)

    selected = [name for name, on in (
        ("--serve", args.serve), ("--import-rules", args.import_rules),
        ("--check", args.check), ("--with-demo-e2e", args.with_demo_e2e)) if on]
    if not selected:
        parser.print_help()
        return 1
    if sum(1 for _ in selected) > 1 and not (args.serve and args.import_rules):
        print("参数互斥：--serve/--import-rules 可组合，其余单选", file=sys.stderr)
        return 1

    if args.check:
        return do_check()
    if args.with_demo_e2e:
        return do_with_demo_e2e(args.demo_run_id)
    if args.import_rules and not args.serve:
        return do_import_rules()
    return do_serve()


if __name__ == "__main__":
    sys.exit(main())
