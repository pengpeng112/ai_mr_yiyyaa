"""
RBAC 系统 API 测试脚本
测试登录、菜单、用户管理、质控反馈等功能
"""
import requests
import json
from typing import Optional

BASE_URL = "http://localhost:8000/api"

class APITester:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.token = None
        self.user = None
    
    def login(self, username: str, password: str) -> bool:
        """登录"""
        print(f"\n🔐 登录用户: {username}")
        try:
            response = requests.post(
                f"{self.base_url}/users/login",
                json={"username": username, "password": password}
            )
            if response.status_code == 200:
                data = response.json()
                self.token = data["access_token"]
                self.user = data["user"]
                print(f"✓ 登录成功")
                print(f"  用户: {self.user['full_name']} ({self.user['role']})")
                print(f"  权限: {', '.join(self.user['permissions'][:3])}...")
                return True
            else:
                print(f"✗ 登录失败: {response.status_code}")
                print(f"  {response.text}")
                return False
        except Exception as e:
            print(f"✗ 登录异常: {e}")
            return False
    
    def get_menu(self) -> bool:
        """获取菜单"""
        print(f"\n📋 获取菜单")
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            response = requests.get(f"{self.base_url}/menu", headers=headers)
            if response.status_code == 200:
                data = response.json()
                print(f"✓ 获取菜单成功")
                print(f"  角色: {data['role']}")
                print(f"  菜单项数: {len(data['menu'])}")
                for menu in data['menu']:
                    print(f"    - {menu['label']} ({menu['id']})")
                return True
            else:
                print(f"✗ 获取菜单失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ 获取菜单异常: {e}")
            return False
    
    def get_current_user(self) -> bool:
        """获取当前用户信息"""
        print(f"\n👤 获取当前用户信息")
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            response = requests.get(f"{self.base_url}/users/me", headers=headers)
            if response.status_code == 200:
                data = response.json()
                print(f"✓ 获取用户信息成功")
                print(f"  用户名: {data['username']}")
                print(f"  姓名: {data['full_name']}")
                print(f"  邮箱: {data['email']}")
                print(f"  角色: {data['role']}")
                if data['dept_name']:
                    print(f"  科室: {data['dept_name']}")
                return True
            else:
                print(f"✗ 获取用户信息失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ 获取用户信息异常: {e}")
            return False
    
    def list_users(self) -> bool:
        """列表用户（仅管理员）"""
        print(f"\n👥 列表用户")
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            response = requests.get(f"{self.base_url}/users?page=1&limit=10", headers=headers)
            if response.status_code == 200:
                data = response.json()
                print(f"✓ 列表用户成功")
                print(f"  总数: {data['total']}")
                print(f"  用户:")
                for user in data['items']:
                    print(f"    - {user['username']} ({user['full_name']}) - {user['role']}")
                return True
            else:
                print(f"✗ 列表用户失败: {response.status_code}")
                print(f"  {response.text}")
                return False
        except Exception as e:
            print(f"✗ 列表用户异常: {e}")
            return False
    
    def get_feedback_stats(self) -> bool:
        """获取反馈统计"""
        print(f"\n📊 获取反馈统计")
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            response = requests.get(f"{self.base_url}/qc/feedback/stats/summary", headers=headers)
            if response.status_code == 200:
                data = response.json()
                print(f"✓ 获取反馈统计成功")
                print(f"  总数: {data['total']}")
                print(f"  严重程度: 高={data['high']}, 中={data['medium']}, 低={data['low']}")
                print(f"  状态: 待处理={data['pending']}, 已确认={data['acknowledged']}, 已整改={data['rectified']}, 已关闭={data['closed']}")
                return True
            else:
                print(f"✗ 获取反馈统计失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ 获取反馈统计异常: {e}")
            return False
    
    def list_feedback(self) -> bool:
        """列表反馈"""
        print(f"\n📝 列表反馈")
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            response = requests.get(f"{self.base_url}/qc/feedback?page=1&limit=10", headers=headers)
            if response.status_code == 200:
                data = response.json()
                print(f"✓ 列表反馈成功")
                print(f"  总数: {data['total']}")
                if data['items']:
                    print(f"  反馈:")
                    for fb in data['items']:
                        print(f"    - ID={fb['id']}, 严重程度={fb['severity']}, 状态={fb['status']}")
                else:
                    print(f"  暂无反馈")
                return True
            else:
                print(f"✗ 列表反馈失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ 列表反馈异常: {e}")
            return False
    
    def logout(self) -> bool:
        """登出"""
        print(f"\n🚪 登出")
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            response = requests.post(f"{self.base_url}/users/logout", headers=headers)
            if response.status_code == 200:
                print(f"✓ 登出成功")
                self.token = None
                self.user = None
                return True
            else:
                print(f"✗ 登出失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ 登出异常: {e}")
            return False


def test_admin_flow():
    """测试管理员流程"""
    print("\n" + "="*60)
    print("测试管理员流程")
    print("="*60)
    
    tester = APITester()
    
    # 登录
    if not tester.login("admin", "admin123"):
        return False
    
    # 获取菜单
    tester.get_menu()
    
    # 获取当前用户
    tester.get_current_user()
    
    # 列表用户
    tester.list_users()
    
    # 获取反馈统计
    tester.get_feedback_stats()
    
    # 列表反馈
    tester.list_feedback()
    
    # 登出
    tester.logout()
    
    return True


def test_clinician_flow():
    """测试医生流程"""
    print("\n" + "="*60)
    print("测试医生流程")
    print("="*60)
    
    tester = APITester()
    
    # 登录
    if not tester.login("doctor_001", "doctor123"):
        return False
    
    # 获取菜单
    tester.get_menu()
    
    # 获取当前用户
    tester.get_current_user()
    
    # 获取反馈统计
    tester.get_feedback_stats()
    
    # 列表反馈
    tester.list_feedback()
    
    # 登出
    tester.logout()
    
    return True


def test_invalid_login():
    """测试无效登录"""
    print("\n" + "="*60)
    print("测试无效登录")
    print("="*60)
    
    tester = APITester()
    
    # 错误的密码
    print("\n🔐 尝试使用错误密码登录")
    tester.login("admin", "wrongpassword")
    
    # 不存在的用户
    print("\n🔐 尝试登录不存在的用户")
    tester.login("nonexistent", "password123")


if __name__ == "__main__":
    print("\n" + "="*60)
    print("RBAC 系统 API 测试")
    print("="*60)
    print("\n确保服务已启动: uvicorn app.main:app --reload")
    
    try:
        # 测试管理员流程
        test_admin_flow()
        
        # 测试医生流程
        test_clinician_flow()
        
        # 测试无效登录
        test_invalid_login()
        
        print("\n" + "="*60)
        print("✓ 所有测试完成")
        print("="*60)
        
    except KeyboardInterrupt:
        print("\n\n⚠️ 测试被中断")
    except Exception as e:
        print(f"\n\n✗ 测试异常: {e}")
