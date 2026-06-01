"""
审计类型 API 手工联调脚本。

用法：
1. 先启动服务：uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
2. 执行：python scripts/test_audit_types.py
"""
import json
from typing import Any

import requests


BASE_URL = "http://localhost:8000/api"


class AuditTypeTester:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.token = ""

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _print_result(self, title: str, response: requests.Response):
        print(f"\n=== {title} ===")
        print(f"status: {response.status_code}")
        try:
            print(json.dumps(response.json(), ensure_ascii=False, indent=2))
        except Exception:
            print(response.text)

    def login(self, username: str = "admin", password: str = "Admin123456") -> bool:
        response = requests.post(
            f"{self.base_url}/users/login",
            headers={"Content-Type": "application/json"},
            json={"username": username, "password": password},
            timeout=15,
        )
        self._print_result("登录", response)
        if response.status_code != 200:
            return False
        self.token = response.json().get("access_token", "")
        return bool(self.token)

    def list_audit_types(self):
        response = requests.get(
            f"{self.base_url}/audit-types",
            headers=self._headers(),
            timeout=15,
        )
        self._print_result("审计类型列表", response)
        return response

    def create_audit_type(self, code: str, name: str):
        payload: dict[str, Any] = {
            "code": code,
            "name": name,
            "description": "联调脚本创建的测试类型",
            "enabled": True,
            "sort_order": 999,
            "default_for_schedule": False,
            "sources": {
                "primary": {
                    "type": "sql",
                    "query_sql": "SELECT 1 FROM dual",
                    "field_mapping": {"patient_id": "PATIENT_ID", "visit_number": "VISIT_NO"},
                    "required": True,
                }
            },
            "group_key": ["patient_id", "visit_number"],
            "payload": {"builder": "generic_multi_source", "extra_fields": {}},
            "dify": {
                "base_url": "http://example.com/v1",
                "workflow_input_variable": "mr_txt",
                "workflow_output_key": "aa",
                "user_identifier": "med-audit-system",
                "timeout_seconds": 90,
                "extra_inputs": {},
                "targets": [],
            },
            "response": {"parse_strategy": "hybrid"},
            "display": {"summary_blocks": [], "detail_blocks": []},
        }
        response = requests.post(
            f"{self.base_url}/audit-types",
            headers=self._headers(),
            json=payload,
            timeout=20,
        )
        self._print_result("创建审计类型", response)
        return response

    def clone_audit_type(self, source_code: str, new_code: str, new_name: str):
        response = requests.post(
            f"{self.base_url}/audit-types/{source_code}/clone",
            headers=self._headers(),
            json={"new_code": new_code, "new_name": new_name},
            timeout=20,
        )
        self._print_result("克隆审计类型", response)
        return response

    def test_source(self, code: str, query_date: str):
        response = requests.post(
            f"{self.base_url}/audit-types/{code}/test-source",
            headers=self._headers(),
            json={"query_date": query_date, "date_dimension": "query_date", "dept_filter": []},
            timeout=30,
        )
        self._print_result("测试数据源", response)
        return response

    def test_dify(self, code: str, mr_txt_sample: str):
        response = requests.post(
            f"{self.base_url}/audit-types/{code}/test-dify",
            headers=self._headers(),
            json={"mr_txt_sample": mr_txt_sample},
            timeout=30,
        )
        self._print_result("测试 Dify", response)
        return response

    def delete_audit_type(self, code: str):
        response = requests.delete(
            f"{self.base_url}/audit-types/{code}",
            headers=self._headers(),
            timeout=20,
        )
        self._print_result("删除审计类型", response)
        return response


if __name__ == "__main__":
    tester = AuditTypeTester()
    if not tester.login():
        raise SystemExit("登录失败，停止联调")

    tester.list_audit_types()

    code = "api_smoke_audit"
    clone_code = f"{code}_copy"

    tester.create_audit_type(code, "API 联调测试类型")
    tester.clone_audit_type(code, clone_code, "API 联调测试类型 - 副本")
    tester.test_source(code, "2026-04-17")
    tester.test_dify(code, "这是用于 Dify 测试的样例病历文本。")
    tester.delete_audit_type(clone_code)
    tester.delete_audit_type(code)
