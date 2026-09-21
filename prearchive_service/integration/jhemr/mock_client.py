# -*- coding: utf-8 -*-
"""JHEMR ↔ Med-Audit Mock 客户端（046 T7 联调包，纯标准库，可直接拷给 JHEMR 开发方）。

用法（L1 本地验收）::

    python mock_client.py --base http://127.0.0.1:8000 \
        --client-id jhemr-demo --secret <JHEMR_INTEGRATION_HMAC_SECRET> \
        --patient TEST0002 --visit 1

也可以 import 复用::

    from mock_client import JhemrClient
    client = JhemrClient(base_url, client_id, secret)
    created = client.create_submission_check(patient_id="TEST0002",
                                             visit_number="1",
                                             submission_id="SUB-001",
                                             operator={"id": "DOC77", "name": "X"})
    result = client.poll_check(created["check_id"], timeout_seconds=60)
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
import uuid

CLOCK_SKEW_SECONDS = 300


def build_signature(secret: str, client_id: str, method: str, path: str,
                    body: bytes, timestamp: str, nonce: str) -> str:
    """与 Med-Audit 主服务逐字节一致的签名实现（六要素绑定）。"""
    body_hash = hashlib.sha256(body or b"").hexdigest()
    message = "\n".join([client_id, method.upper(), path, body_hash,
                         timestamp, nonce])
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"),
                    hashlib.sha256).hexdigest()


class JhemrClient:
    def __init__(self, base_url: str, client_id: str, secret: str,
                 timeout_seconds: int = 10):
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.secret = secret
        self.timeout = timeout_seconds

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        raw = json.dumps(body or {}, ensure_ascii=False).encode("utf-8") \
            if body is not None else b""
        timestamp = str(int(time.time()))
        nonce = uuid.uuid4().hex
        headers = {
            "Content-Type": "application/json",
            "X-Jhemr-Client-Id": self.client_id,
            "X-Jhemr-Timestamp": timestamp,
            "X-Jhemr-Nonce": nonce,
            "X-Jhemr-Signature": build_signature(
                self.secret, self.client_id, method, path, raw,
                timestamp, nonce),
        }
        request = urllib.request.Request(
            self.base_url + path, data=raw if method == "POST" else None,
            headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                return {"status": resp.status,
                        "json": json.loads(resp.read().decode("utf-8"))}
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode("utf-8", "replace")
            try:
                payload = json.loads(payload)
            except ValueError:
                pass
            return {"status": exc.code, "json": payload}

    # ---- 五接口 ----

    def create_submission_check(self, *, patient_id: str, visit_number: str,
                                submission_id: str, operator: dict,
                                document_refs: list | None = None,
                                dept: str = "", submitted_at: str = "") -> dict:
        return self._request("POST", "/api/integrations/jhemr/submission-checks", {
            "request_id": uuid.uuid4().hex,
            "patient_id": patient_id, "visit_number": visit_number,
            "operator": operator, "dept": dept,
            "submission_id": submission_id,
            "document_refs": document_refs or [],
            "submitted_at": submitted_at,
        })

    def get_check(self, check_id: str) -> dict:
        return self._request(
            "GET", f"/api/integrations/jhemr/submission-checks/{check_id}")

    def poll_check(self, check_id: str, timeout_seconds: int = 60) -> dict:
        """退避轮询（2s/5s/10s…），终态（completed/partial/failed）返回视图。"""
        deadline = time.time() + timeout_seconds
        backoff = 2.0
        while True:
            response = self.get_check(check_id)
            payload = response.get("json") or {}
            if response["status"] == 200 and payload.get("status") in (
                    "completed", "partial", "failed"):
                return payload
            if time.time() >= deadline:
                return payload
            time.sleep(min(backoff, 10.0))
            backoff = min(backoff * 2.0, 10.0)

    def create_view_ticket(self, *, patient_id: str, visit_number: str,
                           operator_id: str, scope: str = "issue_view") -> dict:
        return self._request("POST", "/api/integrations/jhemr/view-tickets", {
            "patient_id": patient_id, "visit_number": visit_number,
            "operator_id": operator_id, "scope": scope,
        })

    def issue_feedback(self, *, issue_id: str, action: str, operator: dict,
                       reason: str = "", expect_issue_version: int = 0,
                       document_revision: str = "") -> dict:
        return self._request(
            "POST", f"/api/integrations/jhemr/issues/{issue_id}/feedback", {
                "action": action, "reason": reason,
                "expect_issue_version": expect_issue_version,
                "document_revision": document_revision, "operator": operator,
            })

    def recheck(self, *, patient_id: str, visit_number: str, operator: dict,
                reason: str = "") -> dict:
        return self._request("POST", "/api/integrations/jhemr/rechecks", {
            "patient_id": patient_id, "visit_number": visit_number,
            "operator": operator, "reason": reason,
        })


def main() -> int:
    parser = argparse.ArgumentParser(description="JHEMR Mock 客户端（L1 演示）")
    parser.add_argument("--base", required=True)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--secret", required=True)
    parser.add_argument("--patient", default="TEST0002")
    parser.add_argument("--visit", default="1")
    args = parser.parse_args()

    client = JhemrClient(args.base, args.client_id, args.secret)
    operator = {"id": "DOC77", "name": "Mock医生"}

    created = client.create_submission_check(
        patient_id=args.patient, visit_number=args.visit,
        submission_id=f"MOCK-{uuid.uuid4().hex[:8]}", operator=operator)
    print("[1] create_submission_check:", created["status"],
          json.dumps(created["json"], ensure_ascii=False))
    check_id = created["json"].get("check_id")
    if not check_id:
        return 1

    result = client.poll_check(check_id, timeout_seconds=60)
    print("[2] get_check:", result.get("status"),
          "issues=", len(result.get("issues") or []),
          "summary.status=", (result.get("summary") or {}).get("status"))

    ticket = client.create_view_ticket(
        patient_id=args.patient, visit_number=args.visit,
        operator_id=operator["id"])
    print("[3] create_view_ticket:", ticket["status"],
          json.dumps(ticket["json"], ensure_ascii=False))

    issues = result.get("issues") or []
    if issues:
        target = issues[0]
        feedback = client.issue_feedback(
            issue_id=target["issue_id"], action="viewed", operator=operator,
            expect_issue_version=target.get("issue_version", 1))
        print("[4] issue_feedback(viewed):", feedback["status"],
              json.dumps(feedback["json"], ensure_ascii=False))

    rechecked = client.recheck(patient_id=args.patient,
                               visit_number=args.visit,
                               operator=operator, reason="Mock 整改复检")
    print("[5] recheck:", rechecked["status"],
          json.dumps(rechecked["json"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
