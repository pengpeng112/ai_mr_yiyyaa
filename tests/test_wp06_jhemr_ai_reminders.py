"""064-WP06：JHEMR 提交前 AI 高危提醒（路线 B 主推）+ 规则策略配置验收用例。

覆盖任务书 §六：
1. jhemr_reminder_policy 保存、缺省兼容（旧配置缺失自动补全 enabled=False 安全默认）；
2. 非法枚举（delivery_mode/severities/trigger_stage）校验拒绝（FastAPI 422）；
3. GET /api/integrations/jhemr/ai-reminders：总开关关闭 → 503（复用 _verify_request）；
4. 二级开关 jhemr_ai_reminder.enabled=false → 200 + disabled=true；
5. 开启后仅返回 policy.enabled=True 且 delivery_mode in (pull_api, both) 且
   匹配严重度的高危未闭环提醒（含 block_submit/message 模板渲染）；
6. exclude_reviewed=True 时已复核/已整改闭环记录自动排除；
7. 查询 defer() 了 4 个 CLOB 列（SQL 文本不含大字段列名）。
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import (
    AuditConclusion,
    AuditDimensionResult,
    ExportAuditLog,
    PushLog,
    QCFeedback,
    Role,
    User,
)
from app.routers import audit_types as audit_types_router
from app.routers import jhemr_integration
from app.routers.jhemr_integration import build_signature
from app.schemas import AuditTypeConfig
from app.services.audit_type_registry import AuditTypeRegistry

CLIENT_ID = "jhemr-wp06"
SECRET = "wp06-hmac-secret"


def _policy(**overrides) -> dict:
    base = {
        "enabled": True,
        "delivery_mode": "pull_api",
        "severities": ["high"],
        "trigger_stage": "before_submit",
        "block_submit": False,
        "exclude_reviewed": True,
        "message_template": "【AI内涵质控提醒】发现{severity}风险（{audit_type_name}）：{summary}",
    }
    base.update(overrides)
    return base


def _audit_type_dict(code: str = "progress_vs_nursing", *, policy: dict | None = None,
                     enabled: bool = True) -> dict:
    return {
        "code": code,
        "name": "病程与护理一致性",
        "enabled": enabled,
        "sort_order": 10,
        "sources": {
            "primary": {
                "type": "sql",
                "query_sql": "SELECT 1 FROM dual",
                "field_mapping": {"patient_id": "PATIENT_ID", "visit_number": "VISIT_NO"},
                "required": True,
            },
        },
        "payload": {"builder": "generic_multi_source"},
        "dify": {
            "base_url": "http://example.com/v1",
            "workflow_input_variable": "mr_txt",
            "timeout_seconds": 90,
        },
        "response": {"parse_strategy": "hybrid"},
        "display": {"summary_blocks": [], "detail_blocks": []},
        **({"jhemr_reminder_policy": policy} if policy is not None else {}),
    }


# ---- 用例 1：保存与缺省兼容 ----

def test_reminder_policy_save_and_default_compat(monkeypatch):
    cfg_with = AuditTypeConfig.model_validate(_audit_type_dict(policy=_policy()))
    assert cfg_with.jhemr_reminder_policy.enabled is True
    assert cfg_with.jhemr_reminder_policy.delivery_mode == "pull_api"
    assert cfg_with.jhemr_reminder_policy.severities == ["high"]

    # 旧配置缺失该键 → 自动补全安全默认（enabled=False），读取不报错
    cfg_without = AuditTypeConfig.model_validate(_audit_type_dict(policy=None))
    assert cfg_without.jhemr_reminder_policy.enabled is False
    assert cfg_without.jhemr_reminder_policy.block_submit is False
    assert cfg_without.jhemr_reminder_policy.exclude_reviewed is True
    assert "{severity}" in cfg_without.jhemr_reminder_policy.message_template

    # save 落盘后读回策略不丢失（内存 config 往返）。save_config/load_config 均被
    # monkeypatch 拦截——严禁在单测中写入真实 config/config.json（回归保护）。
    from app.services import audit_type_registry as atr_module

    state = {"config": {"audit_types": []}}
    monkeypatch.setattr(atr_module, "save_config", lambda data: state.update(config=data))
    monkeypatch.setattr(atr_module, "load_config", lambda: state["config"])
    registry = AuditTypeRegistry(config=state["config"])
    saved = registry.save(cfg_with, existing_code="progress_vs_nursing")
    assert saved.jhemr_reminder_policy.enabled is True
    reloaded = AuditTypeRegistry(config=state["config"]).get("progress_vs_nursing")
    assert reloaded.jhemr_reminder_policy.delivery_mode == "pull_api"
    # 拦截生效：真实配置文件未被单测触碰
    assert len(state["config"].get("audit_types") or []) == 1


def test_reminder_policy_invalid_enum_rejected():
    # 非法 delivery_mode
    with pytest.raises(Exception):
        AuditTypeConfig.model_validate(_audit_type_dict(policy=_policy(delivery_mode="weixin")))
    # severities 越界值
    with pytest.raises(Exception):
        AuditTypeConfig.model_validate(_audit_type_dict(policy=_policy(severities=["critical"])))
    # 非法 trigger_stage
    with pytest.raises(Exception):
        AuditTypeConfig.model_validate(_audit_type_dict(policy=_policy(trigger_stage="after_lunch")))
    # 空 severities 回退默认高危（不报错）
    fallback = AuditTypeConfig.model_validate(_audit_type_dict(policy=_policy(severities=[])))
    assert fallback.jhemr_reminder_policy.severities == ["high"]


# ---- ai-reminders 接口 fixture ----

@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False)()

    admin_role = Role(name="admin", description="管理员")
    db.add(admin_role)
    db.flush()
    admin = User(username="wp06_admin", password_hash="x", full_name="管理员", role_id=admin_role.id)
    db.add(admin)
    db.commit()

    push_time = datetime(2026, 11, 20, 9, 15, 0)
    # L1：高危、未复核、progress_vs_nursing（应命中提醒）
    db.add(PushLog(
        patient_id="00985003", visit_number="1", status="success", pushed_flag=1,
        query_date="2026-11-20", trigger_type="manual", source_record_key="WP06-L1",
        audit_type_code="progress_vs_nursing", severity="high", push_time=push_time,
        dept="骨科一病区",
    ))
    # L2：高危但已复核（exclude_reviewed=True 应排除）
    db.add(PushLog(
        patient_id="00985003", visit_number="1", status="success", pushed_flag=1,
        query_date="2026-11-20", trigger_type="manual", source_record_key="WP06-L2",
        audit_type_code="progress_vs_nursing", severity="high",
        push_time=datetime(2026, 11, 19, 8, 0, 0), reviewed_flag=1, dept="骨科一病区",
    ))
    # L3：高危、未复核，但 audit_type 开了提醒但 delivery_mode=fileverify_write（路线 A 不走拉取）
    db.add(PushLog(
        patient_id="00985003", visit_number="1", status="success", pushed_flag=1,
        query_date="2026-11-20", trigger_type="manual", source_record_key="WP06-L3",
        audit_type_code="jyjc_vs_bcnursing", severity="high",
        push_time=datetime(2026, 11, 19, 10, 0, 0), dept="骨科一病区",
    ))
    # L4：中危（不在 severities=["high"] 内，不提醒）
    db.add(PushLog(
        patient_id="00985003", visit_number="1", status="success", pushed_flag=1,
        query_date="2026-11-20", trigger_type="manual", source_record_key="WP06-L4",
        audit_type_code="progress_vs_nursing", severity="medium",
        push_time=datetime(2026, 11, 19, 11, 0, 0), dept="骨科一病区",
    ))
    # L5：高危、未复核、另一类型 fileverify_write——同 L3 通道过滤
    db.add(PushLog(
        patient_id="00985003", visit_number="2", status="success", pushed_flag=1,
        query_date="2026-11-20", trigger_type="manual", source_record_key="WP06-L5",
        audit_type_code="jyjc_vs_bcnursing", severity="high",
        push_time=datetime(2026, 11, 19, 12, 0, 0), dept="骨科一病区",
    ))
    db.commit()

    # 结论与维度（L1 有维度高危问题 + 总体结论）
    l1 = db.query(PushLog).filter(
        PushLog.audit_type_code == "progress_vs_nursing",
        PushLog.push_time == push_time).first()
    db.add(AuditConclusion(
        push_log_id=l1.id, severity="high", alert_level="red",
        overall_conclusion="病程与护理记录存在矛盾", overall_qc_summary="术后首次病程记录时间与护理记录不一致",
    ))
    db.add(AuditDimensionResult(
        push_log_id=l1.id, dimension="手术相关记录时限", dimension_code="surgery_time",
        status="fail", severity="high", issue_summary="术后首次病程记录超时 6 小时完成",
        recommendation="请医师补齐术后首次病程记录",
    ))
    db.add(AuditDimensionResult(
        push_log_id=l1.id, dimension="护理记录一致性", dimension_code="nursing_consistency",
        status="fail", severity="medium", issue_summary="护理记录出入量与病程不一致",
    ))
    db.commit()

    app = FastAPI()
    app.include_router(jhemr_integration.router, prefix="/api")
    app.include_router(audit_types_router.router, prefix="/api/audit-types")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[audit_types_router.get_current_user] = lambda: admin

    config = {
        "jhemr_ai_reminder": {"enabled": True},
        "audit_types": [
            _audit_type_dict(policy=_policy()),
            _audit_type_dict("jyjc_vs_bcnursing", policy=_policy(delivery_mode="fileverify_write")),
        ],
    }
    monkeypatch.setattr("app.config.load_config", lambda: config)
    monkeypatch.setenv("JHEMR_INTEGRATION_ENABLED", "true")
    monkeypatch.setenv("JHEMR_INTEGRATION_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("JHEMR_INTEGRATION_HMAC_SECRET", SECRET)

    captured_sql: list[str] = []

    def _before_cursor(conn, cursor, statement, parameters, context, executemany):
        captured_sql.append(statement)

    event.listen(engine, "before_cursor_execute", _before_cursor)

    yield db, app, config, captured_sql
    event.remove(engine, "before_cursor_execute", _before_cursor)
    db.close()


def _client(app) -> TestClient:
    return TestClient(app)


def _sign(method: str, path: str, body: bytes = b""):
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    return {
        "X-Jhemr-Client-Id": CLIENT_ID,
        "X-Jhemr-Timestamp": timestamp,
        "X-Jhemr-Nonce": nonce,
        "X-Jhemr-Signature": build_signature(SECRET, CLIENT_ID, method, path, body, timestamp, nonce),
    }


REMINDERS_PATH = "/api/integrations/jhemr/ai-reminders"


# ---- 用例 3：总开关关闭 → 503 ----

def test_ai_reminders_disabled_integration_returns_503(monkeypatch):
    monkeypatch.delenv("JHEMR_INTEGRATION_ENABLED", raising=False)
    app = FastAPI()
    app.include_router(jhemr_integration.router, prefix="/api")
    resp = TestClient(app).get(REMINDERS_PATH, params={"patient_id": "00985003"})
    assert resp.status_code == 503


def test_ai_reminders_bad_signature_401(env):
    db, app, config, _ = env
    headers = _sign("GET", REMINDERS_PATH)
    headers["X-Jhemr-Signature"] = "0" * 64
    resp = _client(app).get(REMINDERS_PATH, params={"patient_id": "00985003"}, headers=headers)
    assert resp.status_code == 401


# ---- 用例 4：二级开关关闭 → 200 + disabled=true ----

def test_ai_reminders_switch_off_returns_disabled(env):
    db, app, config, _ = env
    config["jhemr_ai_reminder"] = {"enabled": False}
    resp = _client(app).get(REMINDERS_PATH, params={"patient_id": "00985003"},
                            headers=_sign("GET", REMINDERS_PATH))
    assert resp.status_code == 200
    body = resp.json()
    assert body["disabled"] is True
    assert body["has_reminders"] is False
    assert body["items"] == []


# ---- 用例 5：开启后仅返回符合策略的高危未闭环提醒 ----

def test_ai_reminders_returns_open_high_severity_items(env):
    db, app, config, _ = env
    resp = _client(app).get(REMINDERS_PATH, params={"patient_id": "00985003", "visit_id": 1},
                            headers=_sign("GET", REMINDERS_PATH))
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_reminders"] is True
    assert body["count"] == 1
    assert body["delivery_mode"] == "pull_api"
    items = body["items"]
    assert len(items) == 1
    item = items[0]
    assert item["audit_type_code"] == "progress_vs_nursing"
    assert item["severity"] == "high"
    assert item["severity_label"] == "高危"
    assert item["block_submit"] is False
    assert item["push_time"] == "2026-11-20T09:15:00"
    # message 模板渲染（severity/audit_type_name/summary 占位符）
    assert item["message"].startswith("【AI内涵质控提醒】发现高危风险（病程与护理一致性）：")
    assert "术后首次病程记录超时" in item["message"]
    assert "/ui-next/#/quality/patient-detail?patient_id=00985003" in item["detail_path"]
    # fileverify_write 通道（jyjc_vs_bcnursing）不走拉取：无该类型 item
    assert all(i["audit_type_code"] != "jyjc_vs_bcnursing" for i in items)


def test_ai_reminders_block_submit_flag(env):
    db, app, config, _ = env
    config["audit_types"][0]["jhemr_reminder_policy"]["block_submit"] = True
    resp = _client(app).get(REMINDERS_PATH, params={"patient_id": "00985003"},
                            headers=_sign("GET", REMINDERS_PATH))
    body = resp.json()
    assert body["should_block"] is True
    assert body["items"][0]["block_submit"] is True


# ---- 用例 6：exclude_reviewed=True 排除已复核/已整改闭环 ----

def test_ai_reminders_exclude_reviewed_and_closed(env):
    db, app, config, _ = env
    resp = _client(app).get(REMINDERS_PATH, params={"patient_id": "00985003"},
                            headers=_sign("GET", REMINDERS_PATH))
    body = resp.json()
    # L2（reviewed_flag=1）不出现在结果中
    log_ids = [i["log_id"] for i in body["items"]]
    l2 = db.query(PushLog).filter(PushLog.reviewed_flag == 1).first()
    assert l2.id not in log_ids
    # 已整改闭环记录排除
    l1 = db.query(PushLog).filter(
        PushLog.audit_type_code == "progress_vs_nursing",
        PushLog.push_time == datetime(2026, 11, 20, 9, 15, 0)).first()
    db.add(QCFeedback(push_log_id=l1.id, dept_id=1, severity="high", status="rectified", created_by=1))
    db.commit()
    resp2 = _client(app).get(REMINDERS_PATH, params={"patient_id": "00985003"},
                             headers=_sign("GET", REMINDERS_PATH))
    body2 = resp2.json()
    assert body2["has_reminders"] is False
    assert body2["items"] == []
    assert l1.id not in [i["log_id"] for i in body2["items"]]


# ---- 用例 7a：无提醒返回空；7b：defer 4 CLOB ----

def test_ai_reminders_empty_when_no_policy_enabled(env):
    db, app, config, _ = env
    config["audit_types"] = [_audit_type_dict(policy=_policy(enabled=False))]
    resp = _client(app).get(REMINDERS_PATH, params={"patient_id": "00985003"},
                            headers=_sign("GET", REMINDERS_PATH))
    body = resp.json()
    assert body["has_reminders"] is False
    assert body["should_block"] is False
    assert body["items"] == []
    assert "disabled" not in body  # 开关已开但无规则开启（与 disabled 区分）


def test_ai_reminders_query_defers_all_clob_columns(env):
    db, app, config, captured_sql = env
    captured_sql.clear()
    resp = _client(app).get(REMINDERS_PATH, params={"patient_id": "00985003"},
                            headers=_sign("GET", REMINDERS_PATH))
    assert resp.status_code == 200
    push_log_sql = [s for s in captured_sql if "push_log" in s]
    assert push_log_sql, "应存在 push_logs 查询"
    blob_columns = ("mr_text", "ai_result", "request_json", "response_json")
    for statement in push_log_sql:
        for column in blob_columns:
            assert column not in statement.lower(), f"SELECT 不应加载 CLOB 列 {column}"


# ---- audit-types API：非法枚举 → 422（PUT 合并路径） ----

def test_update_audit_type_invalid_policy_returns_422(monkeypatch):
    class _Db:
        def query(self, _model):
            return self

        def filter(self, *_args, **_kwargs):
            return self

        def first(self):
            return SimpleNamespace(name="admin")

    # save_config/load_config 全拦截——单测严禁写入真实 config/config.json
    from app.services import audit_type_registry as atr_module

    state = {"config": {"audit_types": [_audit_type_dict(policy=_policy())]}}
    monkeypatch.setattr(atr_module, "save_config", lambda data: state.update(config=data))
    monkeypatch.setattr(atr_module, "load_config", lambda: state["config"])
    registry = AuditTypeRegistry(config=state["config"])
    monkeypatch.setattr(audit_types_router, "AuditTypeRegistry", lambda: registry)
    app = FastAPI()
    app.include_router(audit_types_router.router, prefix="/api/audit-types")
    app.dependency_overrides[audit_types_router.get_current_user] = lambda: SimpleNamespace(id=1, role_id=1)
    app.dependency_overrides[audit_types_router.get_db] = lambda: _Db()
    client = TestClient(app)
    resp = client.put("/api/audit-types/progress_vs_nursing",
                      json={"jhemr_reminder_policy": {"delivery_mode": "weixin"}})
    assert resp.status_code == 422
    resp2 = client.put("/api/audit-types/progress_vs_nursing",
                       json={"jhemr_reminder_policy": {"severities": ["critical"]}})
    assert resp2.status_code == 422
    # 合法更新成功（body 不带完整配置时合并现值）
    resp3 = client.put("/api/audit-types/progress_vs_nursing",
                       json={"jhemr_reminder_policy": _policy()})
    assert resp3.status_code == 200
    assert resp3.json()["jhemr_reminder_policy"]["enabled"] is True


def test_ai_reminders_per_policy_exclude_reviewed_mixed(env):
    """回归保护（P1-5）：两策略 exclude_reviewed 一真一假时按各自策略分别过滤已复核记录。"""
    db, app, config, _ = env
    config["audit_types"] = [
        _audit_type_dict("progress_vs_nursing", policy=_policy(exclude_reviewed=True)),
        _audit_type_dict("policy_keep_rev", policy=_policy(exclude_reviewed=False)),
    ]
    # 为 policy_keep_rev 新增一条已复核高危记录（策略允许返回已复核）
    rev_keep = PushLog(
        patient_id="00985003", visit_number="1", status="success", pushed_flag=1,
        query_date="2026-11-20", trigger_type="manual", source_record_key="WP06-KEEP-REV",
        audit_type_code="policy_keep_rev", severity="high",
        push_time=datetime(2026, 11, 20, 10, 0, 0), reviewed_flag=1, dept="骨科一病区",
    )
    db.add(rev_keep)
    db.commit()

    resp = _client(app).get(
        REMINDERS_PATH, params={"patient_id": "00985003", "visit_id": "1"},
        headers=_sign("GET", REMINDERS_PATH),
    )
    assert resp.status_code == 200
    returned_ids = {item["log_id"] for item in resp.json()["items"]}
    # policy_keep_rev 的已复核记录保留
    assert rev_keep.id in returned_ids
    # progress_vs_nursing 的已复核记录（L2）仍按其 exclude_reviewed=True 被排除
    l2 = db.query(PushLog).filter(
        PushLog.audit_type_code == "progress_vs_nursing", PushLog.reviewed_flag == 1
    ).first()
    assert l2 is not None and l2.id not in returned_ids
