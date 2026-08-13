"""隔离测试辅助入口；核心业务页面仍使用真实认证和真实 API。"""
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models import User, QCFeedback, PushLog, Department
from app.demo_support.dataset import SYNTHETIC_LABEL
from app.services.isolated_mode import demo_mode_enabled, isolated_mode_enabled
from datetime import datetime, timedelta
import json

def require_isolated_demo() -> None:
    if not demo_mode_enabled() or not isolated_mode_enabled():
        raise HTTPException(status_code=403, detail="Demo mode disabled")


router = APIRouter(dependencies=[Depends(require_isolated_demo)])


@router.get("/api/demo/login")
def demo_login(db: Session = Depends(get_db)):
    """
    演示模式登录 - 返回演示用户的 Token
    用于本地测试，无需输入用户名密码
    """
    from app.auth import create_access_token
    
    demo_user = db.query(User).filter(User.username == "demo_admin", User.is_active.is_(True)).first()
    if not demo_user:
        raise HTTPException(status_code=503, detail="Synthetic demo user not seeded")
    token = create_access_token(user_id=demo_user.id, username=demo_user.username)
    
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": demo_user.id,
            "username": demo_user.username,
            "full_name": demo_user.full_name,
            "role": "admin",
            "dept_id": None,
        },
        "message": SYNTHETIC_LABEL,
        "synthetic": True,
    }


@router.get("/api/demo/dashboard")
def demo_dashboard(db: Session = Depends(get_db)):
    """
    演示仪表板 - 显示系统统计信息
    """
    try:
        # 获取反馈统计
        total_feedback = db.query(QCFeedback).count()
        high_severity = db.query(QCFeedback).filter(QCFeedback.severity == "high").count()
        medium_severity = db.query(QCFeedback).filter(QCFeedback.severity == "medium").count()
        low_severity = db.query(QCFeedback).filter(QCFeedback.severity == "low").count()
        
        pending = db.query(QCFeedback).filter(QCFeedback.status == "pending").count()
        acknowledged = db.query(QCFeedback).filter(QCFeedback.status == "acknowledged").count()
        rectified = db.query(QCFeedback).filter(QCFeedback.status == "rectified").count()
        closed = db.query(QCFeedback).filter(QCFeedback.status == "closed").count()
        
        # 获取推送日志统计
        total_push = db.query(PushLog).count()
        success_push = db.query(PushLog).filter(PushLog.status == "success").count()
        
        return {
            "status": "success",
            "data": {
                "feedback_stats": {
                    "total": total_feedback,
                    "by_severity": {
                        "high": high_severity,
                        "medium": medium_severity,
                        "low": low_severity,
                    },
                    "by_status": {
                        "pending": pending,
                        "acknowledged": acknowledged,
                        "rectified": rectified,
                        "closed": closed,
                    }
                },
                "push_stats": {
                    "total": total_push,
                    "success": success_push,
                    "success_rate": f"{(success_push/total_push*100):.1f}%" if total_push > 0 else "0%"
                }
            }
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


@router.get("/api/demo/feedback-list")
def demo_feedback_list(db: Session = Depends(get_db)):
    """
    演示反馈列表 - 显示所有反馈
    """
    try:
        feedbacks = db.query(QCFeedback).limit(10).all()
        
        result = []
        for fb in feedbacks:
            push_log = db.query(PushLog).filter(PushLog.id == fb.push_log_id).first()
            result.append({
                "id": fb.id,
                "patient_id": push_log.patient_id if push_log else "N/A",
                "patient_name": push_log.patient_name if push_log else "N/A",
                "severity": fb.severity,
                "status": fb.status,
                "feedback_text": fb.feedback_text,
                "created_at": fb.created_at.isoformat() if fb.created_at is not None else None,
            })
        
        return {
            "status": "success",
            "total": len(result),
            "data": result
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


@router.get("/api/demo/departments")
def demo_departments(db: Session = Depends(get_db)):
    """
    演示科室列表
    """
    try:
        depts = db.query(Department).all()
        
        result = []
        for dept in depts:
            feedback_count = db.query(QCFeedback).filter(QCFeedback.dept_id == dept.id).count()
            result.append({
                "id": dept.id,
                "name": dept.name,
                "code": dept.code,
                "feedback_count": feedback_count,
            })
        
        return {
            "status": "success",
            "total": len(result),
            "data": result
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


@router.get("/api/demo/stats")
def demo_stats(db: Session = Depends(get_db)):
    """
    演示统计数据 - 多维度统计
    """
    try:
        # 按严重程度统计
        severity_stats = {}
        for severity in ["high", "medium", "low"]:
            count = db.query(QCFeedback).filter(QCFeedback.severity == severity).count()
            severity_stats[severity] = count
        
        # 按状态统计
        status_stats = {}
        for status in ["pending", "acknowledged", "rectified", "closed"]:
            count = db.query(QCFeedback).filter(QCFeedback.status == status).count()
            status_stats[status] = count
        
        # 按科室统计
        dept_stats = []
        depts = db.query(Department).all()
        for dept in depts:
            count = db.query(QCFeedback).filter(QCFeedback.dept_id == dept.id).count()
            if count > 0:
                dept_stats.append({
                    "dept_name": dept.name,
                    "count": count
                })
        
        # 每日趋势（最近 7 天）
        daily_trend = []
        for i in range(7):
            date = (datetime.now() - timedelta(days=i)).date()
            count = db.query(QCFeedback).filter(
                func.date(QCFeedback.created_at) == date
            ).count()
            daily_trend.append({
                "date": str(date),
                "count": count
            })
        
        return {
            "status": "success",
            "data": {
                "severity_distribution": severity_stats,
                "status_distribution": status_stats,
                "dept_distribution": dept_stats,
                "daily_trend": daily_trend[::-1],  # 反转为升序
            }
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


@router.get("/api/demo/info")
def demo_info():
    """
    演示模式信息 - 说明如何使用演示模式
    """
    return {
        "status": "success",
        "message": SYNTHETIC_LABEL,
        "synthetic": True,
        "run_id": os.getenv("DEMO_RUN_ID", ""),
        "endpoints": {
            "login": "/api/demo/login - 获取演示 Token",
            "dashboard": "/api/demo/dashboard - 查看仪表板统计",
            "feedback_list": "/api/demo/feedback-list - 查看反馈列表",
            "departments": "/api/demo/departments - 查看科室列表",
            "stats": "/api/demo/stats - 查看多维度统计",
            "info": "/api/demo/info - 查看演示模式信息",
        },
        "quick_start": {
            "step1": "访问 /api/demo/login 获取演示 Token",
            "step2": "在请求头中添加: Authorization: Bearer <token>",
            "step3": "访问其他演示端点查看数据",
        },
        "credentials_file": "config/demo/<run_id>/credentials.json",
    }


@router.get("/api/demo/manifest")
def demo_manifest():
    from app.config import CONFIG_DIR

    path = Path(CONFIG_DIR) / "manifest.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Synthetic manifest not found")
    payload = json.loads(path.read_text("utf-8"))
    payload["synthetic"] = True
    return payload


@router.get("/api/demo/credentials")
def demo_credentials():
    return {
        "synthetic": True,
        "username": "demo_admin",
        "password": "Demo-12Dept!2026",
        "warning": "仅限当前本机隔离测试运行",
    }


@router.get("/demo-test", response_class=HTMLResponse, include_in_schema=False)
def demo_test_center():
    run_id = os.getenv("DEMO_RUN_ID", "")
    return HTMLResponse(f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>12科室脱敏合成测试环境</title><style>
body{{font-family:system-ui;margin:0;background:#f4f7fb;color:#172033}}main{{max-width:920px;margin:40px auto;padding:28px;background:#fff;border-radius:16px;box-shadow:0 12px 40px #19325b18}}
.warn{{padding:14px 18px;border:2px solid #f59e0b;background:#fffbeb;color:#92400e;border-radius:10px;font-weight:700}}a,button{{display:inline-block;margin:14px 10px 0 0;padding:10px 16px;border:0;border-radius:8px;background:#155eef;color:white;text-decoration:none;cursor:pointer}}pre{{white-space:pre-wrap;background:#0f172a;color:#dbeafe;padding:16px;border-radius:10px;max-height:55vh;overflow:auto}}
</style></head><body><main><div class="warn">{SYNTHETIC_LABEL}</div><h1>12 科室交互测试中心</h1><p>run_id：{run_id}。核心页面为 Vue → FastAPI → 独立 SQLite；Dify/Relay 使用回环 HTTP Mock。</p>
<a href="/ui-next/">进入真实可点击系统</a><a href="/docs">查看 API</a><button onclick="loadManifest()">核对本次数据口径</button><pre id="out">点击按钮读取同源 manifest</pre>
<script>async function loadManifest(){{const r=await fetch('/api/demo/manifest');document.getElementById('out').textContent=JSON.stringify(await r.json(),null,2)}}</script></main></body></html>""")
