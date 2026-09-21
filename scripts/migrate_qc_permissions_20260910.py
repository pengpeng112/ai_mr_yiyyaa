# -*- coding: utf-8 -*-
"""046 新增权限显式迁移脚本（默认 dry-run；--apply 才写库）。

纪律（046 §3.2）：
- 新增业务权限只经本脚本落库，禁止挂 init_db/_ensure_default_rbac_permissions/
  启动或访问钩子自动 seed；代码部署后仅重启不得新增权限或扩大既有角色授权；
- 幂等：权限/角色关联已存在则跳过；只处理本轮白名单项，不触碰其他权限；
- 回滚（--rollback）只删除本脚本白名单内的关联与权限行，不动既有权限；
- 生产 apply 须按 023 §9.1 批准（备份+dry-run 明细落 docs/remediation/），
  本脚本本地/演示库可直接 apply。

新增权限与角色关联（最小集合）：
  prearchive_match_run      （AI 匹配任务/候选决策）   → admin 隐式全通过，不另授角色
  prearchive_trial_manage   （trial 申请/管理）        → 同上
  prearchive_check_view     （核查工作台查看）         → auditor / dept_manager / clinician
  prearchive_issue_review   （人工确认缺陷/误报/关闭） → auditor
  prearchive_issue_feedback （医生整改反馈/复检申请）  → clinician / dept_manager
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

NEW_PERMISSIONS = [
    ("prearchive_match_run", "AI 匹配任务创建/执行/取消与候选接受驳回", "prearchive"),
    ("prearchive_trial_manage", "试运行（trial）申请与管理", "prearchive"),
    ("prearchive_check_view", "无纸化核查工作台查看（就诊/缺陷/复检状态）", "prearchive"),
    ("prearchive_issue_review", "缺陷人工确认/误报/关闭（质控动作）", "prearchive"),
    ("prearchive_issue_feedback", "医生整改反馈与复检申请", "prearchive"),
]

ROLE_GRANTS = {
    "prearchive_check_view": ("auditor", "dept_manager", "clinician"),
    "prearchive_issue_review": ("auditor",),
    "prearchive_issue_feedback": ("clinician", "dept_manager"),
    "prearchive_match_run": (),      # admin 隐式全通过；按最小集合不另授角色
    "prearchive_trial_manage": (),
}


def _session_factory():
    from app.database import SessionLocal
    return SessionLocal


def compute_plan(session) -> dict:
    from app.models import Permission, Role, RolePermission

    plan = {"permissions_to_add": [], "permissions_existing": [],
            "role_grants_to_add": [], "role_grants_existing": [],
            "roles_missing": []}
    existing_perms = {p.name: p for p in session.query(Permission).all()}
    roles = {r.name: r for r in session.query(Role).all()}

    perm_ids = {}
    for name, desc, module in NEW_PERMISSIONS:
        if name in existing_perms:
            plan["permissions_existing"].append(name)
            perm_ids[name] = existing_perms[name].id
        else:
            plan["permissions_to_add"].append(
                {"name": name, "description": desc, "module": module})

    # 预演 apply 后的权限 id 集合（dry-run 也要给出完整计划）
    next_id = max((p.id for p in existing_perms.values()), default=0) + 1
    for item in plan["permissions_to_add"]:
        perm_ids.setdefault(item["name"], next_id)
        next_id += 1

    existing_grants = set(
        (rp.role_id, rp.permission_id)
        for rp in session.query(RolePermission).all())
    for perm_name, role_names in ROLE_GRANTS.items():
        pid = perm_ids.get(perm_name)
        for role_name in role_names:
            role = roles.get(role_name)
            if role is None:
                plan["roles_missing"].append(role_name)
                continue
            if (role.id, pid) in existing_grants:
                plan["role_grants_existing"].append(
                    {"role": role_name, "permission": perm_name})
            else:
                plan["role_grants_to_add"].append(
                    {"role": role_name, "permission": perm_name,
                     "role_id": role.id})
    return plan


def apply_plan(session, plan: dict) -> dict:
    from app.models import Permission, RolePermission

    added_perms = 0
    added_grants = 0
    for item in plan["permissions_to_add"]:
        exists = session.query(Permission).filter(
            Permission.name == item["name"]).first()
        if exists is None:
            session.add(Permission(name=item["name"],
                                   description=item["description"],
                                   module=item["module"]))
            added_perms += 1
    session.flush()
    for grant in plan["role_grants_to_add"]:
        perm = session.query(Permission).filter(
            Permission.name == grant["permission"]).first()
        if perm is None:
            continue
        dup = session.query(RolePermission).filter(
            RolePermission.role_id == grant["role_id"],
            RolePermission.permission_id == perm.id).first()
        if dup is None:
            session.add(RolePermission(role_id=grant["role_id"],
                                       permission_id=perm.id))
            added_grants += 1
    session.commit()
    return {"permissions_added": added_perms, "role_grants_added": added_grants}


def rollback(session) -> dict:
    from app.models import Permission, RolePermission

    removed_grants = 0
    removed_perms = 0
    names = [name for name, _d, _m in NEW_PERMISSIONS]
    perms = session.query(Permission).filter(Permission.name.in_(names)).all()
    for perm in perms:
        removed_grants += session.query(RolePermission).filter(
            RolePermission.permission_id == perm.id).delete()
        session.delete(perm)
        removed_perms += 1
    session.commit()
    return {"permissions_removed": removed_perms,
            "role_grants_removed": removed_grants}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="046 新增权限显式迁移（默认 dry-run）")
    parser.add_argument("--apply", action="store_true", help="实际写库（默认 dry-run）")
    parser.add_argument("--rollback", action="store_true",
                        help="只回滚本脚本白名单内的权限与关联")
    parser.add_argument("--output", type=Path,
                        help="计划/结果 JSON 输出路径（生产 apply 时应落 docs/remediation/）")
    args = parser.parse_args(argv)

    session = _session_factory()()
    try:
        if args.rollback:
            if not args.apply:
                result = {"mode": "rollback-dry-run",
                          "note": "加 --apply 才执行回滚"}
            else:
                result = {"mode": "rollback", **rollback(session)}
        else:
            plan = compute_plan(session)
            result = {"mode": "apply" if args.apply else "dry-run",
                      "generated_at": datetime.now().isoformat(timespec="seconds"),
                      **plan}
            if args.apply:
                result["applied"] = apply_plan(session, plan)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        print(text)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text, encoding="utf-8")
            print(f"[migrate] written: {args.output}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
