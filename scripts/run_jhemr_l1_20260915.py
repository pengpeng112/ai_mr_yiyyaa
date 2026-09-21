# -*- coding: utf-8 -*-
"""048 T5 JHEMR L1 本地真机复跑（自足编排：双服务栈 + mock_client 全链 + 负向）。

栈（全部 127.0.0.1，单进程双 uvicorn 线程）：
- 18601 预检集成服务：demo fixtures + example_rules 引擎 + PrecheckProcessor +
  integration 五接口（Admin-Token+Actor 签名，与主服务 BFF 对齐）；
- 18602 主服务：app.main（隔离 DATA/CONFIG/LOG 目录、调度器关）+
  JHEMR 外部路由 /api/integrations/jhemr/*（HMAC 四件套，转发经 BFF 白名单）。

验收（对齐 09-11 L1 口径 + 048 T5 负向补充）：
[1] create 202；[2] get completed 计数守恒；[2b] 幂等复用 200 reused；
[3] view-ticket 200；[4] feedback viewed 200；[5] recheck 202 新 revision；
[degrade] 未签名 401 / 时钟偏差 401 / nonce 重放 401。
finally：双栈停止 + 端口释放核验；失败日志落 review/system-hardening-20260915/。

安全边界：零真实库/零生产；患者=纯 TEST 合成 fixtures；仅本机回环。
"""
from __future__ import annotations

import json
import socket
import sys
import threading
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PREARCHIVE_DIR = REPO_ROOT / "prearchive_service"
EVIDENCE_DIR = REPO_ROOT / "review" / "system-hardening-20260915"

PA_PORT = 18601
MAIN_PORT = 18602
PA_BASE = f"http://127.0.0.1:{PA_PORT}"
MAIN_BASE = f"http://127.0.0.1:{MAIN_PORT}"

ADMIN_TOKEN = "l1-admin-token"
SIGNING_SECRET = "l1-signing-secret"
JHEMR_CLIENT_ID = "l1-client"
JHEMR_HMAC_SECRET = "l1-hmac-secret"

POLL_TIMEOUT_SECONDS = 60.0


def _load_prearchive():
    if str(PREARCHIVE_DIR) not in sys.path:
        sys.path.insert(0, str(PREARCHIVE_DIR))


def build_prearchive_app():
    """预检集成服务（同 test_pa_jhemr_check 真实路径：fixtures+引擎+处理器）。"""
    _load_prearchive()
    from fastapi import FastAPI

    from prearchive.collectors import (
        HisCollector, JhemrCollector, LisCollector, PatientContextBuilder,
        SmCollector,
    )
    from prearchive.delivery_wiring import DeliveryGovernance, ResultEventEmitter
    from prearchive.engine import RuleEngine
    from prearchive.eval_store import EvalRunStore
    from prearchive.fixture_sources import build_demo_fixtures
    from prearchive.integration_api import create_integration_router
    from prearchive.issue_service import IssueService
    from prearchive.models import build_session_factory, build_sqlite_engine
    from prearchive.pusher import WeComPusher
    from prearchive.rule_repository import RuleRepository
    from prearchive.rules import load_rules, rules_version
    from prearchive.store import ResultRepository
    from prearchive.trigger import PrecheckProcessor

    class NullSender:
        def send(self, url, body, headers, timeout):
            return 200, "ok"

    rules_file = PREARCHIVE_DIR / "rules" / "example_rules.json"
    gateways = build_demo_fixtures()
    builder = PatientContextBuilder(
        jhemr=JhemrCollector(gateways["jhemr"]),
        his=HisCollector(gateways["his"]),
        sm=SmCollector(gateways["sm"]),
        lis=LisCollector(gateways["lis"]),
    )
    rules = load_rules(rules_file)
    engine = RuleEngine(rules, rule_version=rules_version(rules_file))
    # 050 T2：文件库替代 :memory:——uvicorn 下 BackgroundTasks 走 threadpool 线程，
    # :memory:+StaticPool 单连接会被 event-loop 线程的读事务交叉回滚，吞掉物化
    # 写入（实测 issues=0 而 evals=6）；文件库多连接独立事务，与 run_service
    # 生产形态一致。
    import tempfile
    pa_db_dir = Path(tempfile.mkdtemp(prefix="jhemr-l1-pa-"))
    session_factory = build_session_factory(
        build_sqlite_engine(str(pa_db_dir / "pa.sqlite3")))
    rule_repo = RuleRepository(session_factory)
    pusher = WeComPusher(push_config={"enabled": False},
                         secret_provider=lambda: "", sender=NullSender())
    processor = PrecheckProcessor(
        builder, engine, ResultRepository(session_factory), pusher,
        eval_store=EvalRunStore(session_factory),
        trigger_type="finished",
        issue_service=IssueService(session_factory),
        delivery_emitter=ResultEventEmitter(
            rule_repo, DeliveryGovernance(enabled=False)))
    config = {"admin_api": {"enabled": True, "admin_token": ADMIN_TOKEN,
                            "signing_secret": SIGNING_SECRET},
              "jhemr_integration": {"ticket_ttl_seconds": 300}}
    app = FastAPI()
    app.include_router(create_integration_router(
        config, session_factory, rule_repo, processor))
    return app, session_factory, pa_db_dir


def _start_server(app, port: int):
    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True,
                              name=f"l1-server-{port}")
    thread.start()
    return server, thread


def _wait_port(port: int, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.3)
    return False


def _port_released(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def run_l1() -> tuple[bool, list[str]]:
    lines: list[str] = []
    ok_all = True

    def log(line: str):
        print(line, flush=True)
        lines.append(line)

    # 端口预检：被占则拒绝启动（不杀未知进程）
    for port in (PA_PORT, MAIN_PORT):
        if not _port_released(port):
            log(f"[precheck] 端口 {port} 已被占用，拒绝启动（不杀未知进程）")
            return False, lines

    # 主服务隔离 env（必须在 import app.main 前设置）
    import tempfile
    tmp = tempfile.mkdtemp(prefix="jhemr-l1-")
    import os
    env_pairs = {
        "DATA_DIR": tmp, "CONFIG_DIR": str(Path(tmp) / "config"),
        "LOG_DIR": str(Path(tmp) / "logs"),
        "ENABLE_SCHEDULER": "false",
        # 050 T2：钉死应用库类型——防宿主环境残留 APP_DB_TYPE=oracle 时
        # init_db 连真实应用库（app/database.py 按 env 选库）
        "APP_DB_TYPE": "sqlite",
        "PREARCHIVE_ADMIN_ENABLED": "true",
        "PREARCHIVE_ADMIN_BASE_URL": PA_BASE,
        "PREARCHIVE_ADMIN_TOKEN": ADMIN_TOKEN,
        "PREARCHIVE_ADMIN_SECRET": SIGNING_SECRET,
        "JHEMR_INTEGRATION_ENABLED": "true",
        "JHEMR_INTEGRATION_CLIENT_ID": JHEMR_CLIENT_ID,
        "JHEMR_INTEGRATION_HMAC_SECRET": JHEMR_HMAC_SECRET,
    }
    original = {k: os.environ.get(k) for k in env_pairs}
    os.environ.update(env_pairs)
    Path(tmp, "config").mkdir(parents=True, exist_ok=True)
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    servers = []
    try:
        from app.main import app as main_app
        pa_app, pa_sf, pa_db_dir = build_prearchive_app()

        pa_server, pa_thread = _start_server(pa_app, PA_PORT)
        main_server, main_thread = _start_server(main_app, MAIN_PORT)
        servers = [(pa_server, pa_thread, PA_PORT), (main_server, main_thread, MAIN_PORT)]
        pa_up = _wait_port(PA_PORT)
        main_up = _wait_port(MAIN_PORT)
        log(f"[stack] prearchive: {pa_up} | main: {main_up}")
        if not (pa_up and main_up):
            return False, lines

        sys.path.insert(0, str(PREARCHIVE_DIR / "integration" / "jhemr"))
        from mock_client import JhemrClient, build_signature  # noqa: E402 —— 联调包纯标准库客户端

        client = JhemrClient(MAIN_BASE, JHEMR_CLIENT_ID, JHEMR_HMAC_SECRET)
        operator = {"id": "DOC77", "name": "Mock医生"}
        patient, visit = "TEST0002", "1"
        submission_id = f"L1-{uuid.uuid4().hex[:8]}"
        check_path = "/api/integrations/jhemr/submission-checks"

        def submission_body(request_id: str) -> dict:
            return {"request_id": request_id, "patient_id": patient,
                    "visit_number": visit, "operator": operator,
                    "submission_id": submission_id}

        # [1] create
        created = client.create_submission_check(
            patient_id=patient, visit_number=visit,
            submission_id=submission_id, operator=operator)
        log(f"[1] create: {created['status']} check= {str((created['json'] or {}).get('check_id', ''))[:12]} …")
        if created["status"] != 202:
            ok_all = False
        check_id = (created["json"] or {}).get("check_id")

        # [2] poll get（completed + 计数守恒 + D-J1 契约）
        # 050 v1.1 T2 判据：终态首查 issues 必须等于期望 key 集（本 run fail
        # evals 按 issue_key_for 口径物化），1s 后稳定读亦须相等——旧判据
        # 「非空即稳」在部分物化（如 2/4 条）时会假通过，已废弃。
        from sqlalchemy import select as _sa_select

        from prearchive.closed_loop_models import RuleEvalRow
        from prearchive.issue_service import issue_key_for
        result = client.poll_check(check_id, timeout_seconds=POLL_TIMEOUT_SECONDS)
        first_keys = {i.get("issue_key") for i in (result.get("issues") or [])}
        with pa_sf() as _session:
            _evals = _session.execute(_sa_select(RuleEvalRow).where(
                RuleEvalRow.run_id == check_id)).scalars().all()
        expected_keys = {
            issue_key_for(patient, visit, ev.rule_id,
                          str(ev.event_instance_id or ""))
            for ev in _evals if ev.status == "fail" and not ev.is_trial}
        time.sleep(1.0)   # 稳定读：D-J1 修复后 issues 不应再变化
        stable = client.get_check(check_id).get("json") or {}
        stable_keys = {i.get("issue_key") for i in (stable.get("issues") or [])}
        result = stable
        summary = result.get("summary") or {}
        log(f"[2] get: status= {result.get('status')} trigger= "
            f"{result.get('trigger_type')} | instances= "
            f"{summary.get('rule_instance_count')}"
            f" pass= {summary.get('pass_count')} fail= {summary.get('fail_count')}"
            f" unknown= {summary.get('unknown_count')}"
            f" excluded= {summary.get('excluded_count')}"
            f" summary.status= {summary.get('status')}"
            f" | issues= {len(result.get('issues') or [])}"
            f" (expected= {len(expected_keys)} first= {len(first_keys)}"
            f" stable= {len(stable_keys)})")
        if result.get("status") != "completed" or summary.get("status") != "fail":
            ok_all = False
        issues = result.get("issues") or []
        if not issues:
            ok_all = False
        if not expected_keys:
            log("[2] D-J1 契约: 期望集为空——fixture 应产生 fail（异常）")
            ok_all = False
        elif first_keys != expected_keys or stable_keys != expected_keys:
            log(f"[2] D-J1 契约 FAIL: expected={sorted(expected_keys)} "
                f"first={sorted(first_keys)} stable={sorted(stable_keys)}")
            ok_all = False
        else:
            log("[2] D-J1 契约: first==stable==expected ✓")

        # [2b] 幂等复用（同 submission_id → 200 reused）
        again = client.create_submission_check(
            patient_id=patient, visit_number=visit,
            submission_id=submission_id, operator=operator)
        log(f"[2b] idempotent reuse: {again.get('status')} reused= "
            f"{(again.get('json') or {}).get('reused')}")
        if again.get("status") != 200:
            ok_all = False

        # [3] view ticket
        ticket = client.create_view_ticket(
            patient_id=patient, visit_number=visit, operator_id=operator["id"])
        log(f"[3] ticket: {ticket['status']} nonce= "
            f"{str((ticket['json'] or {}).get('ticket_nonce', ''))[:12]} …")
        if ticket["status"] != 200:
            ok_all = False

        # [4] feedback viewed
        if issues:
            target = issues[0]
            feedback = client.issue_feedback(
                issue_id=target["issue_id"], action="viewed", operator=operator,
                expect_issue_version=target.get("issue_version", 1))
            log(f"[4] feedback(viewed): {feedback['status']} → "
                f"{(feedback['json'] or {}).get('status')}")
            if feedback["status"] != 200:
                ok_all = False
        else:
            log("[4] feedback(viewed): SKIPPED（issues 稳定态为空——异常）")
            ok_all = False

        # [5] recheck（同锚点新 revision；view 回读确认）
        rechecked = client.recheck(patient_id=patient, visit_number=visit,
                                   operator=operator, reason="L1 复检")
        body = rechecked["json"] or {}
        view_after = {}
        if rechecked["status"] == 202:
            view_after = client.poll_check(
                body.get("check_id") or check_id,
                timeout_seconds=POLL_TIMEOUT_SECONDS) or {}
        log(f"[5] recheck: {rechecked['status']} | view: revision= "
            f"{view_after.get('run_revision')} trigger= "
            f"{view_after.get('trigger_type')} issues= "
            f"{len(view_after.get('issues') or [])}")
        if rechecked["status"] != 202:
            ok_all = False
        elif view_after.get("trigger_type") != "manual_recheck":
            ok_all = False

        # [degrade] 未签名 / 时钟偏差 / nonce 重放 → 401
        import urllib.request
        import urllib.error

        def raw_post(path: str, body: dict, headers: dict) -> int:
            req = urllib.request.Request(
                MAIN_BASE + path, data=json.dumps(body, ensure_ascii=False)
                .encode("utf-8"),
                headers={"Content-Type": "application/json", **headers},
                method="POST")
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.status
            except urllib.error.HTTPError as exc:
                return exc.code

        def signed_headers(path: str, raw: bytes, timestamp: str, nonce: str) -> dict:
            return {
                "X-Jhemr-Client-Id": JHEMR_CLIENT_ID,
                "X-Jhemr-Timestamp": timestamp,
                "X-Jhemr-Nonce": nonce,
                "X-Jhemr-Signature": build_signature(
                    JHEMR_HMAC_SECRET, JHEMR_CLIENT_ID, "POST", path, raw,
                    timestamp, nonce),
            }

        unsigned = raw_post(check_path, submission_body("l1-unsigned"), {})
        log(f"[degrade] unsigned → {unsigned}")
        if unsigned != 401:
            ok_all = False

        stale_raw = json.dumps(submission_body("l1-stale"),
                               ensure_ascii=False).encode("utf-8")
        stale_headers = signed_headers(
            check_path, stale_raw, str(int(time.time()) - 4000),
            uuid.uuid4().hex)   # 超出 ±300s 偏差窗
        stale = raw_post(check_path, submission_body("l1-stale"), stale_headers)
        log(f"[degrade] stale timestamp → {stale}")
        if stale != 401:
            ok_all = False

        replay_raw = json.dumps(submission_body("l1-replay"),
                                ensure_ascii=False).encode("utf-8")
        replay_nonce = uuid.uuid4().hex
        replay_headers = signed_headers(check_path, replay_raw,
                                        str(int(time.time())), replay_nonce)
        first = raw_post(check_path, submission_body("l1-replay"), replay_headers)
        replay = raw_post(check_path, submission_body("l1-replay"), replay_headers)
        log(f"[degrade] nonce replay: first= {first} replay → {replay}")
        if replay != 401:
            ok_all = False

        log("L1-VERIFY: " + ("ALL PASS" if ok_all else "FAILURES PRESENT"))
        return ok_all, lines
    finally:
        for server, thread, port in servers:
            server.should_exit = True
        deadline = time.monotonic() + 15
        for server, thread, port in servers:
            thread.join(timeout=max(0.1, deadline - time.monotonic()))
        released = {port: _port_released(port) for _, _, port in servers}
        log(f"[stack] stopped, ports released: {released}")
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        import shutil
        shutil.rmtree(pa_db_dir, ignore_errors=True)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="JHEMR L1 真机双栈验收")
    parser.add_argument(
        "--out-dir", default=str(EVIDENCE_DIR),
        help="证据输出目录（默认=048 证据目录；重跑建议另指新目录，"
             "避免覆盖旧日志——050 T2 起支持）")
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ok, lines = run_l1()
    (out_dir / "jhemr-l1.log").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    print(f"[l1] evidence -> {out_dir / 'jhemr-l1.log'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
