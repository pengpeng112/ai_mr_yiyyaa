"""
反馈导出服务
支持 CSV、Excel、PDF 导出
"""
import csv
import io
from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session

from app.models import QCFeedback, Department, User

class FeedbackExportService:
    """反馈导出服务"""
    
    def __init__(self, db: Session):
        self.db = db
    
    EXPORT_MAX_ROWS = 10000  # 单次导出最大行数

    def get_feedbacks_for_export(self, dept_id: Optional[int] = None) -> List[dict]:
        """获取用于导出的反馈数据（限制最大行数防止 OOM）"""
        query = self.db.query(QCFeedback)
        
        if dept_id:
            query = query.filter(QCFeedback.dept_id == dept_id)
        
        feedbacks = query.order_by(QCFeedback.created_at.desc()).limit(self.EXPORT_MAX_ROWS).all()
        
        # 批量预加载科室和用户，消除 N+1
        dept_ids = {fb.dept_id for fb in feedbacks if fb.dept_id}
        user_ids = {fb.created_by for fb in feedbacks if fb.created_by}
        user_ids |= {fb.assigned_to for fb in feedbacks if fb.assigned_to}
        
        depts_map = {}
        if dept_ids:
            depts = self.db.query(Department).filter(Department.id.in_(dept_ids)).all()
            depts_map = {d.id: d.name for d in depts}
        
        users_map = {}
        if user_ids:
            users = self.db.query(User).filter(User.id.in_(user_ids)).all()
            users_map = {u.id: u.full_name for u in users}
        
        result = []
        for fb in feedbacks:
            dept_name = depts_map.get(fb.dept_id, "未知")
            creator_name = users_map.get(fb.created_by, "未知")
            assignee_name = users_map.get(fb.assigned_to, "未分配") if fb.assigned_to else "未分配"
            
            result.append({
                "id": fb.id,
                "push_log_id": fb.push_log_id,
                "dept_name": dept_name,
                "severity": fb.severity,
                "severity_label": self._get_severity_label(fb.severity),
                "status": fb.status,
                "status_label": self._get_status_label(fb.status),
                "feedback_text": fb.feedback_text,
                "rectification_text": fb.rectification_text,
                "assigned_to": assignee_name,
                "created_by": creator_name,
                "created_at": fb.created_at.strftime("%Y-%m-%d %H:%M:%S") if fb.created_at else "",
                "rectification_date": fb.rectification_date.strftime("%Y-%m-%d %H:%M:%S") if fb.rectification_date else "",
            })
        
        return result
    
    def export_to_csv(self, dept_id: Optional[int] = None) -> bytes:
        """导出为 CSV 格式"""
        feedbacks = self.get_feedbacks_for_export(dept_id)
        
        output = io.StringIO()
        
        if not feedbacks:
            return output.getvalue().encode('utf-8-sig')
        
        # 定义字段
        fieldnames = [
            "ID", "推送日志ID", "科室", "严重程度", "状态", 
            "反馈内容", "整改说明", "分配给", "创建人", 
            "创建时间", "整改完成时间"
        ]
        
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        
        for fb in feedbacks:
            writer.writerow({
                "ID": fb["id"],
                "推送日志ID": fb["push_log_id"],
                "科室": fb["dept_name"],
                "严重程度": fb["severity_label"],
                "状态": fb["status_label"],
                "反馈内容": fb["feedback_text"],
                "整改说明": fb["rectification_text"],
                "分配给": fb["assigned_to"],
                "创建人": fb["created_by"],
                "创建时间": fb["created_at"],
                "整改完成时间": fb["rectification_date"],
            })
        
        return output.getvalue().encode('utf-8-sig')
    
    def export_to_excel(self, dept_id: Optional[int] = None) -> bytes:
        """导出为 Excel 格式"""
        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment
        except ImportError:
            # 如果没有安装 openpyxl，返回 CSV 格式
            return self.export_to_csv(dept_id)
        
        feedbacks = self.get_feedbacks_for_export(dept_id)
        
        # 创建工作簿
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "反馈数据"
        
        # 定义列
        columns = [
            ("ID", 10),
            ("推送日志ID", 15),
            ("科室", 15),
            ("严重程度", 12),
            ("状态", 12),
            ("反馈内容", 30),
            ("整改说明", 30),
            ("分配给", 15),
            ("创建人", 15),
            ("创建时间", 20),
            ("整改完成时间", 20),
        ]
        
        # 写入表头
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF")
        
        for col_idx, (col_name, col_width) in enumerate(columns, 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.value = col_name
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = col_width
        
        # 写入数据
        for row_idx, fb in enumerate(feedbacks, 2):
            ws.cell(row=row_idx, column=1).value = fb["id"]
            ws.cell(row=row_idx, column=2).value = fb["push_log_id"]
            ws.cell(row=row_idx, column=3).value = fb["dept_name"]
            ws.cell(row=row_idx, column=4).value = fb["severity_label"]
            ws.cell(row=row_idx, column=5).value = fb["status_label"]
            ws.cell(row=row_idx, column=6).value = fb["feedback_text"]
            ws.cell(row=row_idx, column=7).value = fb["rectification_text"]
            ws.cell(row=row_idx, column=8).value = fb["assigned_to"]
            ws.cell(row=row_idx, column=9).value = fb["created_by"]
            ws.cell(row=row_idx, column=10).value = fb["created_at"]
            ws.cell(row=row_idx, column=11).value = fb["rectification_date"]
            
            # 设置行高和对齐
            ws.row_dimensions[row_idx].height = 30
            for col_idx in range(1, len(columns) + 1):
                ws.cell(row=row_idx, column=col_idx).alignment = Alignment(
                    horizontal="left", vertical="top", wrap_text=True
                )
        
        # 保存到字节流
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return output.getvalue()
    
    def _get_severity_label(self, severity: str) -> str:
        """获取严重程度标签"""
        labels = {
            "high": "🔴 高",
            "medium": "🟡 中",
            "low": "🔵 低",
        }
        return labels.get(severity, severity)
    
    def _get_status_label(self, status: str) -> str:
        """获取状态标签"""
        labels = {
            "pending": "待处理",
            "acknowledged": "已确认",
            "rectified": "已整改",
            "closed": "已关闭",
        }
        return labels.get(status, status)
