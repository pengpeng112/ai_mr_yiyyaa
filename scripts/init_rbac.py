"""
RBAC 系统初始化脚本
创建默认角色、权限、科室和管理员用户
"""
import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, init_db
from app.models import Role, Permission, RolePermission, Department, User
from app.auth import hash_password


def init_rbac():
    """初始化 RBAC 系统"""
    db = SessionLocal()
    
    try:
        # 1. 创建表
        print("创建数据库表...")
        init_db()
        print("✓ 数据库表创建完成")
        
        # 2. 创建角色
        print("\n创建角色...")
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
                print(f"  ✓ 创建角色: {role_data['name']}")
            else:
                roles[role_data["name"]] = existing
                print(f"  - 角色已存在: {role_data['name']}")
        
        db.commit()
        
        # 3. 创建权限
        print("\n创建权限...")
        permissions_data = [
            # 仪表板权限
            {"name": "view_dashboard", "description": "查看仪表板", "module": "dashboard"},
            
            # 质控报告权限
            {"name": "view_reports", "description": "查看质控报告", "module": "qc_reports"},
            {"name": "export_reports", "description": "导出质控报告", "module": "qc_reports"},
            
            # 反馈管理权限
            {"name": "view_feedback", "description": "查看反馈", "module": "feedback"},
            {"name": "create_feedback", "description": "创建反馈", "module": "feedback"},
            {"name": "edit_feedback", "description": "编辑反馈", "module": "feedback"},
            {"name": "approve_feedback", "description": "审批反馈", "module": "feedback"},
            
            # 用户管理权限
            {"name": "manage_users", "description": "管理用户", "module": "admin"},
            {"name": "manage_roles", "description": "管理角色", "module": "admin"},
            
            # 系统配置权限
            {"name": "manage_config", "description": "管理系统配置", "module": "admin"},
        ]
        
        permissions = {}
        for perm_data in permissions_data:
            existing = db.query(Permission).filter(Permission.name == perm_data["name"]).first()
            if not existing:
                perm = Permission(**perm_data)
                db.add(perm)
                db.flush()
                permissions[perm_data["name"]] = perm
                print(f"  ✓ 创建权限: {perm_data['name']}")
            else:
                permissions[perm_data["name"]] = existing
                print(f"  - 权限已存在: {perm_data['name']}")
        
        db.commit()
        
        # 4. 分配权限给角色
        print("\n分配权限给角色...")
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
                    rp = RolePermission(
                        role_id=role.id,
                        permission_id=permissions[perm_name].id
                    )
                    db.add(rp)
            print(f"  ✓ 为角色 {role_name} 分配了 {len(perm_names)} 个权限")
        
        db.commit()
        
        # 5. 创建科室
        print("\n创建科室...")
        depts_data = [
            {"name": "心内科", "code": "XNK"},
            {"name": "呼吸科", "code": "HXK"},
            {"name": "消化科", "code": "XHK"},
            {"name": "神经内科", "code": "SNNK"},
            {"name": "肾内科", "code": "SNK"},
        ]
        
        depts = {}
        for dept_data in depts_data:
            existing = db.query(Department).filter(Department.name == dept_data["name"]).first()
            if not existing:
                dept = Department(**dept_data)
                db.add(dept)
                db.flush()
                depts[dept_data["name"]] = dept
                print(f"  ✓ 创建科室: {dept_data['name']}")
            else:
                depts[dept_data["name"]] = existing
                print(f"  - 科室已存在: {dept_data['name']}")
        
        db.commit()
        
        # 6. 创建默认用户
        print("\n创建默认用户...")
        users_data = [
            {
                "username": "admin",
                "password": "admin123",
                "full_name": "系统管理员",
                "email": "admin@hospital.com",
                "role_name": "admin",
                "dept_name": None,
            },
            {
                "username": "manager_xnk",
                "password": "manager123",
                "full_name": "心内科主任",
                "email": "manager@hospital.com",
                "role_name": "dept_manager",
                "dept_name": "心内科",
            },
            {
                "username": "doctor_001",
                "password": "doctor123",
                "full_name": "医生001",
                "email": "doctor001@hospital.com",
                "role_name": "clinician",
                "dept_name": "心内科",
            },
            {
                "username": "auditor_001",
                "password": "auditor123",
                "full_name": "审计员001",
                "email": "auditor001@hospital.com",
                "role_name": "auditor",
                "dept_name": None,
            },
        ]
        
        for user_data in users_data:
            existing = db.query(User).filter(User.username == user_data["username"]).first()
            if not existing:
                role = roles[user_data["role_name"]]
                dept = depts.get(user_data["dept_name"]) if user_data["dept_name"] else None
                
                user = User(
                    username=user_data["username"],
                    password_hash=hash_password(user_data["password"]),
                    full_name=user_data["full_name"],
                    email=user_data["email"],
                    role_id=role.id,
                    dept_id=dept.id if dept else None,
                    is_active=True,
                )
                db.add(user)
                db.flush()
                print(f"  ✓ 创建用户: {user_data['username']} (密码: {user_data['password']})")
            else:
                print(f"  - 用户已存在: {user_data['username']}")
        
        db.commit()
        
        print("\n" + "="*50)
        print("✓ RBAC 系统初始化完成！")
        print("="*50)
        print("\n默认用户信息:")
        print("  用户名: admin          密码: admin123")
        print("  用户名: manager_xnk    密码: manager123")
        print("  用户名: doctor_001     密码: doctor123")
        print("  用户名: auditor_001    密码: auditor123")
        print("\n请在生产环境中修改这些密码！")
        
    except Exception as e:
        print(f"\n✗ 初始化失败: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    init_rbac()
