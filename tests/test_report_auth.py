"""报告认证与权限测试。"""
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import User, Role, Department, PushLog


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _seed(db):
    admin_role = Role(name="admin", description="")
    dept_mgr_role = Role(name="dept_manager", description="")
    db.add_all([admin_role, dept_mgr_role])
    db.flush()

    dept_a = Department(name="心内科", code="xnk")
    dept_b = Department(name="骨科", code="gk")
    db.add_all([dept_a, dept_b])
    db.flush()

    admin_user = User(username="admin", password_hash="...", full_name="管理员", role_id=admin_role.id, dept_id=dept_a.id)
    mgr_user = User(username="mgr", password_hash="...", full_name="主任", role_id=dept_mgr_role.id, dept_id=dept_a.id)
    db.add_all([admin_user, mgr_user])
    db.flush()

    log_xnk = PushLog(patient_id="p1", patient_name="患者心内", dept="心内科", trigger_type="manual",
                      push_time=datetime.now(), query_date="2026-06-01", status="success", inconsistency=0,
                      risk_score=0, elapsed_ms=0, retry_count=0)
    log_gk = PushLog(patient_id="p2", patient_name="患者骨科", dept="骨科", trigger_type="manual",
                     push_time=datetime.now(), query_date="2026-06-01", status="success", inconsistency=0,
                     risk_score=0, elapsed_ms=0, retry_count=0)
    db.add_all([log_xnk, log_gk])
    db.commit()
    return admin_user, mgr_user, log_xnk, log_gk


def test_issue_print_token_own_dept(mocker):
    """本科室用户可签发本科室 log 的 print token。"""
    from app.services.report_token import generate_report_token, verify_report_token
    token = generate_report_token(log_id=1, user_id=100, ttl=60)
    assert token
    assert verify_report_token(token, 1) is True
    assert verify_report_token(token, 2) is False


def test_verify_report_token_expired(mocker):
    """过期 token 应拒绝。"""
    from app.services.report_token import generate_report_token, verify_report_token
    token = generate_report_token(log_id=5, user_id=200, ttl=-1)
    assert verify_report_token(token, 5) is False


def test_verify_report_token_wrong_log_id():
    """跨 log_id 的 token 拒绝。"""
    from app.services.report_token import generate_report_token, verify_report_token
    token = generate_report_token(log_id=10, user_id=1, ttl=300)
    assert verify_report_token(token, 10) is True
    assert verify_report_token(token, 11) is False


def test_verify_report_token_invalid_format():
    """非法 token 拒绝。"""
    from app.services.report_token import verify_report_token
    assert verify_report_token("", 1) is False
    assert verify_report_token("abc", 1) is False
    assert verify_report_token("1.2", 1) is False
    assert verify_report_token("x.y.z", 1) is False


# ---- 041 T7：生产门禁复用 _resolve_runtime_environment（ENVIRONMENT/APP_ENV/冲突） ----

def _clear_secret_env(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    # 屏蔽本地 config.json 的 encryption.report_token_secret，只测 env 路径
    monkeypatch.setattr("app.config.load_config", lambda: {})


def test_report_token_production_gate_reads_environment(monkeypatch):
    """仅 ENVIRONMENT=production（无 APP_ENV）且无密钥 → raise（023 P1-01 残留修复）。"""
    _clear_secret_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "production")
    from app.services.report_token import _secret
    with pytest.raises(RuntimeError, match="production"):
        _secret()


def test_report_token_production_gate_reads_legacy_app_env(monkeypatch):
    """仅 APP_ENV=prod（别名归一为 production）且无密钥 → raise。"""
    _clear_secret_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "prod")
    from app.services.report_token import _secret
    with pytest.raises(RuntimeError, match="production"):
        _secret()


def test_report_token_env_conflict_raises_from_resolver(monkeypatch):
    """ENVIRONMENT 与 APP_ENV 冲突 → 由 _resolve_runtime_environment 拒绝。"""
    _clear_secret_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("APP_ENV", "development")
    from app.services.report_token import _secret
    with pytest.raises(RuntimeError, match="冲突"):
        _secret()


def test_report_token_development_fallback_still_works(monkeypatch):
    """development 环境无密钥 → 开发 fallback 不变。"""
    _clear_secret_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "development")
    from app.services.report_token import _secret
    assert _secret() == "dev-fallback-report-key"


def test_apply_push_log_visibility_restricts_other_dept():
    """非管理员用户不能看他科室的 PushLog。"""
    from app.services.dept_visibility import apply_push_log_visibility

    db = _make_db()
    _, mgr, _, _ = _seed(db)

    q = apply_push_log_visibility(db.query(PushLog), mgr, db)
    results = q.all()
    depts = [r.dept for r in results]
    assert "心内科" in depts
    assert "骨科" not in depts
    assert len(results) == 1
