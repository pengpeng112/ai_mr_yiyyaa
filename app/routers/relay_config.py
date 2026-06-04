"""
前置机推送人员配置管理接口 —— 查看规则 + 预览接收人
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import load_config
from app.models import PushLog, User
from app.permissions import require_permission
from app.services.relay_alert_service import RelayAlertService, _get_patient_info

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_manage_config(current_user: User = Depends(require_permission("manage_config"))):
    return current_user


class PreviewRequest(BaseModel):
    push_log_id: int = Field(..., description="推送日志ID")
    severity: str = Field(default="high", description="严重度 high/medium/low")


# ── 查看当前人员配置 ──

@router.get("/receiver-config", summary="查看推送人员配置规则")
def get_receiver_config(_user: User = Depends(_require_manage_config)):
    cfg = load_config()
    relay = cfg.get("relay_alert", {})
    return {
        "enabled": relay.get("enabled", False),
        "severity_levels": relay.get("severity_levels", []),
        "receiver_rules": relay.get("receiver_rules", {}),
        "nurse_heads": relay.get("nurse_heads", []),
        "detail_page": relay.get("detail_page", {}),
        "source": relay.get("source", ""),
        "base_url": relay.get("base_url", ""),
    }


# ── 预览指定推送记录的接收人 ──

@router.post("/preview-receivers", summary="预览推送记录会推送给哪些人")
def preview_receivers(body: PreviewRequest, db: Session = Depends(get_db), _user: User = Depends(_require_manage_config)):
    log = db.query(PushLog).filter(PushLog.id == body.push_log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="推送记录不存在")

    config = load_config()
    svc = RelayAlertService(db, config)

    patient_info = _get_patient_info(log)
    receivers, debug = svc._build_receivers(patient_info, log, body.severity)

    return {
        "push_log_id": body.push_log_id,
        "patient_id": log.patient_id or "",
        "patient_name": log.patient_name or "",
        "audit_type_code": getattr(log, "audit_type_code", "") or "",
        "severity": body.severity,
        "patient_info": {
            "doctor_id": patient_info.get("doctor_id", ""),
            "doctor_name": patient_info.get("doctor_name", ""),
            "dept": patient_info.get("dept", ""),
            "dept_code": patient_info.get("dept_code", ""),
            "nurse_head_userid": patient_info.get("nurse_head_userid", ""),
        },
        "receivers": receivers,
        "receiver_debug": debug,
        "rule": debug.get("rule", ""),
    }


# ── 按科室编码/名称测试护理负责人查询 ──

@router.get("/test-nurse-head", summary="按科室查询护理负责人")
def test_nurse_head(
    dept_code: str = Query(default="", description="科室编码"),
    dept_name: str = Query(default="", description="科室名称"),
    _user: User = Depends(_require_manage_config),
):
    from app.services.relay_alert_service import _query_personnel_by_dept
    result = _query_personnel_by_dept(dept_code=dept_code, dept_name=dept_name)
    return {
        "dept_code": dept_code,
        "dept_name": dept_name,
        "nurse_head": result if result else None,
        "found": bool(result),
    }
