"""
医生端 H5 页面与反馈接口
无需系统用户登录，通过 HMAC token 验证。
"""
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    QCRecordAlertLog,
    QCAlertFeedback,
    PushLog,
    AuditDimensionResult,
    AuditConclusion,
)
from app.services.alert_token import verify_alert_token
from app.config import load_config

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------- helpers ----------

def _get_token_secret() -> str:
    cfg = load_config().get("relay_alert") or {}
    secret = (cfg.get("secret_key") or "").strip()
    if secret:
        return secret
    enc = (cfg.get("secret_key_enc") or "").strip()
    if enc:
        try:
            from app.config import decrypt_value
            return decrypt_value(enc)
        except Exception:
            logger.warning("[mobile_qc] secret_key_enc decrypt failed")
            return ""
    return ""


def _verify(token: str, path_alert_id: int) -> QCRecordAlertLog:
    """验证 token 并返回 alert log，任何失败抛 HTTPException。"""
    if not token:
        raise HTTPException(status_code=400, detail="token required")
    secret = _get_token_secret()
    token_alert_id = verify_alert_token(token, secret)
    if token_alert_id is None:
        raise HTTPException(status_code=401, detail="token invalid or expired")
    if token_alert_id != path_alert_id:
        raise HTTPException(status_code=401, detail="token mismatch")
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        alert = db.query(QCRecordAlertLog).filter(QCRecordAlertLog.id == path_alert_id).first()
        if not alert:
            raise HTTPException(status_code=404, detail="alert not found")
        return alert
    finally:
        db.close()


# ---------- H5 页面 ----------

@router.get("/mobile/qc/{alert_id}", response_class=HTMLResponse, summary="医生端质控详情 H5 页面")
def mobile_qc_page(alert_id: int, token: str = ""):
    """返回手机端 H5 页面。token 无效时返回错误页，防止未授权访问。"""
    # token 校验
    if not token:
        return HTMLResponse(content=_error_html("缺少访问令牌，请从企业微信消息中打开"), status_code=400)
    secret = _get_token_secret()
    if not secret:
        return HTMLResponse(content=_error_html("访问令牌配置异常，请联系管理员"), status_code=401)
    token_alert_id = verify_alert_token(token, secret)
    if token_alert_id is None:
        return HTMLResponse(content=_error_html("链接已过期或无效，请重新从企业微信消息中打开"), status_code=401)
    if token_alert_id != alert_id:
        return HTMLResponse(content=_error_html("访问令牌与质控记录不匹配"), status_code=401)

    import pathlib
    html_path = pathlib.Path(__file__).resolve().parent.parent.parent / "static" / "templates" / "mobile" / "qc_detail.html"
    if not html_path.exists():
        raise HTTPException(status_code=500, detail="H5 page not found")
    html = html_path.read_text("utf-8")
    html = html.replace("__ALERT_ID__", str(alert_id)).replace("__TOKEN__", token)
    return HTMLResponse(content=html)


def _error_html(message: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>病历质控</title>
<style>
body{{margin:0;display:flex;align-items:center;justify-content:center;min-height:100vh;font-family:-apple-system,sans-serif;background:#f2f6fb;color:#475569}}
.msg{{text-align:center;padding:24px}}h2{{color:#dc2626;margin:0 0 8px}}p{{margin:0;font-size:15px}}
</style>
</head>
<body><div class="msg"><h2>!</h2><p>{message}</p></div></body>
</html>"""


# ---------- API: 获取详情 ----------

@router.get("/api/mobile/qc-detail/{alert_id}", summary="获取质控详情（H5 数据接口）")
def get_qc_detail(
    alert_id: int,
    request: Request,
    token: str = "",
    viewer_userid: str = "",
    viewer_name: str = "",
    db: Session = Depends(get_db),
):
    alert = _verify_token_and_get_alert(token, alert_id, db)

    try:
        _mark_alert_viewed(alert, request, viewer_userid, viewer_name)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("[mobile_qc] mark viewed failed alert_id=%s err=%s", alert_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="查看状态记录失败，请联系管理员")

    push_log = db.query(PushLog).filter(PushLog.id == alert.push_log_id).first()
    dimension = db.query(AuditDimensionResult).filter(
        AuditDimensionResult.push_log_id == alert.push_log_id,
        AuditDimensionResult.dimension_code == alert.dimension_code,
    ).first()
    if not dimension:
        dimension = db.query(AuditDimensionResult).filter(
            AuditDimensionResult.push_log_id == alert.push_log_id,
        ).first()
    conclusion = db.query(AuditConclusion).filter(
        AuditConclusion.push_log_id == alert.push_log_id,
    ).first()
    feedback = db.query(QCAlertFeedback).filter(
        QCAlertFeedback.alert_log_id == alert.id,
    ).first()

    from app.utils.json_utils import safe_json_dumps
    from app.services.patient_snapshot import extract_patient_snapshot

    snapshot = extract_patient_snapshot(push_log) if push_log else {}
    payload_data = json.loads(alert.payload_json or "{}") if alert.payload_json else {}

    return {
        "alert": {
            "id": alert.id,
            "patient_name": push_log.patient_name if push_log else "",
            "admission_no": push_log.admission_no if push_log else "",
            "dept": alert.dept or (push_log.dept if push_log else ""),
            "doctor_name": _extract_doctor_name(alert, push_log),
            "dimension": dimension.dimension if dimension else "",
            "alert_level": alert.alert_level or "",
            "severity": alert.severity or "",
            "closure_hours": getattr(dimension, "closure_hours", 0) if dimension else (getattr(conclusion, "closure_hours", 0) if conclusion else 0),
            "created_at": alert.created_at.strftime("%Y-%m-%d %H:%M:%S") if alert.created_at else "",
            "admission_date": snapshot.get("admission_date") or "",
            "discharge_date": snapshot.get("discharge_date") or "",
            "admission_dept_name": snapshot.get("admission_dept_name") or "",
            "discharge_dept_name": snapshot.get("discharge_dept_name") or "",
        },
        "dimension_detail": {
            "issue_summary": getattr(dimension, "issue_summary", "") or "" if dimension else "",
            "recommendation": getattr(dimension, "recommendation", "") or "" if dimension else "",
            "explanation": getattr(dimension, "explanation", "") or "" if dimension else "",
            "confidence": getattr(dimension, "confidence", 0) or 0 if dimension else 0,
            "medical_content": getattr(dimension, "medical_content", "") or "" if dimension else "",
            "nursing_content": getattr(dimension, "nursing_content", "") or "" if dimension else "",
        },
        "conclusion": {
            "overall_conclusion": getattr(conclusion, "overall_conclusion", "") or "" if conclusion else "",
            "risk_score": getattr(conclusion, "risk_score", 0) or 0 if conclusion else 0,
            "reasoning_brief": getattr(conclusion, "reasoning_brief", "") or "" if conclusion else "",
        },
        "feedback": {
            "action": feedback.action if feedback else None,
            "action_label": _feedback_action_label(feedback.action) if feedback else "",
            "doctor_id": feedback.doctor_id if feedback else "",
            "doctor_name": feedback.doctor_name if feedback else "",
            "dept": feedback.dept if feedback else "",
            "reason": feedback.reason if feedback else "",
            "rectification_text": feedback.rectification_text if feedback else "",
            "created_at": feedback.created_at.strftime("%Y-%m-%d %H:%M:%S") if feedback and feedback.created_at else None,
        },
        "view_status": {
            "viewed_flag": int(alert.viewed_flag or 0),
            "viewed_at": alert.viewed_at.strftime("%Y-%m-%d %H:%M:%S") if alert.viewed_at else "",
            "last_viewed_at": alert.last_viewed_at.strftime("%Y-%m-%d %H:%M:%S") if alert.last_viewed_at else "",
            "view_count": int(alert.view_count or 0),
            "viewer_userid": alert.viewer_userid or "",
            "viewer_name": alert.viewer_name or "",
        },
        "evidence": {
            "summary": payload_data.get("evidence_summary") or payload_data.get("evidence_title") or "",
            "titles": payload_data.get("evidence_titles") or {},
        },
    }


def _feedback_action_label(action: str) -> str:
    if action == "acknowledged":
        return "已知晓"
    if action == "rectified":
        return "已处理"
    if action == "other":
        return "其他原因"
    return action or ""


def _extract_doctor_name(alert: QCRecordAlertLog, push_log: PushLog | None) -> str:
    try:
        payload = json.loads(alert.payload_json or "{}")
        return payload.get("doctor_name") or ""
    except Exception:
        pass
    if push_log:
        try:
            req = json.loads(push_log.request_json or "{}")
            pi = req.get("patient_info", {})
            return pi.get("管床医师") or pi.get("doctor_name") or ""
        except Exception:
            pass
    return ""


def _verify_token_and_get_alert(token: str, alert_id: int, db: Session) -> QCRecordAlertLog:
    if not token:
        raise HTTPException(status_code=400, detail="token required")
    secret = _get_token_secret()
    if not secret:
        raise HTTPException(status_code=401, detail="token secret not configured")
    token_alert_id = verify_alert_token(token, secret)
    if token_alert_id is None:
        raise HTTPException(status_code=401, detail="token invalid or expired")
    if token_alert_id != alert_id:
        raise HTTPException(status_code=401, detail="token mismatch")
    alert = db.query(QCRecordAlertLog).filter(QCRecordAlertLog.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="alert not found")
    return alert


def _mark_alert_viewed(
    alert: QCRecordAlertLog,
    request: Request,
    viewer_userid: str = "",
    viewer_name: str = "",
) -> None:
    now = datetime.now()
    if not getattr(alert, "viewed_flag", 0):
        alert.viewed_flag = 1
        alert.viewed_at = now
    alert.last_viewed_at = now
    alert.view_count = int(alert.view_count or 0) + 1
    header_userid = request.headers.get("X-WeCom-UserId", "") if request else ""
    header_name = request.headers.get("X-WeCom-UserName", "") if request else ""
    alert.viewer_userid = viewer_userid or header_userid or alert.viewer_userid or ""
    alert.viewer_name = viewer_name or header_name or alert.viewer_name or ""
    alert.viewer_ip = request.client.host if request and request.client else ""
    alert.viewer_user_agent = (request.headers.get("user-agent", "") if request else "")[:500]


# ---------- API: 提交反馈 ----------

class FeedbackRequest(BaseModel):
    alert_id: int = Field(..., description="质控记录 ID")
    token: str = Field(..., description="签名 token")
    action: str = Field(..., description="acknowledged / rectified / other")
    reason: str = Field("", description="其他原因说明（action=other 时必填）")
    rectification_text: str = Field("", description="整改说明（action=rectified 时必填）")
    viewer_userid: str = Field("", description="企业微信用户ID（前置机透传）")
    viewer_name: str = Field("", description="企业微信用户姓名（前置机透传）")


@router.post("/api/mobile/qc-feedback", summary="提交医生反馈（H5 用）")
def submit_feedback(body: FeedbackRequest, request: Request, db: Session = Depends(get_db)):
    if body.action not in ("acknowledged", "rectified", "other"):
        raise HTTPException(status_code=400, detail="invalid action")
    if body.action == "other" and not (body.reason or "").strip():
        raise HTTPException(status_code=400, detail="其他原因需要填写说明")
    if body.action == "rectified" and not (body.rectification_text or "").strip():
        raise HTTPException(status_code=400, detail="已处理需要填写整改说明")

    alert = _verify_token_and_get_alert(body.token, body.alert_id, db)

    existing = db.query(QCAlertFeedback).filter(QCAlertFeedback.alert_log_id == alert.id).first()
    if existing:
        raise HTTPException(status_code=409, detail="已反馈，不可重复提交")

    # 读取提交人：body 优先 → header 次之 → payload 兜底
    doctor_id = body.viewer_userid or request.headers.get("X-WeCom-UserId", "")
    doctor_name = body.viewer_name or request.headers.get("X-WeCom-UserName", "")
    viewer_dept = request.headers.get("X-WeCom-DeptName", "") or request.headers.get("X-WeCom-Dept", "")
    if not doctor_name:
        try:
            payload = json.loads(alert.payload_json or "{}")
            doctor_id = doctor_id or payload.get("doctor_id") or ""
            doctor_name = payload.get("doctor_name") or ""
        except Exception:
            pass
    if not doctor_name:
        doctor_name = "未知人员"

    client_ip = request.client.host if request.client else ""
    user_agent = request.headers.get("user-agent", "")

    feedback = QCAlertFeedback(
        alert_log_id=alert.id,
        push_log_id=alert.push_log_id,
        dimension_code=alert.dimension_code,
        action=body.action,
        status="submitted",
        doctor_id=doctor_id,
        doctor_name=doctor_name,
        dept=viewer_dept or alert.dept or "",
        reason=body.reason.strip() if body.action == "other" else "",
        rectification_text=body.rectification_text.strip() if body.action == "rectified" else "",
        client_ip=client_ip,
        user_agent=user_agent[:500] if user_agent else "",
    )
    db.add(feedback)
    db.commit()
    logger.info("[mobile_qc] feedback alert_id=%s action=%s", alert.id, body.action)
    return {"ok": True, "message": "反馈已提交"}


# ---------- API: 健康检查 ----------

@router.get("/api/mobile/qc-detail/{alert_id}/verify-token", summary="验证 token 有效性")
def verify_token(alert_id: int, token: str = ""):
    secret = _get_token_secret()
    token_alert_id = verify_alert_token(token, secret)
    if token_alert_id is None or token_alert_id != alert_id:
        return {"valid": False}
    return {"valid": True, "alert_id": alert_id}
