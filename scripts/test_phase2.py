"""
Phase 2 API 测试脚本
测试角色管理、权限管理、科室管理、用户扩展功能
"""
import requests
import json

BASE_URL = "http://localhost:8000/api"

class Phase2Tester:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.token = None
        self.admin_token = None
    
    def login_as_admin(self) -> bool:
        """以管理员身份登录"""
        print("\n🔐 以管理员身份登录")
        try:
            response = requests.post(
                f"{self.base_url}/users/login",
                json={"username": "admin", "password": "admin123"}
            )
            if response.status_code == 200:
                data = response.json()
                self.admin_token = data["access_token"]
                print(f"✓ 管理员登录成功")
                return True
            else:
                print(f"✗ 登录失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ 登录异常: {e}")
            return False
    
    def test_list_roles(self) -> bool:
        """测试获取角色列表"""
        print("\n🎭 测试获取角色列表")
        try:
            headers = {"Authorization": f"Bearer {self.admin_token}"}
            response = requests.get(f"{self.base_url}/roles", headers=headers)
            if response.status_code == 200:
                data = response.json()
                print(f"✓ 获取角色列表成功")
                print(f"  角色数: {len(data)}")
                for role in data:
                    print(f"    - {role['name']} ({len(role['permissions'])} 个权限)")
                return True
            else:
                print(f"✗ 获取角色列表失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ 获取角色列表异常: {e}")
            return False
    
    def test_get_role_detail(self, role_id: int = 1) -> bool:
        """测试获取角色详情"""
        print(f"\n🎭 测试获取角色详情 (ID={role_id})")
        try:
            headers = {"Authorization": f"Bearer {self.admin_token}"}
            response = requests.get(f"{self.base_url}/roles/{role_id}", headers=headers)
            if response.status_code == 200:
                data = response.json()
                print(f"✓ 获取角色详情成功")
                print(f"  角色名: {data['name']}")
                print(f"  权限数: {len(data['permissions'])}")
                print(f"  权限: {', '.join([p['name'] for p in data['permissions'][:3]])}...")
                return True
            else:
                print(f"✗ 获取角色详情失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ 获取角色详情异常: {e}")
            return False
    
    def test_list_permissions(self) -> bool:
        """测试获取权限列表"""
        print("\n🔐 测试获取权限列表")
        try:
            headers = {"Authorization": f"Bearer {self.admin_token}"}
            response = requests.get(f"{self.base_url}/permissions", headers=headers)
            if response.status_code == 200:
                data = response.json()
                print(f"✓ 获取权限列表成功")
                print(f"  权限数: {len(data)}")
                for perm in data[:5]:
                    print(f"    - {perm['name']} ({perm['module']})")
                return True
            else:
                print(f"✗ 获取权限列表失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ 获取权限列表异常: {e}")
            return False
    
    def test_list_departments(self) -> bool:
        """测试获取科室列表"""
        print("\n🏥 测试获取科室列表")
        try:
            headers = {"Authorization": f"Bearer {self.admin_token}"}
            response = requests.get(f"{self.base_url}/departments", headers=headers)
            if response.status_code == 200:
                data = response.json()
                print(f"✓ 获取科室列表成功")
                print(f"  科室数: {len(data)}")
                for dept in data:
                    print(f"    - {dept['name']} ({dept['code']})")
                return True
            else:
                print(f"✗ 获取科室列表失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ 获取科室列表异常: {e}")
            return False
    
    def test_get_user_permissions(self, user_id: int = 1) -> bool:
        """测试获取用户权限"""
        print(f"\n👤 测试获取用户权限 (ID={user_id})")
        try:
            headers = {"Authorization": f"Bearer {self.admin_token}"}
            response = requests.get(f"{self.base_url}/users/{user_id}/permissions", headers=headers)
            if response.status_code == 200:
                data = response.json()
                print(f"✓ 获取用户权限成功")
                print(f"  用户名: {data['username']}")
                print(f"  角色: {data['role']}")
                print(f"  权限数: {len(data['permissions'])}")
                print(f"  权限: {', '.join(data['permissions'][:3])}...")
                return True
            else:
                print(f"✗ 获取用户权限失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ 获取用户权限异常: {e}")
            return False
    
    def test_change_password(self, user_id: int = 1) -> bool:
        """测试修改密码"""
        print(f"\n🔑 测试修改密码 (ID={user_id})")
        try:
            headers = {"Authorization": f"Bearer {self.admin_token}"}
            response = requests.post(
                f"{self.base_url}/users/{user_id}/change-password",
                headers=headers,
                params={
                    "old_password": "admin123",
                    "new_password": "newpassword123"
                }
            )
            if response.status_code == 200:
                print(f"✓ 修改密码成功")
                # 改回原密码
                requests.post(
                    f"{self.base_url}/users/{user_id}/change-password",
                    headers=headers,
                    params={
                        "old_password": "newpassword123",
                        "new_password": "admin123"
                    }
                )
                print(f"  已改回原密码")
                return True
            else:
                print(f"✗ 修改密码失败: {response.status_code}")
                print(f"  {response.text}")
                return False
        except Exception as e:
            print(f"✗ 修改密码异常: {e}")
            return False
    
    def test_create_department(self) -> bool:
        """测试创建科室"""
        print("\n🏥 测试创建科室")
        try:
            headers = {"Authorization": f"Bearer {self.admin_token}"}
            response = requests.post(
                f"{self.base_url}/departments",
                headers=headers,
                json={
                    "name": "测试科室",
                    "code": "TEST",
                    "manager_id": None
                }
            )
            if response.status_code == 200:
                data = response.json()
                print(f"✓ 创建科室成功")
                print(f"  科室ID: {data['id']}")
                print(f"  科室名: {data['name']}")
                
                # 删除测试科室
                requests.delete(
                    f"{self.base_url}/departments/{data['id']}",
                    headers=headers
                )
                print(f"  已删除测试科室")
                return True
            else:
                print(f"✗ 创建科室失败: {response.status_code}")
                print(f"  {response.text}")
                return False
        except Exception as e:
            print(f"✗ 创建科室异常: {e}")
            return False
    
    def test_assign_permission(self) -> bool:
        """测试为角色分配权限"""
        print("\n🎭 测试为角色分配权限")
        try:
            headers = {"Authorization": f"Bearer {self.admin_token}"}
            
            # 先获取一个权限
            perm_response = requests.get(f"{self.base_url}/permissions", headers=headers)
            if perm_response.status_code != 200:
                print(f"✗ 获取权限列表失败")
                return False
            
            permissions = perm_response.json()
            if not permissions:
                print(f"✗ 没有可用的权限")
                return False
            
            perm_id = permissions[0]['id']
            
            # 尝试为角色分配权限
            response = requests.post(
                f"{self.base_url}/roles/4/permissions/{perm_id}",
                headers=headers
            )
            if response.status_code == 200:
                print(f"✓ 为角色分配权限成功")
                return True
            else:
                print(f"✗ 为角色分配权限失败: {response.status_code}")
                print(f"  {response.text}")
                return False
        except Exception as e:
            print(f"✗ 为角色分配权限异常: {e}")
            return False


def run_phase2_tests():
    """运行 Phase 2 测试"""
    print("\n" + "="*60)
    print("Phase 2 API 测试")
    print("="*60)
    
    tester = Phase2Tester()
    
    # 登录
    if not tester.login_as_admin():
        print("\n✗ 无法登录，测试中止")
        return False
    
    # 运行测试
    tests = [
        ("角色列表", tester.test_list_roles),
        ("角色详情", tester.test_get_role_detail),
        ("权限列表", tester.test_list_permissions),
        ("科室列表", tester.test_list_departments),
        ("用户权限", tester.test_get_user_permissions),
        ("修改密码", tester.test_change_password),
        ("创建科室", tester.test_create_department),
        ("分配权限", tester.test_assign_permission),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n✗ {test_name} 异常: {e}")
            results.append((test_name, False))
    
    # 打印总结
    print("\n" + "="*60)
    print("测试总结")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✓" if result else "✗"
        print(f"{status} {test_name}")
    
    print(f"\n通过: {passed}/{total}")
    
    if passed == total:
        print("✓ 所有测试通过！")
    else:
        print(f"✗ 有 {total - passed} 个测试失败")
    
    return passed == total


if __name__ == "__main__":
    try:
        success = run_phase2_tests()
        exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️ 测试被中断")
        exit(1)
    except Exception as e:
        print(f"\n\n✗ 测试异常: {e}")
        exit(1)
