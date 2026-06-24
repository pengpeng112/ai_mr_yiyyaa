"""
前置机推送人员配置管理接口 —— 查看规则 + 预览接收人 + 保存规则 + 搜索人员
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import load_config, update_section
from app.models import PushLog, User
from app.permissions import require_permission
from app.services.relay_alert_service import (
    RelayAlertService, _get_patient_info,
    _is_oracle_data_source, _get_oracle_connection_from_config,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_manage_config(current_user: User = Depends(require_permission("manage_config"))):
    return current_user


class PreviewRequest(BaseModel):
    push_log_id: int = Field(..., description="推送日志ID")
    severity: str = Field(default="high", description="严重度 high/medium/low")


class FixedUser(BaseModel):
    userid: str = Field(..., description="人员 userid")
    user_name: str = Field("", description="人员姓名")


class SeverityRule(BaseModel):
    attending_doctor: bool = Field(True, description="是否推管床医生")
    record_creator: bool = Field(True, description="是否推病历创建医师")
    nurse_head: bool = Field(True, description="是否推护士长")
    fixed_users: list[FixedUser] = Field(default_factory=list, description="固定推送人员")
    dedupe: bool = Field(True, description="是否去重")
    max_receivers: int = Field(10, ge=0, le=50, description="最大接收人数，0=不限")


class SaveReceiverRulesRequest(BaseModel):
    rules: dict[str, SeverityRule] = Field(..., description="按严重度配置的接收人规则")


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


# ── 搜索人员（用于前端选择固定推送人员）──

@router.get("/search-user", summary="按姓名模糊搜索人员")
def search_user(
    name: str = Query(..., min_length=1, max_length=20, description="姓名关键词"),
    _user: User = Depends(_require_manage_config),
):
    if not _is_oracle_data_source():
        return {"keyword": name, "results": []}
    conn = None
    cur = None
    results: list[dict] = []
    try:
        conn = _get_oracle_connection_from_config()
        cur = conn.cursor()
        cur.execute(
            "SELECT userid, user_name, remark FROM ODS.V_AI_ZKUSER WHERE user_name LIKE :n AND ROWNUM <= 20",
            {"n": f"%{name.strip()}%"},
        )
        for row in cur.fetchall():
            results.append({
                "userid": str(row[0] or ""),
                "user_name": str(row[1] or ""),
                "remark": str(row[2] or ""),
            })
    except Exception as exc:
        logger.warning("[relay_config] search-user failed: %s", exc, exc_info=True)
    finally:
        if cur is not None:
            try: cur.close()
            except Exception: pass
        if conn is not None:
            try: conn.close()
            except Exception: pass
    return {"keyword": name, "results": results}


# ── 保存推送人员规则 ──

@router.post("/receiver-rules", summary="保存推送人员接收规则")
def save_receiver_rules(
    body: SaveReceiverRulesRequest,
    current_user: User = Depends(_require_manage_config),
):
    current = load_config().get("relay_alert", {})
    merged_rules: dict[str, dict] = {}
    for severity, rule in body.rules.items():
        merged_rules[severity] = {
            "attending_doctor": rule.attending_doctor,
            "record_creator": rule.record_creator,
            "nurse_head": rule.nurse_head,
            "fixed_users": [{"userid": u.userid, "user_name": u.user_name} for u in rule.fixed_users],
            "dedupe": rule.dedupe,
            "max_receivers": rule.max_receivers,
        }
    merged = {**current, "receiver_rules": merged_rules}
    update_section("relay_alert", merged)
    logger.info(
        "[AUDIT] 用户=%s id=%s 保存推送人员规则 severities=%s",
        current_user.username, current_user.id, list(merged_rules.keys()),
    )
    return {"message": "推送人员规则已保存", "rules": merged_rules}
