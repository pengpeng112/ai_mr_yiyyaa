"""仅监听回环地址的 Dify/Relay 合约 Mock。"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from app.demo_support.dataset import AUDIT_TYPE_BY_CODE, SYNTHETIC_LABEL


def _log_request(kind: str, payload: dict) -> None:
    log_dir = Path(os.getenv("LOG_DIR", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / f"mock_{kind}_requests.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": datetime.now().isoformat(), **payload}, ensure_ascii=False) + "\n")


def _structured_result(audit_type_code: str, body: dict) -> dict:
    spec = AUDIT_TYPE_BY_CODE.get(audit_type_code) or AUDIT_TYPE_BY_CODE["progress_vs_nursing"]
    input_text = str(((body.get("inputs") or {}).get("mr_txt") or ""))
    digest = int(hashlib.sha256(input_text.encode("utf-8")).hexdigest()[:4], 16)
    severity = ["high", "medium", "low"][digest % 3]
    risk_score = {"high": 86, "medium": 58, "low": 22}[severity]
    dimensions = []
    for index, code in enumerate(spec["dimensions"]):
        item_severity = severity if index == 0 else ("medium" if index == 1 and severity == "high" else "low")
        dimensions.append(
            {
                "dimension_code": code,
                "dimension_name": f"{spec['name']}维度{index + 1}",
                "status": "fail" if index == 0 and severity != "low" else "pass",
                "severity": item_severity,
                "confidence": round(0.96 - index * 0.05, 2),
                "alert_level": {"high": "red", "medium": "yellow", "low": "blue"}[item_severity],
                "closure_hours": {"high": 24, "medium": 72, "low": 0}[item_severity],
                "push_strategy": "immediate" if item_severity == "high" else "batch",
                "outcome_bucket": "primary" if index == 0 else "secondary",
                "issue_summary": f"脱敏合成测试问题：{code}" if index == 0 else "脱敏合成测试记录一致",
                "medical_evidence": ["测试病历证据，不来源于真实患者"],
                "nursing_evidence": ["测试护理证据，不来源于真实患者"],
                "recommendation": "请在隔离环境中完成测试整改与复核。" if index == 0 else "无需处理。",
            }
        )
    return {
        "version": "2.0",
        "patient_summary": {"patient_id": "SYNTH-MOCK", "visit_number": "1", "patient_name": "测试患者", "dept": "脱敏合成测试科室"},
        "audit_summary": {
            "has_inconsistency": severity != "low",
            "severity": severity,
            "risk_score": risk_score,
            "alert_level": {"high": "red", "medium": "yellow", "low": "blue"}[severity],
            "closure_hours": {"high": 24, "medium": 72, "low": 0}[severity],
            "push_strategy": "immediate" if severity == "high" else "batch",
            "outcome_bucket": "primary" if severity != "low" else "none",
            "overall_conclusion": f"{SYNTHETIC_LABEL}：已完成 {spec['name']}。",
            "overall_qc_summary": "本结果由本地 Mock Dify 生成，用于验证真实 API、持久化和闭环交互。",
            "focus_items": ["脱敏合成测试问题"],
            "reasoning_brief": "基于固定测试契约生成，不构成临床判断。",
        },
        "dimensions": dimensions,
    }


def create_dify_app() -> FastAPI:
    app = FastAPI(title="Med-Audit Demo Dify Mock")

    @app.post("/v1/workflows/run")
    async def workflow_run(
        request: Request,
        x_demo_audit_type: str = Header("progress_vs_nursing"),
        x_demo_scenario: str = Header("success"),
    ):
        body = await request.json()
        scenario = str((body.get("inputs") or {}).get("demo_scenario") or x_demo_scenario or "success")
        _log_request("dify", {"scenario": scenario, "audit_type_code": x_demo_audit_type, "body": body})
        if scenario == "timeout":
            import asyncio
            await asyncio.sleep(15)
        if scenario == "http_500":
            raise HTTPException(status_code=500, detail="synthetic failure")
        if scenario == "invalid_json":
            return Response(content="{invalid-json", media_type="application/json", status_code=200)
        run_key = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]
        outputs = {} if scenario == "empty_outputs" else {"aa": json.dumps(_structured_result(x_demo_audit_type, body), ensure_ascii=False)}
        return {"workflow_run_id": f"demo-wf-{run_key}", "task_id": f"demo-task-{run_key}", "data": {"outputs": outputs}}

    @app.get("/health")
    def health():
        return {"status": "healthy", "synthetic": True}

    return app


def create_relay_app() -> FastAPI:
    app = FastAPI(title="Med-Audit Demo Relay Mock")
    secret = os.getenv("DEMO_RELAY_SECRET", "demo-relay-secret-2026")
    internal_base = os.getenv("DEMO_APP_BASE_URL", "http://127.0.0.1:18080").rstrip("/")

    @app.post("/qc-record-alert")
    async def qc_record_alert(request: Request):
        raw = await request.body()
        timestamp = request.headers.get("X-Relay-Timestamp", "")
        actual = request.headers.get("X-Relay-Signature", "")
        expected = hmac.new(secret.encode("utf-8"), timestamp.encode("utf-8") + b"." + raw, hashlib.sha256).hexdigest()
        if not timestamp or not hmac.compare_digest(actual, expected):
            raise HTTPException(status_code=401, detail="invalid signature")
        payload = json.loads(raw.decode("utf-8"))
        _log_request("relay", {"headers": {"X-Relay-Timestamp": timestamp}, "body": payload})
        if payload.get("demo_scenario") == "http_500":
            raise HTTPException(status_code=500, detail="synthetic relay failure")
        return {"success": True, "message_id": f"demo-msg-{payload.get('alert_id', 'unknown')}", "synthetic": True}

    @app.get("/qc-detail/{alert_id}")
    def qc_detail(alert_id: int, token: str = ""):
        return RedirectResponse(f"{internal_base}/mobile/qc/{alert_id}?token={token}", status_code=307)

    @app.get("/api/mock/messages")
    def messages():
        path = Path(os.getenv("LOG_DIR", "logs")) / "mock_relay_requests.jsonl"
        if not path.exists():
            return {"items": [], "total": 0, "synthetic": True}
        items = [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]
        return {"items": items[-200:], "total": len(items), "synthetic": True}

    @app.get("/health")
    def health():
        return {"status": "healthy", "synthetic": True}

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Loopback-only demo integration mock")
    parser.add_argument("--kind", choices=["dify", "relay"], required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    if args.port < 1024 or args.port > 65535:
        raise SystemExit("port must be between 1024 and 65535")
    import uvicorn
    uvicorn.run(create_dify_app() if args.kind == "dify" else create_relay_app(), host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
