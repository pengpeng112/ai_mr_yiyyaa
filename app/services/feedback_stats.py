"""
反馈统计服务
提供反馈统计、分析、趋势等功能
"""
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from app.models import QCFeedback, Department, User

class FeedbackStatsService:
    """反馈统计服务"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_total_stats(self, dept_id: Optional[int] = None) -> Dict:
        """获取总体统计 —— 单次聚合查询替代 8 次 COUNT"""
        query = self.db.query(
            func.count(QCFeedback.id).label("total"),
            func.sum(func.case((QCFeedback.severity == "high", 1), else_=0)).label("high"),
            func.sum(func.case((QCFeedback.severity == "medium", 1), else_=0)).label("medium"),
            func.sum(func.case((QCFeedback.severity == "low", 1), else_=0)).label("low"),
            func.sum(func.case((QCFeedback.status == "pending", 1), else_=0)).label("pending"),
            func.sum(func.case((QCFeedback.status == "acknowledged", 1), else_=0)).label("acknowledged"),
            func.sum(func.case((QCFeedback.status == "rectified", 1), else_=0)).label("rectified"),
            func.sum(func.case((QCFeedback.status == "closed", 1), else_=0)).label("closed"),
        )
        
        if dept_id:
            query = query.filter(QCFeedback.dept_id == dept_id)
        
        row = query.one()
        
        return {
            "total": row.total or 0,
            "high": row.high or 0,
            "medium": row.medium or 0,
            "low": row.low or 0,
            "pending": row.pending or 0,
            "acknowledged": row.acknowledged or 0,
            "rectified": row.rectified or 0,
            "closed": row.closed or 0,
        }
    
    def get_severity_distribution(self, dept_id: Optional[int] = None) -> List[Dict]:
        """获取严重程度分布"""
        query = self.db.query(
            QCFeedback.severity,
            func.count(QCFeedback.id).label("count")
        )
        
        if dept_id:
            query = query.filter(QCFeedback.dept_id == dept_id)
        
        query = query.group_by(QCFeedback.severity)
        
        result = []
        for severity, count in query.all():
            result.append({
                "severity": severity,
                "count": count,
                "percentage": 0  # 后续计算
            })
        
        # 计算百分比
        total = sum(item["count"] for item in result)
        if total > 0:
            for item in result:
                item["percentage"] = round(item["count"] / total * 100, 2)
        
        return result
    
    def get_status_distribution(self, dept_id: Optional[int] = None) -> List[Dict]:
        """获取状态分布"""
        query = self.db.query(
            QCFeedback.status,
            func.count(QCFeedback.id).label("count")
        )
        
        if dept_id:
            query = query.filter(QCFeedback.dept_id == dept_id)
        
        query = query.group_by(QCFeedback.status)
        
        result = []
        for status, count in query.all():
            result.append({
                "status": status,
                "count": count,
                "percentage": 0
            })
        
        # 计算百分比
        total = sum(item["count"] for item in result)
        if total > 0:
            for item in result:
                item["percentage"] = round(item["count"] / total * 100, 2)
        
        return result
    
    def get_dept_distribution(self) -> List[Dict]:
        """获取科室分布"""
        query = self.db.query(
            Department.name,
            func.count(QCFeedback.id).label("total"),
            func.sum(
                func.case(
                    (QCFeedback.severity == "high", 1),
                    else_=0
                )
            ).label("high_count"),
            func.sum(
                func.case(
                    (QCFeedback.status == "pending", 1),
                    else_=0
                )
            ).label("pending_count"),
        ).join(
            Department, QCFeedback.dept_id == Department.id
        ).group_by(Department.id, Department.name)
        
        result = []
        for dept_name, total, high_count, pending_count in query.all():
            result.append({
                "dept_name": dept_name,
                "total": total or 0,
                "high": high_count or 0,
                "pending": pending_count or 0,
            })
        
        return result
    
    def get_daily_trend(self, days: int = 30, dept_id: Optional[int] = None) -> List[Dict]:
        """获取每日趋势"""
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days)
        
        query = self.db.query(
            func.date(QCFeedback.created_at).label("date"),
            func.count(QCFeedback.id).label("total"),
            func.sum(
                func.case(
                    (QCFeedback.status == "pending", 1),
                    else_=0
                )
            ).label("pending"),
            func.sum(
                func.case(
                    (QCFeedback.status == "rectified", 1),
                    else_=0
                )
            ).label("rectified"),
        ).filter(
            QCFeedback.created_at >= start_date
        )
        
        if dept_id:
            query = query.filter(QCFeedback.dept_id == dept_id)
        
        query = query.group_by(func.date(QCFeedback.created_at)).order_by(
            func.date(QCFeedback.created_at)
        )
        
        result = []
        for date, total, pending, rectified in query.all():
            result.append({
                "date": str(date),
                "total": total or 0,
                "pending": pending or 0,
                "rectified": rectified or 0,
            })
        
        return result
    
    def get_avg_rectification_time(self, dept_id: Optional[int] = None) -> Dict:
        """获取平均整改时间"""
        query = self.db.query(QCFeedback).filter(
            QCFeedback.rectification_date.isnot(None)
        )
        
        if dept_id:
            query = query.filter(QCFeedback.dept_id == dept_id)
        
        feedbacks = query.all()
        
        if not feedbacks:
            return {
                "avg_days": 0,
                "min_days": 0,
                "max_days": 0,
                "total_rectified": 0,
            }
        
        times = []
        for fb in feedbacks:
            days = (fb.rectification_date - fb.created_at).days
            times.append(days)
        
        return {
            "avg_days": round(sum(times) / len(times), 2),
            "min_days": min(times),
            "max_days": max(times),
            "total_rectified": len(times),
        }
    
    def get_top_issues(self, limit: int = 10, dept_id: Optional[int] = None) -> List[Dict]:
        """获取高频问题"""
        query = self.db.query(
            QCFeedback.feedback_text,
            func.count(QCFeedback.id).label("count")
        ).filter(
            QCFeedback.feedback_text.isnot(None),
            QCFeedback.feedback_text != ""
        )
        
        if dept_id:
            query = query.filter(QCFeedback.dept_id == dept_id)
        
        query = query.group_by(QCFeedback.feedback_text).order_by(
            func.count(QCFeedback.id).desc()
        ).limit(limit)
        
        result = []
        for text, count in query.all():
            result.append({
                "issue": text[:100],  # 截断长文本
                "count": count,
            })
        
        return result
    
    def get_user_workload(self, dept_id: Optional[int] = None) -> List[Dict]:
        """获取用户工作量"""
        query = self.db.query(
            User.full_name,
            func.count(QCFeedback.id).label("assigned_count"),
            func.sum(
                func.case(
                    (QCFeedback.status == "pending", 1),
                    else_=0
                )
            ).label("pending_count"),
        ).join(
            QCFeedback, QCFeedback.assigned_to == User.id
        )
        
        if dept_id:
            query = query.filter(QCFeedback.dept_id == dept_id)
        
        query = query.group_by(User.id, User.full_name).order_by(
            func.count(QCFeedback.id).desc()
        )
        
        result = []
        for name, assigned, pending in query.all():
            result.append({
                "user_name": name,
                "assigned_count": assigned or 0,
                "pending_count": pending or 0,
                "completed_count": (assigned or 0) - (pending or 0),
            })
        
        return result
    
    def get_rectification_rate(self, dept_id: Optional[int] = None) -> Dict:
        """获取整改率"""
        query = self.db.query(QCFeedback)
        
        if dept_id:
            query = query.filter(QCFeedback.dept_id == dept_id)
        
        total = query.count()
        if total == 0:
            return {
                "total": 0,
                "rectified": 0,
                "rate": 0,
            }
        
        rectified = query.filter(QCFeedback.status == "rectified").count()
        
        return {
            "total": total,
            "rectified": rectified,
            "rate": round(rectified / total * 100, 2),
        }
    
    def get_dashboard_stats(self, dept_id: Optional[int] = None) -> Dict:
        """获取仪表板统计（综合所有数据）"""
        return {
            "total_stats": self.get_total_stats(dept_id),
            "severity_distribution": self.get_severity_distribution(dept_id),
            "status_distribution": self.get_status_distribution(dept_id),
            "dept_distribution": self.get_dept_distribution() if not dept_id else [],
            "daily_trend": self.get_daily_trend(30, dept_id),
            "avg_rectification_time": self.get_avg_rectification_time(dept_id),
            "top_issues": self.get_top_issues(5, dept_id),
            "user_workload": self.get_user_workload(dept_id),
            "rectification_rate": self.get_rectification_rate(dept_id),
        }
