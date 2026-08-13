"""12 科室脱敏合成测试环境的一键生命周期工具。

环境变量必须在 import app.* 前设置，因此本文件顶层只使用标准库。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time


WORKSPACE = Path(__file__).resolve().parent.parent
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))
RUN_ID_PATTERN = __import__("re").compile(r"^[a-z0-9][a-z0-9_-]{2,47}$")


def _paths(run_id: str) -> dict[str, Path]:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise SystemExit("run_id 仅允许 3-48 位小写字母、数字、下划线或连字符")
    return {
        "data": (WORKSPACE / "data" / "demo" / run_id).resolve(),
        "config": (WORKSPACE / "config" / "demo" / run_id).resolve(),
        "logs": (WORKSPACE / "logs" / "demo" / run_id).resolve(),
    }


def _state_path(run_id: str) -> Path:
    return _paths(run_id)["config"] / "runtime.json"


def _read_state(run_id: str) -> dict:
    path = _state_path(run_id)
    if not path.exists():
        raise SystemExit(f"测试环境不存在: {run_id}")
    return json.loads(path.read_text("utf-8"))


def _apply_env(run_id: str, state: dict) -> dict[str, str]:
    paths = _paths(run_id)
    values = {
        "APP_DB_TYPE": "sqlite",
        "DATA_DIR": str(paths["data"]),
        "CONFIG_DIR": str(paths["config"]),
        "CONFIG_TEMPLATE_PATH": str(paths["config"] / "config.json.template"),
        "LOG_DIR": str(paths["logs"]),
        "ENABLE_SCHEDULER": "false",
        "TEST_ISOLATED_MODE": "true",
        "DEMO_MODE": "true",
        "DEMO_RUN_ID": run_id,
        "DEMO_WORKSPACE_ROOT": str(WORKSPACE),
        "DEMO_RELAY_SECRET": state.get("relay_secret", "demo-relay-secret-2026"),
        "DEMO_APP_BASE_URL": f"http://127.0.0.1:{state.get('app_port', 18080)}",
        "JWT_SECRET_KEY": state["jwt_secret"],
        "SECRET_KEY": state["config_secret"],
        "ENVIRONMENT": "development",
        "APP_ENV": "development",
        "UI_DEFAULT_ENTRY": "ui-next",
        "ENABLE_API_DOCS": "true",
        "ALLOWED_ORIGINS": f"http://127.0.0.1:{state.get('app_port', 18080)}",
    }
    os.environ.update(values)
    return {**os.environ, **values}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", "utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create(args) -> None:
    paths = _paths(args.run_id)
    existing = [path for path in paths.values() if path.exists() and any(path.iterdir())]
    if existing:
        raise SystemExit("目标运行目录非空，请使用 reset 或新的 run_id: " + ", ".join(map(str, existing)))
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    state = {
        "run_id": args.run_id,
        "profile": args.profile,
        "seed": args.seed,
        "app_port": args.app_port,
        "dify_port": args.dify_port,
        "relay_port": args.relay_port,
        "jwt_secret": secrets.token_urlsafe(48),
        "config_secret": secrets.token_urlsafe(48),
        "relay_secret": "demo-relay-secret-2026",
        "created_at": __import__("datetime").datetime.now().isoformat(),
    }
    _apply_env(args.run_id, state)
    from app.demo_support.dataset import build_demo_config

    config = build_demo_config(args.app_port, args.dify_port, args.relay_port)
    config["demo_environment"]["run_id"] = args.run_id
    config["demo_environment"]["profile"] = args.profile
    config["demo_environment"]["seed"] = args.seed
    config["relay_alert"]["secret_key"] = state["relay_secret"]
    _write_json(paths["config"] / "config.json.template", config)
    _write_json(paths["config"] / "config.json", config)
    _write_json(_state_path(args.run_id), state)

    try:
        from app.demo_support.seed import DEMO_PASSWORD, build_entity_projections, seed_database

        manifest = seed_database(profile=args.profile, seed=args.seed)
        _write_json(paths["config"] / "baseline_entities.json", build_entity_projections())
        db_path = paths["data"] / "med_audit.db"
        manifest["run"] = {
            "run_id": args.run_id,
            "created_at": state["created_at"],
            "database_sha256": _sha256_file(db_path),
            "ports": {"app": args.app_port, "dify": args.dify_port, "relay": args.relay_port},
        }
        _write_json(paths["config"] / "manifest.json", manifest)
        _write_json(paths["config"] / "credentials.json", {
            "synthetic": True,
            "warning": "仅限本机隔离测试，禁止用于生产",
            "password": DEMO_PASSWORD,
            "users": ["demo_admin", "demo_auditor", "manager_d001", "clinician_d001"],
        })
    except Exception:
        print("创建失败；隔离目录保留以便诊断，可运行 destroy --force 清理。", file=sys.stderr)
        raise
    print(json.dumps({"ok": True, "run_id": args.run_id, "profile": args.profile, "manifest": str(paths["config"] / "manifest.json"), "login": {"username": "demo_admin", "password": DEMO_PASSWORD}}, ensure_ascii=False, indent=2))


def verify(args) -> None:
    state = _read_state(args.run_id)
    _apply_env(args.run_id, state)
    from app.config import load_config
    from app.database import SessionLocal
    from app.demo_support.dataset import AUDIT_TYPES
    from app.demo_support.seed import PROFILE_SIZES, build_entity_projections, build_manifest
    from app.models import PushLog

    config = load_config()  # 同时执行全部外联地址硬门禁
    db = SessionLocal()
    try:
        manifest = build_manifest(db, profile=state["profile"], seed=state["seed"])
        baseline_path = _paths(args.run_id)["config"] / "manifest.json"
        baseline_entities_path = _paths(args.run_id)["config"] / "baseline_entities.json"
        if not baseline_path.exists():
            raise SystemExit("验收失败: baseline manifest missing")
        if not baseline_entities_path.exists():
            raise SystemExit("验收失败: baseline entity projections missing")
        baseline = json.loads(baseline_path.read_text("utf-8"))
        baseline_entities = json.loads(baseline_entities_path.read_text("utf-8"))
        current_entities = build_entity_projections(db)
        expected_logs = PROFILE_SIZES[state["profile"]] * 12
        errors = []
        if manifest["counts"]["departments"] != 12:
            errors.append("departments != 12")
        actual_logs = manifest["counts"]["push_logs"]
        if (args.allow_drift and actual_logs < expected_logs) or (not args.allow_drift and actual_logs != expected_logs):
            operator = ">=" if args.allow_drift else "=="
            errors.append(f"push_logs must be {operator} {expected_logs}, actual={actual_logs}")
        expected_per_dept = PROFILE_SIZES[state["profile"]]
        invalid_dept_count = any(
            count < expected_per_dept if args.allow_drift else count != expected_per_dept
            for count in manifest["push_logs_by_dept"].values()
        )
        if len(manifest["push_logs_by_dept"]) != 12 or invalid_dept_count:
            errors.append("per-department PushLog distribution mismatch")
        expected_codes = sorted(item["code"] for item in AUDIT_TYPES)
        database_codes = sorted(
            str(code or "").strip()
            for (code,) in db.query(PushLog.audit_type_code).distinct().all()
            if str(code or "").strip()
        )
        config_codes = sorted(
            str(item.get("code") or "").strip()
            for item in (config.get("audit_types") or [])
            if str(item.get("code") or "").strip()
        )
        if database_codes != expected_codes:
            errors.append(f"database audit types mismatch: {database_codes}")
        if config_codes != expected_codes:
            errors.append(f"config audit types mismatch: {config_codes}")
        if not {"success", "failed", "skipped"}.issubset(manifest["push_logs_by_status"]):
            errors.append("success/failed/skipped coverage missing")
        if args.allow_drift:
            for name, baseline_count in (baseline.get("counts") or {}).items():
                if int(manifest["counts"].get(name, 0)) < int(baseline_count):
                    errors.append(f"baseline {name} rows were removed")
            for name, baseline_rows in baseline_entities.items():
                missing_rows = set(baseline_rows) - set(current_entities.get(name) or [])
                if missing_rows:
                    errors.append(f"baseline {name} projections missing/changed: {len(missing_rows)}")
        else:
            if manifest.get("dataset_contract_digest") != baseline.get("dataset_contract_digest"):
                errors.append("strict dataset contract digest mismatch")
            if current_entities != baseline_entities:
                errors.append("strict entity projection mismatch")
        non_synthetic = db.query(PushLog).filter(~PushLog.patient_id.like("SYNTH-%")).count()
        if non_synthetic:
            errors.append(f"non-synthetic patient ids: {non_synthetic}")
        if not manifest["counts"]["qc_feedback"] or not manifest["counts"]["relay_alerts"] or not manifest["counts"]["h5_feedback"]:
            errors.append("feedback/relay/H5 closure data missing")
        if errors:
            raise SystemExit("验收失败: " + "; ".join(errors))
        print(json.dumps({
            "ok": True,
            "run_id": args.run_id,
            "zero_external_config": True,
            "allow_drift": bool(args.allow_drift),
            "baseline_counts": baseline.get("counts", {}),
            "current_counts": manifest.get("counts", {}),
            "manifest": manifest,
        }, ensure_ascii=False, indent=2))
    finally:
        db.close()


def verify_absent(args) -> None:
    paths = _paths(args.run_id)
    existing = [str(path) for path in paths.values() if path.exists()]
    if existing:
        raise SystemExit("销毁验收失败，目录仍存在: " + ", ".join(existing))
    print(json.dumps({"ok": True, "run_id": args.run_id, "absent": True, "paths": [str(path) for path in paths.values()]}, ensure_ascii=False, indent=2))


def status(args) -> None:
    paths = _paths(args.run_id)
    manifest_path = paths["config"] / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"测试环境不存在或创建未完成: {args.run_id}")
    print(manifest_path.read_text("utf-8"))


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259
        handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, int(pid))
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == still_active
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _process_identity(pid: int) -> dict:
    """返回可抵抗 PID 重用的进程身份；无法读取时返回空字典并拒绝终止。"""
    if not _pid_alive(pid):
        return {}
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, int(pid))
        if not handle:
            return {}
        try:
            class FileTime(ctypes.Structure):
                _fields_ = [("low", ctypes.c_ulong), ("high", ctypes.c_ulong)]

            creation, exit_time, kernel, user = FileTime(), FileTime(), FileTime(), FileTime()
            if not ctypes.windll.kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ):
                return {}
            size = ctypes.c_ulong(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            executable = ""
            if ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                executable = str(buffer.value).lower()
            created = (int(creation.high) << 32) | int(creation.low)
            return {"pid": int(pid), "created": str(created), "executable": executable}
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    proc = Path("/proc") / str(pid)
    try:
        created = str(proc.stat().st_ctime_ns)
        executable = str((proc / "exe").resolve())
        command = (proc / "cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", "replace").strip()
        return {"pid": int(pid), "created": created, "executable": executable, "command_line": command}
    except OSError:
        return {}


def _same_process(entry: dict) -> bool:
    pid = int(entry.get("pid") or 0)
    current = _process_identity(pid)
    if not current:
        return False
    return bool(entry.get("created")) and current.get("created") == entry.get("created") and current.get("executable") == entry.get("executable")


def _terminate_process(entry: dict) -> None:
    pid = int(entry.get("pid") or 0)
    if not _same_process(entry):
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False, capture_output=True)
        else:
            os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.25):
            return True
    except OSError:
        return False


def _runtime_ports(state: dict) -> list[int]:
    return [int(state[name]) for name in ("app_port", "dify_port", "relay_port")]


def _occupied_run_ports(run_id: str) -> list[int]:
    state_path = _state_path(run_id)
    if not state_path.exists():
        return []
    state = json.loads(state_path.read_text("utf-8"))
    return [port for port in _runtime_ports(state) if _port_open(port)]


def _owned_runtime_payload(path: Path, owner_token: str) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if secrets.compare_digest(str(payload.get("owner_token") or ""), str(owner_token or "")) else {}


def _remove_owned_runtime_files(run_id: str, owner_token: str) -> None:
    config_dir = _paths(run_id)["config"]
    for name in ("pids.json", "serve.lock"):
        path = config_dir / name
        if _owned_runtime_payload(path, owner_token) and path.exists():
            path.unlink()


def stop(args) -> None:
    paths = _paths(args.run_id)
    pid_file = paths["config"] / "pids.json"
    lock_file = paths["config"] / "serve.lock"
    runtime_file = pid_file if pid_file.exists() else lock_file
    if not runtime_file.exists():
        occupied = _occupied_run_ports(args.run_id)
        if occupied:
            raise SystemExit(f"缺少运行锁但测试端口仍被占用，拒绝假报已停止: {occupied}")
        print(json.dumps({"ok": True, "run_id": args.run_id, "stopped": True, "reason": "no_pid_file"}, ensure_ascii=False, indent=2))
        return
    payload = json.loads(runtime_file.read_text("utf-8"))
    if payload.get("run_id") != args.run_id or not payload.get("owner_token"):
        raise SystemExit("运行锁身份无效，拒绝终止任何进程")
    entries = list(payload.get("processes") or [])
    if not entries and payload.get("owner"):
        entries = [payload["owner"]]
    if not entries:
        raise SystemExit("运行锁缺少进程身份，拒绝终止任何进程")
    unverified_alive = [
        int(entry.get("pid") or 0)
        for entry in entries
        if int(entry.get("pid") or 0) > 0 and _pid_alive(int(entry.get("pid") or 0)) and not _same_process(entry)
    ]
    if unverified_alive:
        raise SystemExit(f"运行进程身份无法验证，保留锁并拒绝终止: {unverified_alive}")
    # 子进程先停、父进程后停，避免父进程立刻以异常退出覆盖诊断。
    matched = [entry for entry in entries if _same_process(entry)]
    for entry in reversed(matched):
        _terminate_process(entry)
    deadline = time.time() + 8
    while time.time() < deadline and any(_same_process(entry) for entry in matched):
        time.sleep(0.2)
    alive = [int(entry["pid"]) for entry in matched if _same_process(entry)]
    if alive:
        raise SystemExit(f"仍有测试进程未停止: {alive}")
    occupied = _occupied_run_ports(args.run_id)
    if occupied:
        raise SystemExit(f"测试端口仍被占用，保留运行锁: {occupied}")
    _remove_owned_runtime_files(args.run_id, payload["owner_token"])
    print(json.dumps({"ok": True, "run_id": args.run_id, "stopped": True, "pids": [int(entry["pid"]) for entry in matched]}, ensure_ascii=False, indent=2))


def destroy(args) -> None:
    paths = _paths(args.run_id)
    pid_file = paths["config"] / "pids.json"
    lock_file = paths["config"] / "serve.lock"
    runtime_file = pid_file if pid_file.exists() else lock_file
    if runtime_file.exists():
        payload = json.loads(runtime_file.read_text("utf-8"))
        entries = list(payload.get("processes") or []) or ([payload.get("owner")] if payload.get("owner") else [])
        alive = [int(entry["pid"]) for entry in entries if entry and _same_process(entry)]
        if alive and not args.force:
            raise SystemExit(f"测试服务仍在运行 {alive}；请先 Ctrl+C 或使用 --force")
        if alive:
            stop(argparse.Namespace(run_id=args.run_id))
        elif payload.get("owner_token"):
            _remove_owned_runtime_files(args.run_id, payload["owner_token"])
    if _state_path(args.run_id).exists():
        state = _read_state(args.run_id)
        occupied = [port for port in _runtime_ports(state) if _port_open(port)]
        if occupied:
            raise SystemExit(f"测试端口仍被占用，拒绝销毁目录: {occupied}")
    expected = _paths(args.run_id)
    for key, path in paths.items():
        resolved = path.resolve()
        if resolved != expected[key] or resolved.name != args.run_id or resolved.parent.name != "demo":
            raise SystemExit(f"拒绝删除未通过路径校验的目录: {resolved}")
    for path in paths.values():
        if path.exists():
            last_error = None
            for _attempt in range(10):
                try:
                    shutil.rmtree(path)
                    last_error = None
                    break
                except PermissionError as exc:
                    last_error = exc
                    time.sleep(0.3)
            if last_error is not None:
                raise last_error
    absent = all(not path.exists() for path in paths.values())
    if not absent:
        raise SystemExit("销毁后目录仍存在")
    print(json.dumps({"ok": True, "destroyed": args.run_id, "recoverable": False, "paths": [str(path) for path in paths.values()]}, ensure_ascii=False, indent=2))


def reset(args) -> None:
    if _state_path(args.run_id).exists():
        old = _read_state(args.run_id)
        destroy(argparse.Namespace(run_id=args.run_id, force=True))
        args.profile = args.profile or old["profile"]
        args.seed = args.seed if args.seed is not None else old["seed"]
        args.app_port = old["app_port"]
        args.dify_port = old["dify_port"]
        args.relay_port = old["relay_port"]
    if args.profile is None:
        args.profile = "showcase"
    if args.seed is None:
        args.seed = 20260813
    create(args)


def serve(args) -> None:
    state = _read_state(args.run_id)
    env = _apply_env(args.run_id, state)
    paths = _paths(args.run_id)
    lock_file = paths["config"] / "serve.lock"
    pid_file = paths["config"] / "pids.json"
    if lock_file.exists() or pid_file.exists():
        raise SystemExit("该 run_id 已有运行锁；请先执行 stop，禁止重复启动")
    occupied = [port for port in _runtime_ports(state) if _port_open(port)]
    if occupied:
        raise SystemExit(f"测试端口已被占用，拒绝启动: {occupied}")
    owner_token = secrets.token_urlsafe(32)
    owner = {**_process_identity(os.getpid()), "command": list(sys.argv)}
    lock_payload = {
        "run_id": args.run_id,
        "owner_token": owner_token,
        "started_at": __import__("datetime").datetime.now().isoformat(),
        "owner": owner,
    }
    try:
        fd = os.open(lock_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        raise SystemExit("该 run_id 已被另一进程锁定，禁止重复启动")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(lock_payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    commands = [
        [sys.executable, "-m", "app.demo_support.mock_server", "--kind", "dify", "--port", str(state["dify_port"])],
        [sys.executable, "-m", "app.demo_support.mock_server", "--kind", "relay", "--port", str(state["relay_port"])],
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(state["app_port"])],
    ]
    processes: list[subprocess.Popen] = []
    try:
        for command in commands:
            processes.append(subprocess.Popen(command, cwd=WORKSPACE, env=env))
        process_entries = [owner]
        for command, process in zip(commands, processes):
            identity = _process_identity(process.pid)
            if not identity:
                raise RuntimeError(f"无法确认测试子进程身份: {process.pid}")
            process_entries.append({**identity, "command": command})
        _write_json(pid_file, {**lock_payload, "processes": process_entries})
        print(f"脱敏合成测试环境已启动: http://127.0.0.1:{state['app_port']}/ui-next/", flush=True)
        print("按 Ctrl+C 停止；核心 UI → FastAPI → SQLite，Dify/Relay 为真实回环 HTTP Mock。", flush=True)
        while True:
            for process in processes:
                code = process.poll()
                if code is not None:
                    raise SystemExit(f"子进程异常退出 pid={process.pid} code={code}")
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("正在停止测试服务...", flush=True)
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
        _remove_owned_runtime_files(args.run_id, owner_token)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Med-Audit 12 科室脱敏合成测试环境")
    sub = parser.add_subparsers(dest="command", required=True)
    create_parser = sub.add_parser("create", help="创建独立环境并确定性造数")
    create_parser.add_argument("--run-id", required=True)
    create_parser.add_argument("--profile", choices=["smoke", "showcase", "performance"], default="showcase")
    create_parser.add_argument("--seed", type=int, default=20260813)
    create_parser.add_argument("--app-port", type=int, default=18080)
    create_parser.add_argument("--dify-port", type=int, default=18081)
    create_parser.add_argument("--relay-port", type=int, default=18082)
    create_parser.set_defaults(func=create)
    for name, handler in (("status", status), ("serve", serve), ("stop", stop), ("verify-absent", verify_absent)):
        item = sub.add_parser(name)
        item.add_argument("--run-id", required=True)
        item.set_defaults(func=handler)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--run-id", required=True)
    verify_parser.add_argument("--allow-drift", action="store_true", help="允许交互后记录数增加，但基线数据不得减少")
    verify_parser.set_defaults(func=verify)
    destroy_parser = sub.add_parser("destroy", help="停止后整体销毁三个隔离目录")
    destroy_parser.add_argument("--run-id", required=True)
    destroy_parser.add_argument("--force", action="store_true")
    destroy_parser.set_defaults(func=destroy)
    reset_parser = sub.add_parser("reset")
    reset_parser.add_argument("--run-id", required=True)
    reset_parser.add_argument("--profile", choices=["smoke", "showcase", "performance"], default=None)
    reset_parser.add_argument("--seed", type=int, default=None)
    reset_parser.add_argument("--app-port", type=int, default=18080)
    reset_parser.add_argument("--dify-port", type=int, default=18081)
    reset_parser.add_argument("--relay-port", type=int, default=18082)
    reset_parser.set_defaults(func=reset)
    return parser


if __name__ == "__main__":
    parsed = build_parser().parse_args()
    parsed.func(parsed)
