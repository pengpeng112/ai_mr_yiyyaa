"""
本地快速测试启动脚本
一键初始化 SQLite 数据库 + 创建演示数据 + 启动服务
"""
import sys
import os

# 强制 UTF-8 输出，兼容 Windows GBK 终端
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 快速启动脚本默认使用 SQLite，避免误连 Oracle
os.environ.setdefault("APP_DB_TYPE", "sqlite")

from app.database import SessionLocal, init_db
from app.models import (
    Role, Permission, RolePermission, Department, User,
    QCFeedback, QCFeedbackHistory, PushLog
)
from app.auth import hash_password
from datetime import datetime, timedelta
import random


def create_demo_data():
    """创建演示数据，便于本地测试"""
    db = SessionLocal()

    try:
        print("\n" + "="*60)
        print("  本地快速测试 - 演示数据初始化")
        print("="*60)

        # 1. 初始化数据库表
        print("\n[1/7] 创建数据库表...")
        init_db()
        print("[OK] 数据库表创建完成")

        # 2. 创建角色
        print("\n[2/7] 创建角色...")
        roles_data = [
            {"name": "admin", "description": "系统管理员"},
            {"name": "dept_manager", "description": "科室主任"},
            {"name": "clinician", "description": "临床医生"},
            {"name": "auditor", "description": "审计员"},
        ]

        roles = {}
        for role_data in roles_data:
            existing = db.query(Role).filter(Role.name == role_data["name"]).first()
            if not existing:
                role = Role(**role_data)
                db.add(role)
                db.flush()
                roles[role_data["name"]] = role
                print(f"  [+] {role_data['name']}")
            else:
                roles[role_data["name"]] = existing
                print(f"  [-] {role_data['name']} (already exists)")

        db.commit()

        # 3. 创建权限
        print("\n[3/7] 创建权限...")
        permissions_data = [
            {"name": "view_dashboard",  "description": "查看仪表板",   "module": "dashboard"},
            {"name": "view_reports",    "description": "查看质控报告", "module": "qc_reports"},
            {"name": "export_reports",  "description": "导出质控报告", "module": "qc_reports"},
            {"name": "view_feedback",   "description": "查看反馈",     "module": "feedback"},
            {"name": "create_feedback", "description": "创建反馈",     "module": "feedback"},
            {"name": "edit_feedback",   "description": "编辑反馈",     "module": "feedback"},
            {"name": "approve_feedback","description": "审批反馈",     "module": "feedback"},
            {"name": "manage_users",    "description": "管理用户",     "module": "admin"},
            {"name": "manage_roles",    "description": "管理角色",     "module": "admin"},
            {"name": "manage_config",   "description": "管理系统配置", "module": "admin"},
        ]

        permissions = {}
        for perm_data in permissions_data:
            existing = db.query(Permission).filter(Permission.name == perm_data["name"]).first()
            if not existing:
                perm = Permission(**perm_data)
                db.add(perm)
                db.flush()
                permissions[perm_data["name"]] = perm
            else:
                permissions[perm_data["name"]] = existing

        db.commit()
        print(f"[OK] {len(permissions)} permissions ready")

        # 4. 分配权限给角色
        print("\n[4/7] 分配权限给角色...")
        role_permissions_map = {
            "admin": [
                "view_dashboard", "view_reports", "export_reports",
                "view_feedback", "create_feedback", "edit_feedback", "approve_feedback",
                "manage_users", "manage_roles", "manage_config"
            ],
            "dept_manager": [
                "view_dashboard", "view_reports", "export_reports",
                "view_feedback", "create_feedback", "edit_feedback", "approve_feedback"
            ],
            "clinician": [
                "view_dashboard", "view_reports",
                "view_feedback", "create_feedback"
            ],
            "auditor": [
                "view_dashboard", "view_reports", "export_reports",
                "view_feedback", "create_feedback", "edit_feedback"
            ],
        }

        for role_name, perm_names in role_permissions_map.items():
            role = roles[role_name]
            for perm_name in perm_names:
                existing = db.query(RolePermission).filter(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == permissions[perm_name].id
                ).first()
                if not existing:
                    db.add(RolePermission(
                        role_id=role.id,
                        permission_id=permissions[perm_name].id
                    ))
            print(f"  [OK] {role_name}: {len(perm_names)} permissions")

        db.commit()

        # 5. 创建科室
        print("\n[5/7] 创建科室...")
        depts_data = [
            {"name": "心内科",   "code": "XNK"},
            {"name": "呼吸科",   "code": "HXK"},
            {"name": "消化科",   "code": "XHK"},
            {"name": "神经内科", "code": "SNNK"},
            {"name": "肾内科",   "code": "SNK"},
        ]

        depts = {}
        for dept_data in depts_data:
            existing = db.query(Department).filter(Department.name == dept_data["name"]).first()
            if not existing:
                dept = Department(**dept_data)
                db.add(dept)
                db.flush()
                depts[dept_data["name"]] = dept
            else:
                depts[dept_data["name"]] = existing

        db.commit()
        print(f"[OK] {len(depts)} departments ready")

        # 6. 创建默认用户
        print("\n[6/7] 创建默认用户...")
        users_data = [
            {"username": "admin",       "password": "admin123",   "full_name": "系统管理员", "email": "admin@hospital.com",      "role_name": "admin",        "dept_name": None},
            {"username": "manager_xnk", "password": "manager123", "full_name": "心内科主任", "email": "manager@hospital.com",    "role_name": "dept_manager", "dept_name": "心内科"},
            {"username": "doctor_001",  "password": "doctor123",  "full_name": "医生001",   "email": "doctor001@hospital.com", "role_name": "clinician",    "dept_name": "心内科"},
            {"username": "auditor_001", "password": "auditor123", "full_name": "审计员001", "email": "auditor001@hospital.com","role_name": "auditor",      "dept_name": None},
        ]

        created = 0
        for user_data in users_data:
            existing = db.query(User).filter(User.username == user_data["username"]).first()
            if not existing:
                role = roles[user_data["role_name"]]
                dept = depts.get(user_data["dept_name"]) if user_data["dept_name"] else None
                db.add(User(
                    username=user_data["username"],
                    password_hash=hash_password(user_data["password"]),
                    full_name=user_data["full_name"],
                    email=user_data["email"],
                    role_id=role.id,
                    dept_id=dept.id if dept else None,
                    is_active=True,
                ))
                db.flush()
                created += 1
                print(f"  [+] {user_data['username']} ({user_data['role_name']})")
            else:
                print(f"  [-] {user_data['username']} (already exists)")

        db.commit()
        print(f"[OK] {created} users created")

        # 7. 创建演示反馈数据
        print("\n[7/7] 创建演示反馈数据...")
        _create_demo_feedback(db)

        print("\n" + "="*60)
        print("  [DONE] 初始化完成！")
        print("="*60)
        print()
        print("  默认用户信息:")
        print("  +------------------+-------------+----------+")
        print("  | 用户名           | 密码        | 角色     |")
        print("  +------------------+-------------+----------+")
        print("  | admin            | admin123    | 管理员   |")
        print("  | manager_xnk      | manager123  | 科室主任 |")
        print("  | doctor_001       | doctor123   | 医生     |")
        print("  | auditor_001      | auditor123  | 审计员   |")
        print("  +------------------+-------------+----------+")
        print()
        print("  访问地址: http://localhost:8000")
        print("  API文档:  http://localhost:8000/docs")
        print()

    except Exception as e:
        print(f"\n[ERROR] 初始化失败: {e}")
        db.rollback()
        raise
    finally:
        db.close()


def _create_demo_feedback(db):
    """创建演示反馈数据"""
    try:
        admin_user  = db.query(User).filter(User.username == "admin").first()
        doctor_user = db.query(User).filter(User.username == "doctor_001").first()
        dept_xnk    = db.query(Department).filter(Department.name == "心内科").first()

        if not admin_user:
            print("[WARN] admin user not found, skipping demo feedback")
            return

        statuses   = ["pending", "acknowledged", "rectified", "closed"]
        severities = ["high", "medium", "low"]
        texts      = [
            "诊断信息不一致",
            "护理级别不匹配",
            "生命体征数据缺失",
            "医嘱执行记录不完整",
            "患者基本信息错误",
        ]

        for i in range(5):
            push_log = PushLog(
                patient_id=f"P{1001+i}",
                patient_name=f"患者{i+1}",
                dept_id=dept_xnk.id if dept_xnk else None,
                query_date="2026-03-30",
                trigger_type="manual",
                status="success",
                ai_result='{"result": "success"}',
                admission_no=f"ZYH{2026001+i}",
                visit_number=str(i+1),
            )
            db.add(push_log)
            db.flush()

            chosen_status = random.choice(statuses)
            feedback = QCFeedback(
                push_log_id=push_log.id,
                dept_id=dept_xnk.id if dept_xnk else None,
                severity=random.choice(severities),
                status=chosen_status,
                assigned_to=doctor_user.id if doctor_user else None,
                feedback_text=random.choice(texts),
                created_by=admin_user.id,
                created_at=datetime.now() - timedelta(days=random.randint(0, 10)),
            )
            db.add(feedback)
            db.flush()

            db.add(QCFeedbackHistory(
                feedback_id=feedback.id,
                old_status="pending",
                new_status=chosen_status,
                changed_by=admin_user.id,
                change_reason="Demo init",
                changed_at=datetime.now(),
            ))

        db.commit()
        print("[OK] 5 demo feedbacks created")

    except Exception as e:
        print(f"[WARN] Demo feedback creation failed: {e}")
        db.rollback()


if __name__ == "__main__":
    create_demo_data()
