"""科室可见性服务测试。"""
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import User, Role, Department, RoleDepartment, PushLog


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def _seed(db):
    admin_role = Role(name="admin", description="管理员")
    dept_mgr_role = Role(name="dept_manager", description="科室主任")
    db.add_all([admin_role, dept_mgr_role])
    db.flush()

    dept_a = Department(name="心内科", code="xnk")
    dept_b = Department(name="骨科", code="gk")
    db.add_all([dept_a, dept_b])
    db.flush()

    admin_user = User(username="admin", password_hash="...", full_name="管理员", role_id=admin_role.id, dept_id=dept_a.id)
    mgr_user = User(username="mgr", password_hash="...", full_name="主任", role_id=dept_mgr_role.id, dept_id=dept_a.id)
    no_dept_user = User(username="nodpt", password_hash="...", full_name="无科室", role_id=dept_mgr_role.id, dept_id=None)
    db.add_all([admin_user, mgr_user, no_dept_user])
    db.flush()

    db.add(RoleDepartment(role_id=dept_mgr_role.id, dept_id=dept_a.id))
    db.add(RoleDepartment(role_id=dept_mgr_role.id, dept_id=dept_b.id))
    db.commit()
    return admin_user, mgr_user, no_dept_user


def test_is_admin():
    from app.services.dept_visibility import is_admin_user
    db = _make_db()
    admin, mgr, _ = _seed(db)
    assert is_admin_user(db, admin) is True
    assert is_admin_user(db, mgr) is False


def test_visible_dept_names_admin_returns_none():
    from app.services.dept_visibility import visible_dept_names
    db = _make_db()
    admin, _, _ = _seed(db)
    assert visible_dept_names(db, admin) is None


def test_visible_dept_names_mgr_multiple_depts():
    from app.services.dept_visibility import visible_dept_names
    db = _make_db()
    _, mgr, _ = _seed(db)
    names = visible_dept_names(db, mgr)
    assert set(names) == {"心内科", "骨科"}


def test_visible_dept_names_no_dept_user_empty():
    """用户无科室且角色无 RoleDepartment 时返回空列表。"""
    from app.services.dept_visibility import visible_dept_names
    db = _make_db()
    _, _, nodpt = _seed(db)
    # 将 nodpt 的角色改为新建的空角色，确保无科室可见
    from app.models import Role as _Role
    empty_role = _Role(name="no_access", description="")
    db.add(empty_role)
    db.flush()
    nodpt.role_id = empty_role.id
    db.commit()
    names = visible_dept_names(db, nodpt)
    assert names == []


def test_apply_push_log_visibility_admin_no_filter():
    from app.services.dept_visibility import apply_push_log_visibility
    db = _make_db()
    admin, _, _ = _seed(db)
    q = apply_push_log_visibility(db.query(PushLog), admin, db)
    assert q is not None


def test_apply_push_log_visibility_mgr_filters_by_dept():
    from app.services.dept_visibility import apply_push_log_visibility
    db = _make_db()
    _, mgr, _ = _seed(db)
    log_xnk = PushLog(patient_id="p1", patient_name="患者1", dept="心内科", trigger_type="manual",
                      push_time=datetime.now(), query_date="2026-06-01", status="success", inconsistency=0,
                      risk_score=0, elapsed_ms=0, retry_count=0)
    log_gk = PushLog(patient_id="p2", patient_name="患者2", dept="骨科", trigger_type="manual",
                     push_time=datetime.now(), query_date="2026-06-01", status="success", inconsistency=0,
                     risk_score=0, elapsed_ms=0, retry_count=0)
    db.add_all([log_xnk, log_gk])
    db.commit()

    q = apply_push_log_visibility(db.query(PushLog), mgr, db)
    results = q.all()
    names = [r.dept for r in results]
    assert "心内科" in names
    assert "骨科" in names
    assert len(results) == 2


def test_apply_push_log_visibility_no_dept_user_empty():
    from app.services.dept_visibility import apply_push_log_visibility
    db = _make_db()
    _, _, nodpt = _seed(db)
    from app.models import Role as _Role
    empty_role = _Role(name="no_access_apply", description="")
    db.add(empty_role)
    db.flush()
    nodpt.role_id = empty_role.id
    db.commit()
    log = PushLog(patient_id="p1", patient_name="患者1", dept="心内科", trigger_type="manual",
                  push_time=datetime.now(), query_date="2026-06-01", status="success", inconsistency=0,
                  risk_score=0, elapsed_ms=0, retry_count=0)
    db.add(log)
    db.commit()
    q = apply_push_log_visibility(db.query(PushLog), nodpt, db)
    assert q.count() == 0
