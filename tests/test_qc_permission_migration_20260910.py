"""046 T1a 权限显式迁移测试：dry-run/apply/rollback/幂等 + 无启动 seed 守卫。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "migrate_qc_permissions_20260910",
    ROOT / "scripts" / "migrate_qc_permissions_20260910.py")
migrate = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("migrate_qc_permissions_20260910", migrate)
_spec.loader.exec_module(migrate)

NEW_NAMES = [n for n, _d, _m in migrate.NEW_PERMISSIONS]


@pytest.fixture()
def session():
    from app.models import Permission, Role, RolePermission, Role, User, Base
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine,
                             tables=[Role.__table__, Permission.__table__,
                                     RolePermission.__table__])
    s = sessionmaker(bind=engine)()
    s.add(Role(id=1, name="admin"))
    s.add(Role(id=2, name="auditor"))
    s.add(Role(id=3, name="dept_manager"))
    s.add(Role(id=4, name="clinician"))
    s.commit()
    yield s
    s.close()


def test_dry_run_adds_nothing(session):
    from app.models import Permission
    before = session.query(Permission).count()
    plan = migrate.compute_plan(session)
    assert len(plan["permissions_to_add"]) == 5
    assert {i["name"] for i in plan["permissions_to_add"]} == set(NEW_NAMES)
    assert not plan["roles_missing"]
    assert session.query(Permission).count() == before, "dry-run 不得写库"


def test_apply_then_idempotent(session):
    from app.models import Permission
    plan = migrate.compute_plan(session)
    applied = migrate.apply_plan(session, plan)
    assert applied["permissions_added"] == 5
    assert applied["role_grants_added"] == 6   # check_view×3 + review×1 + feedback×2

    names = {p.name for p in session.query(Permission).all()}
    assert set(NEW_NAMES) <= names

    plan2 = migrate.compute_plan(session)
    assert plan2["permissions_to_add"] == []
    assert plan2["role_grants_to_add"] == []
    applied2 = migrate.apply_plan(session, plan2)
    assert applied2["permissions_added"] == 0 and applied2["role_grants_added"] == 0


def test_rollback_only_removes_whitelist(session):
    from app.models import Permission, RolePermission
    plan = migrate.compute_plan(session)
    migrate.apply_plan(session, plan)
    # 造一个不属于白名单的权限，回滚不得删除
    keeper = Permission(name="legacy_perm_2020", description="", module="old")
    session.add(keeper)
    session.commit()

    result = migrate.rollback(session)
    assert result["permissions_removed"] == 5
    assert result["role_grants_removed"] == 6
    remaining = {p.name for p in session.query(Permission).all()}
    assert "legacy_perm_2020" in remaining
    assert not (set(NEW_NAMES) & remaining)
    assert session.query(RolePermission).count() == 0


def test_new_permissions_not_in_startup_seed():
    """046 §3.2 红线：init_db/_ensure_default_rbac_permissions 不得包含新权限。"""
    db_src = (ROOT / "app" / "database.py").read_text(encoding="utf-8")
    seed_section = db_src[db_src.index("_ensure_default_rbac_permissions"):
                          db_src.index("def ", db_src.index("_ensure_default_rbac_permissions") + 10)]
    for name in NEW_NAMES:
        assert name not in seed_section, f"{name} 不得进入启动 seed"
        assert name not in db_src, f"{name} 不得出现在 database.py 任何位置"
    main_src = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    for name in NEW_NAMES:
        assert name not in main_src
    # 迁移脚本自身必须默认 dry-run
    script = (ROOT / "scripts" / "migrate_qc_permissions_20260910.py").read_text(
        encoding="utf-8")
    assert '"--apply", action="store_true"' in script
    assert "默认 dry-run" in script


def test_bff_new_routes_permission_gates():
    """新增 BFF 端点的权限声明（match→match_run；trial 写→trial_manage；全覆盖）。"""
    import inspect
    import re as _re
    from app.routers import prearchive_admin as bff
    guards = {}
    for route in bff.router.routes:
        path = getattr(route, "path", "")
        if any(k in path for k in ("coverage", "match", "trial")):
            src = inspect.getsource(route.endpoint)
            m = _re.search(r"_require\((\w+)\)", src)
            guards[(path, ",".join(sorted(route.methods)))] = \
                m.group(1) if m else None
    assert guards, "未找到新增端点"
    assert any("match/tasks" in p and v == "PERM_MATCH"
               for (p, _m), v in guards.items()), guards
    assert any("trial/runs" in p and "POST" in _m and v == "PERM_TRIAL"
               for (p, _m), v in guards.items()), guards
    assert any("trial/runs" in p and "GET" in _m and v == "PERM_VIEW"
               for (p, _m), v in guards.items()), guards
    assert all(v for v in guards.values()), "所有新端点必须声明权限"
