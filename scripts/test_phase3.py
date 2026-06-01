"""
Phase 3 API 测试脚本
测试反馈统计、导出等功能
"""
import requests
import json

BASE_URL = "http://localhost:8000/api"

class Phase3Tester:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.token = None
    
    def login_as_admin(self) -> bool:
        """以管理员身份登录"""
        print("\n🔐 以管理员身份登录")
        try:
            response = requests.post(
                f"{self.base_url}/users/login",
                json={"username": "admin", "password": "Admin123456"}
            )
            if response.status_code == 200:
                data = response.json()
                self.token = data["access_token"]
                print(f"✓ 管理员登录成功")
                return True
            else:
                print(f"✗ 登录失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ 登录异常: {e}")
            return False
    
    def test_feedback_summary_stats(self) -> bool:
        """测试反馈总体统计"""
        print("\n📊 测试反馈总体统计")
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            response = requests.get(f"{self.base_url}/qc/feedback/stats/summary", headers=headers)
            if response.status_code == 200:
                data = response.json()
                print(f"✓ 获取反馈总体统计成功")
                print(f"  总数: {data['total']}")
                print(f"  严重程度: 高={data['high']}, 中={data['medium']}, 低={data['low']}")
                print(f"  状态: 待处理={data['pending']}, 已确认={data['acknowledged']}, 已整改={data['rectified']}, 已关闭={data['closed']}")
                return True
            else:
                print(f"✗ 获取反馈总体统计失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ 获取反馈总体统计异常: {e}")
            return False
    
    def test_dashboard_stats(self) -> bool:
        """测试仪表板统计"""
        print("\n📈 测试仪表板统计")
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            response = requests.get(f"{self.base_url}/qc/feedback/stats/dashboard", headers=headers)
            if response.status_code == 200:
                data = response.json()
                print(f"✓ 获取仪表板统计成功")
                print(f"  包含数据:")
                for key in data.keys():
                    print(f"    - {key}")
                return True
            else:
                print(f"✗ 获取仪表板统计失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ 获取仪表板统计异常: {e}")
            return False
    
    def test_severity_stats(self) -> bool:
        """测试严重程度统计"""
        print("\n🔴 测试严重程度统计")
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            response = requests.get(f"{self.base_url}/qc/feedback/stats/severity", headers=headers)
            if response.status_code == 200:
                data = response.json()
                print(f"✓ 获取严重程度统计成功")
                for item in data.get("severity_distribution", []):
                    print(f"  {item['severity']}: {item['count']} ({item['percentage']}%)")
                return True
            else:
                print(f"✗ 获取严重程度统计失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ 获取严重程度统计异常: {e}")
            return False
    
    def test_status_stats(self) -> bool:
        """测试状态统计"""
        print("\n📋 测试状态统计")
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            response = requests.get(f"{self.base_url}/qc/feedback/stats/status", headers=headers)
            if response.status_code == 200:
                data = response.json()
                print(f"✓ 获取状态统计成功")
                for item in data.get("status_distribution", []):
                    print(f"  {item['status']}: {item['count']} ({item['percentage']}%)")
                return True
            else:
                print(f"✗ 获取状态统计失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ 获取状态统计异常: {e}")
            return False
    
    def test_trend_stats(self) -> bool:
        """测试趋势统计"""
        print("\n📈 测试趋势统计")
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            response = requests.get(f"{self.base_url}/qc/feedback/stats/trend?days=30", headers=headers)
            if response.status_code == 200:
                data = response.json()
                trend = data.get("daily_trend", [])
                print(f"✓ 获取趋势统计成功")
                print(f"  数据点数: {len(trend)}")
                if trend:
                    print(f"  最新数据: {trend[-1]}")
                return True
            else:
                print(f"✗ 获取趋势统计失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ 获取趋势统计异常: {e}")
            return False
    
    def test_rectification_rate(self) -> bool:
        """测试整改率"""
        print("\n✅ 测试整改率")
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            response = requests.get(f"{self.base_url}/qc/feedback/stats/rectification-rate", headers=headers)
            if response.status_code == 200:
                data = response.json()
                print(f"✓ 获取整改率成功")
                print(f"  总数: {data['total']}")
                print(f"  已整改: {data['rectified']}")
                print(f"  整改率: {data['rate']}%")
                return True
            else:
                print(f"✗ 获取整改率失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ 获取整改率异常: {e}")
            return False
    
    def test_top_issues(self) -> bool:
        """测试高频问题"""
        print("\n🔥 测试高频问题")
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            response = requests.get(f"{self.base_url}/qc/feedback/stats/top-issues?limit=5", headers=headers)
            if response.status_code == 200:
                data = response.json()
                issues = data.get("top_issues", [])
                print(f"✓ 获取高频问题成功")
                print(f"  问题数: {len(issues)}")
                for issue in issues[:3]:
                    print(f"    - {issue['issue']}: {issue['count']} 次")
                return True
            else:
                print(f"✗ 获取高频问题失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ 获取高频问题异常: {e}")
            return False
    
    def test_user_workload(self) -> bool:
        """测试用户工作量"""
        print("\n👥 测试用户工作量")
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            response = requests.get(f"{self.base_url}/qc/feedback/stats/user-workload", headers=headers)
            if response.status_code == 200:
                data = response.json()
                workload = data.get("user_workload", [])
                print(f"✓ 获取用户工作量成功")
                print(f"  用户数: {len(workload)}")
                for user in workload[:3]:
                    print(f"    - {user['user_name']}: 分配 {user['assigned_count']}, 待处理 {user['pending_count']}")
                return True
            else:
                print(f"✗ 获取用户工作量失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ 获取用户工作量异常: {e}")
            return False
    
    def test_export_csv(self) -> bool:
        """测试 CSV 导出"""
        print("\n📥 测试 CSV 导出")
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            response = requests.get(f"{self.base_url}/qc/feedback/export/csv", headers=headers)
            if response.status_code == 200:
                print(f"✓ CSV 导出成功")
                print(f"  数据大小: {len(response.content)} 字节")
                return True
            else:
                print(f"✗ CSV 导出失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ CSV 导出异常: {e}")
            return False
    
    def test_export_excel(self) -> bool:
        """测试 Excel 导出"""
        print("\n📊 测试 Excel 导出")
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            response = requests.get(f"{self.base_url}/qc/feedback/export/excel", headers=headers)
            if response.status_code == 200:
                print(f"✓ Excel 导出成功")
                print(f"  数据大小: {len(response.content)} 字节")
                return True
            else:
                print(f"✗ Excel 导出失败: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ Excel 导出异常: {e}")
            return False


def run_phase3_tests():
    """运行 Phase 3 测试"""
    print("\n" + "="*60)
    print("Phase 3 API 测试")
    print("="*60)
    
    tester = Phase3Tester()
    
    # 登录
    if not tester.login_as_admin():
        print("\n✗ 无法登录，测试中止")
        return False
    
    # 运行测试
    tests = [
        ("反馈总体统计", tester.test_feedback_summary_stats),
        ("仪表板统计", tester.test_dashboard_stats),
        ("严重程度统计", tester.test_severity_stats),
        ("状态统计", tester.test_status_stats),
        ("趋势统计", tester.test_trend_stats),
        ("整改率", tester.test_rectification_rate),
        ("高频问题", tester.test_top_issues),
        ("用户工作量", tester.test_user_workload),
        ("CSV 导出", tester.test_export_csv),
        ("Excel 导出", tester.test_export_excel),
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
        success = run_phase3_tests()
        exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️ 测试被中断")
        exit(1)
    except Exception as e:
        print(f"\n\n✗ 测试异常: {e}")
        exit(1)
