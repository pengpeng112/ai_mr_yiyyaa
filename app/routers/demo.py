"""
演示模式 - 无需登录直接查看系统功能
在 main.py 中添加此路由，可以跳过认证直接访问演示数据
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, QCFeedback, PushLog, Department
from datetime import datetime, timedelta
import json

router = APIRouter()


@router.get("/api/demo/login")
def demo_login():
    """
    演示模式登录 - 返回演示用户的 Token
    用于本地测试，无需输入用户名密码
    """
    from app.auth import create_access_token
    
    # 创建演示 Token（有效期 24 小时）
    demo_user = {
        "id": 0,
        "username": "demo_user",
        "full_name": "演示用户",
        "role": "admin",
        "dept_id": None,
    }
    
    # 修复：使用正确的参数签名 create_access_token(user_id, username)
    token = create_access_token(user_id=0, username="demo_user")
    
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": demo_user,
        "message": "演示模式已启用，可直接查看系统功能"
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
                "created_at": fb.created_at.isoformat() if fb.created_at else None,
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
                db.func.date(QCFeedback.created_at) == date
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
        "message": "演示模式已启用",
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
        "default_users": {
            "admin": {"password": "admin123", "role": "管理员"},
            "manager_xnk": {"password": "manager123", "role": "科室主任"},
            "doctor_001": {"password": "doctor123", "role": "医生"},
            "auditor_001": {"password": "auditor123", "role": "审计员"},
        }
    }
