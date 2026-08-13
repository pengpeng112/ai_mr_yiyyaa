"""初始化 RBAC 角色、权限和示例科室，不创建任何默认账号。

管理员必须通过 ``python scripts/init_admin.py`` 显式创建并设置强密码；
合成演示账号只允许由 ``scripts/demo_env.py`` 在隔离目录中生成。
"""
import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, init_db
from app.models import Role, Permission, RolePermission, Department


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

            # 调度器权限
            {"name": "view_scheduler", "description": "查看调度器", "module": "scheduler"},
            {"name": "manage_scheduler", "description": "管理调度器", "module": "scheduler"},
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
                "manage_users", "manage_roles", "manage_config",
                "view_scheduler", "manage_scheduler"
            ],
            "dept_manager": [
                "view_dashboard", "view_reports", "export_reports",
                "view_feedback", "create_feedback", "edit_feedback", "approve_feedback",
                "view_scheduler", "manage_scheduler"
            ],
            "clinician": [
                "view_dashboard", "view_reports",
                "view_feedback", "create_feedback"
            ],
            "auditor": [
                "view_dashboard", "view_reports", "export_reports",
                "view_feedback", "create_feedback"
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
        
        print("\n" + "="*50)
        print("✓ RBAC 系统初始化完成！")
        print("="*50)
        print("未创建默认账号。请运行 python scripts/init_admin.py 创建管理员。")
        
    except Exception as e:
        print(f"\n✗ 初始化失败: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    init_rbac()
