"""
质控反馈导出服务
支持 CSV/Excel 导出病例详情视图
"""
import csv
import io
import json
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.config import load_config
from app.models import (
    AuditConclusion,
    AuditDimensionResult,
    Department,
    PushLog,
    QCFeedback,
    QCFeedbackHistory,
    User,
)
from app.services.patient_snapshot import (
    apply_privacy_masking,
    extract_patient_snapshot,
    normalize_privacy_masking_config,
)


class FeedbackExportService:
    """反馈导出服务（按病例详情维度导出）"""

    EXPORT_MAX_ROWS = 10000

    def __init__(self, db: Session):
        self.db = db

    def _parse_focus_items(self, raw_text: str) -> list[str]:
        if not raw_text:
            return []
        try:
            value = json.loads(raw_text)
            if isinstance(value, list):
                return [str(item).strip() for item in value if str(item).strip()]
        except Exception:
            return []
        return []

    def _status_label(self, status_value: str) -> str:
        labels = {
            "pending": "待处理",
            "acknowledged": "已确认",
            "rectified": "已整改",
            "closed": "已关闭",
        }
        return labels.get(status_value or "", status_value or "")

    def _severity_label(self, severity_value: str) -> str:
        labels = {
            "high": "高",
            "medium": "中",
            "low": "低",
        }
        return labels.get(severity_value or "", severity_value or "")

    def _normalize_dimension_name(self, value: str) -> str:
        name = str(value or "").strip()
        if not name:
            return "未命名维度"
        return name

    def _build_case_rows(
        self,
        role_name: str,
        current_user_dept_id: Optional[int],
        status: Optional[str] = None,
        severity: Optional[str] = None,
        dept_id: Optional[int] = None,
        days: int = 30,
        keyword: Optional[str] = None,
        mask_sensitive: bool = False,
    ) -> list[dict]:
        mask_cfg = normalize_privacy_masking_config(load_config().get("privacy_masking", {})) if mask_sensitive else None
        departments = self.db.query(Department).all()
        dept_by_name = {str(d.name or "").strip(): d for d in departments if str(d.name or "").strip()}
        dept_by_id = {d.id: d for d in departments}

        current_dept_name = None
        if current_user_dept_id:
            current_dept = dept_by_id.get(current_user_dept_id)
            current_dept_name = current_dept.name if current_dept else None

        issue_count_subquery = (
            self.db.query(
                AuditDimensionResult.push_log_id.label("log_id"),
                func.count(AuditDimensionResult.id).label("issue_count"),
            )
            .group_by(AuditDimensionResult.push_log_id)
            .subquery()
        )

        latest_feedback_subquery = (
            self.db.query(
                QCFeedback.push_log_id.label("log_id"),
                func.max(QCFeedback.id).label("feedback_id"),
            )
            .group_by(QCFeedback.push_log_id)
            .subquery()
        )

        query = (
            self.db.query(
                PushLog,
                AuditConclusion,
                QCFeedback,
                issue_count_subquery.c.issue_count,
            )
            .outerjoin(AuditConclusion, AuditConclusion.push_log_id == PushLog.id)
            .outerjoin(latest_feedback_subquery, latest_feedback_subquery.c.log_id == PushLog.id)
            .outerjoin(QCFeedback, QCFeedback.id == latest_feedback_subquery.c.feedback_id)
            .outerjoin(issue_count_subquery, issue_count_subquery.c.log_id == PushLog.id)
            .filter(PushLog.inconsistency == 1)
            .filter(PushLog.push_time >= datetime.now() - timedelta(days=days))
        )

        if role_name != "admin":
            dept_filters = [QCFeedback.dept_id == current_user_dept_id]
            if current_dept_name:
                dept_filters.append(and_(QCFeedback.id.is_(None), PushLog.dept == current_dept_name))
            query = query.filter(or_(*dept_filters))
        elif dept_id:
            dept_obj = dept_by_id.get(dept_id)
            dept_name = dept_obj.name if dept_obj else None
            query = query.filter(
                or_(
                    QCFeedback.dept_id == dept_id,
                    and_(QCFeedback.id.is_(None), PushLog.dept == dept_name),
                )
            )

        if status:
            if status == "pending":
                query = query.filter(or_(QCFeedback.id.is_(None), QCFeedback.status == "pending"))
            else:
                query = query.filter(QCFeedback.status == status)

        if severity:
            query = query.filter(or_(AuditConclusion.severity == severity, PushLog.severity == severity))

        if keyword:
            kw = keyword.strip()
            if kw:
                like_pattern = f"%{kw}%"
                query = query.filter(
                    or_(
                        PushLog.patient_id.like(like_pattern),
                        PushLog.patient_name.like(like_pattern),
                        PushLog.admission_no.like(like_pattern),
                    )
                )

        rows = (
            query.order_by(PushLog.push_time.desc())
            .limit(self.EXPORT_MAX_ROWS)
            .all()
        )
        if not rows:
            return []

        log_ids = [log.id for log, _, _, _ in rows]
        feedback_ids = [fb.id for _, _, fb, _ in rows if fb]

        dimensions_by_log_id = defaultdict(list)
        if log_ids:
            dims = (
                self.db.query(AuditDimensionResult)
                .filter(AuditDimensionResult.push_log_id.in_(log_ids))
                .order_by(AuditDimensionResult.push_log_id.asc(), AuditDimensionResult.id.asc())
                .all()
            )
            for item in dims:
                dimensions_by_log_id[item.push_log_id].append(item)

        history_by_feedback_id = defaultdict(list)
        if feedback_ids:
            histories = (
                self.db.query(QCFeedbackHistory)
                .filter(QCFeedbackHistory.feedback_id.in_(feedback_ids))
                .order_by(QCFeedbackHistory.feedback_id.asc(), QCFeedbackHistory.changed_at.asc())
                .all()
            )
            for item in histories:
                history_by_feedback_id[item.feedback_id].append(item)

        user_ids = set()
        for _, _, fb, _ in rows:
            if fb and fb.created_by:
                user_ids.add(fb.created_by)
            if fb and fb.assigned_to:
                user_ids.add(fb.assigned_to)
        user_map = {}
        if user_ids:
            users = self.db.query(User).filter(User.id.in_(user_ids)).all()
            user_map = {u.id: (u.full_name or u.username or f"#{u.id}") for u in users}

        result = []
        for log, conclusion, feedback, issue_count in rows:
            dept_ref = None
            if feedback and feedback.dept_id:
                dept_ref = dept_by_id.get(feedback.dept_id)
            elif log.dept:
                dept_ref = dept_by_name.get(str(log.dept or "").strip())
            dept_name = dept_ref.name if dept_ref else (log.dept or "")
            snapshot = extract_patient_snapshot(log)
            if mask_sensitive:
                snapshot = apply_privacy_masking(snapshot, mask_cfg)
            if not snapshot.get("dept_name"):
                snapshot["dept_name"] = dept_name

            focus_items = self._parse_focus_items(getattr(conclusion, "focus_items", "") or "")
            focus_items_text = "\n".join(focus_items) if focus_items else ""
            overall_conclusion = getattr(conclusion, "overall_conclusion", "") or ""
            overall_qc_summary = getattr(conclusion, "overall_qc_summary", "") or ""

            dimension_lines = []
            dimension_structured = {}
            for dim in dimensions_by_log_id.get(log.id, []):
                dim_name = self._normalize_dimension_name(dim.dimension)
                status_text = str(dim.status or "").strip()
                medical_text = str(dim.medical_content or "").strip()
                nursing_text = str(dim.nursing_content or "").strip()
                explanation_text = str(dim.issue_summary or dim.explanation or "").strip()

                if dim_name in dimension_structured:
                    # 同一维度出现多条时合并
                    prev = dimension_structured[dim_name]
                    status_text = " | ".join(filter(None, [prev.get("status", ""), status_text]))
                    medical_text = "\n---\n".join(filter(None, [prev.get("medical", ""), medical_text]))
                    nursing_text = "\n---\n".join(filter(None, [prev.get("nursing", ""), nursing_text]))
                    explanation_text = "\n---\n".join(filter(None, [prev.get("explanation", ""), explanation_text]))

                dimension_structured[dim_name] = {
                    "status": status_text,
                    "medical": medical_text,
                    "nursing": nursing_text,
                    "explanation": explanation_text,
                }

                dimension_lines.append(
                    f"[{dim.dimension}] 状态:{dim.status or ''} 严重度:{dim.severity or ''} | "
                    f"病程:{(dim.medical_content or '').strip()} | 护理:{(dim.nursing_content or '').strip()} | "
                    f"说明:{(dim.issue_summary or dim.explanation or '').strip()} | 建议:{(dim.recommendation or '').strip()}"
                )
            dimensions_text = "\n".join(dimension_lines)

            history_lines = []
            if feedback:
                for item in history_by_feedback_id.get(feedback.id, []):
                    changed_at = item.changed_at.strftime("%Y-%m-%d %H:%M:%S") if item.changed_at else ""
                    history_lines.append(
                        f"{changed_at} | {item.old_status or ''} -> {item.new_status or ''} | {item.change_reason or ''}"
                    )
            history_text = "\n".join(history_lines)

            feedback_text = feedback.feedback_text if feedback else ""
            feedback_status = feedback.status if feedback else "pending"
            assignee = user_map.get(feedback.assigned_to, "") if feedback and feedback.assigned_to else ""
            creator = user_map.get(feedback.created_by, "") if feedback and feedback.created_by else ""

            severity_value = (getattr(conclusion, "severity", "") or log.severity or "")

            result.append(
                {
                    "log_id": log.id,
                    "patient_name": snapshot.get("patient_name", "") or log.patient_name or "",
                    "patient_id": snapshot.get("patient_id", "") or log.patient_id or "",
                    "admission_no": snapshot.get("admission_no", "") or getattr(log, "admission_no", "") or "",
                    "dept_name": snapshot.get("dept_name", "") or dept_name,
                    "admission_date": snapshot.get("admission_date", ""),
                    "discharge_date": snapshot.get("discharge_date", ""),
                    "admission_diagnosis": snapshot.get("admission_diagnosis", ""),
                    "is_discharged": snapshot.get("is_discharged", ""),
                    "admission_dept_name": snapshot.get("admission_dept_name", ""),
                    "discharge_dept_name": snapshot.get("discharge_dept_name", ""),
                    "discharge_main_diagnosis": snapshot.get("discharge_main_diagnosis", ""),
                    "surgery": snapshot.get("surgery", ""),
                    "id_card": snapshot.get("id_card", ""),
                    "address": snapshot.get("address", ""),
                    "phone": snapshot.get("phone", ""),
                    "feedback_status": self._status_label(feedback_status),
                    "severity": self._severity_label(severity_value),
                    "query_date": log.query_date or "",
                    "push_time": log.push_time.strftime("%Y-%m-%d %H:%M:%S") if log.push_time else "",
                    "issue_count": issue_count or 0,
                    "overall_conclusion": overall_conclusion,
                    "overall_qc_summary": overall_qc_summary,
                    "focus_items": focus_items_text,
                    "mr_text": log.mr_text or "",
                    "dimensions_text": dimensions_text,
                    "dimensions": dimension_structured,
                    "feedback_text": feedback_text or "",
                    "assigned_to": assignee,
                    "created_by": creator,
                    "history_text": history_text,
                }
            )

        return result

    def export_to_csv(
        self,
        role_name: str,
        current_user_dept_id: Optional[int],
        status: Optional[str] = None,
        severity: Optional[str] = None,
        dept_id: Optional[int] = None,
        days: int = 30,
        keyword: Optional[str] = None,
    ) -> bytes:
        """导出 CSV（病例详情）"""
        rows = self._build_case_rows(
            role_name=role_name,
            current_user_dept_id=current_user_dept_id,
            status=status,
            severity=severity,
            dept_id=dept_id,
            days=days,
            keyword=keyword,
            mask_sensitive=False,
        )

        output = io.StringIO()
        dimension_names = sorted(
            {
                dim_name
                for row in rows
                for dim_name in (row.get("dimensions") or {}).keys()
            }
        )
        dimension_fieldnames = []
        for dim_name in dimension_names:
            dimension_fieldnames.extend(
                [
                    f"{dim_name}_状态",
                    f"{dim_name}_病程记录",
                    f"{dim_name}_护理记录",
                    f"{dim_name}_说明",
                ]
            )
        fieldnames = [
            "日志ID",
            "患者姓名",
            "患者ID",
            "身份证号",
            "住址",
            "联系电话",
            "住院号",
            "所在科室名称",
            "入院日期",
            "出院日期",
            "入院诊断",
            "是否出院",
            "入院科室名称",
            "出院科室名称",
            "出院主诊断",
            "手术",
            "状态",
            "严重度",
            "查询日期",
            "推送时间",
            "问题数",
            "总体结论",
            "整体质控描述",
            "重点关注项",
            "原始推送病历文书与护理记录",
            "当前反馈记录",
            "分配给",
            "创建人",
            "状态变更历史",
        ]
        fieldnames.extend(dimension_fieldnames)

        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for item in rows:
            row_data = {
                "日志ID": item["log_id"],
                "患者姓名": item["patient_name"],
                "患者ID": item["patient_id"],
                "身份证号": item["id_card"],
                "住址": item["address"],
                "联系电话": item["phone"],
                "住院号": item["admission_no"],
                "所在科室名称": item["dept_name"],
                "入院日期": item["admission_date"],
                "出院日期": item["discharge_date"],
                "入院诊断": item["admission_diagnosis"],
                "是否出院": item["is_discharged"],
                "入院科室名称": item["admission_dept_name"],
                "出院科室名称": item["discharge_dept_name"],
                "出院主诊断": item["discharge_main_diagnosis"],
                "手术": item["surgery"],
                "状态": item["feedback_status"],
                "严重度": item["severity"],
                "查询日期": item["query_date"],
                "推送时间": item["push_time"],
                "问题数": item["issue_count"],
                "总体结论": item["overall_conclusion"],
                "整体质控描述": item["overall_qc_summary"],
                "重点关注项": item["focus_items"],
                "原始推送病历文书与护理记录": item["mr_text"],
                "当前反馈记录": item["feedback_text"],
                "分配给": item["assigned_to"],
                "创建人": item["created_by"],
                "状态变更历史": item["history_text"],
            }
            item_dims = item.get("dimensions") or {}
            for dim_name in dimension_names:
                dim_value = item_dims.get(dim_name) or {}
                row_data[f"{dim_name}_状态"] = dim_value.get("status", "")
                row_data[f"{dim_name}_病程记录"] = dim_value.get("medical", "")
                row_data[f"{dim_name}_护理记录"] = dim_value.get("nursing", "")
                row_data[f"{dim_name}_说明"] = dim_value.get("explanation", "")
            writer.writerow(row_data)

        return output.getvalue().encode("utf-8-sig")

    def export_to_excel(
        self,
        role_name: str,
        current_user_dept_id: Optional[int],
        status: Optional[str] = None,
        severity: Optional[str] = None,
        dept_id: Optional[int] = None,
        days: int = 30,
        keyword: Optional[str] = None,
    ) -> tuple[bytes, str]:
        """导出 Excel；依赖缺失时回退 CSV。返回 (bytes, format) 元组，format 为 'xlsx' 或 'csv'。"""
        try:
            import openpyxl
            from openpyxl.styles import Alignment, Font, PatternFill
        except Exception:
            # openpyxl 不可用，回退 CSV 导出
            csv_bytes = self.export_to_csv(
                role_name=role_name,
                current_user_dept_id=current_user_dept_id,
                status=status,
                severity=severity,
                dept_id=dept_id,
                days=days,
                keyword=keyword,
            )
            return csv_bytes, "csv"

        rows = self._build_case_rows(
            role_name=role_name,
            current_user_dept_id=current_user_dept_id,
            status=status,
            severity=severity,
            dept_id=dept_id,
            days=days,
            keyword=keyword,
            mask_sensitive=True,
        )

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "病例详情导出"

        dimension_names = sorted(
            {
                dim_name
                for row in rows
                for dim_name in (row.get("dimensions") or {}).keys()
            }
        )

        columns = [
            ("日志ID", 10),
            ("患者姓名", 12),
            ("患者ID", 14),
            ("身份证号", 20),
            ("住址", 28),
            ("联系电话", 16),
            ("住院号", 14),
            ("所在科室名称", 14),
            ("入院日期", 20),
            ("出院日期", 20),
            ("入院诊断", 24),
            ("是否出院", 12),
            ("入院科室名称", 18),
            ("出院科室名称", 18),
            ("出院主诊断", 24),
            ("手术", 24),
            ("状态", 10),
            ("严重度", 10),
            ("查询日期", 12),
            ("推送时间", 19),
            ("问题数", 8),
            ("总体结论", 30),
            ("整体质控描述", 30),
            ("重点关注项", 26),
            ("原始推送病历文书与护理记录", 48),
            ("当前反馈记录", 28),
            ("分配给", 12),
            ("创建人", 12),
            ("状态变更历史", 32),
        ]
        for dim_name in dimension_names:
            columns.extend(
                [
                    (f"{dim_name}_状态", 12),
                    (f"{dim_name}_病程记录", 36),
                    (f"{dim_name}_护理记录", 36),
                    (f"{dim_name}_说明", 36),
                ]
            )

        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF")

        for col_idx, (name, width) in enumerate(columns, 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.value = name
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = width

        for row_idx, item in enumerate(rows, 2):
            values = [
                item["log_id"],
                item["patient_name"],
                item["patient_id"],
                item["id_card"],
                item["address"],
                item["phone"],
                item["admission_no"],
                item["dept_name"],
                item["admission_date"],
                item["discharge_date"],
                item["admission_diagnosis"],
                item["is_discharged"],
                item["admission_dept_name"],
                item["discharge_dept_name"],
                item["discharge_main_diagnosis"],
                item["surgery"],
                item["feedback_status"],
                item["severity"],
                item["query_date"],
                item["push_time"],
                item["issue_count"],
                item["overall_conclusion"],
                item["overall_qc_summary"],
                item["focus_items"],
                item["mr_text"],
                item["feedback_text"],
                item["assigned_to"],
                item["created_by"],
                item["history_text"],
            ]
            item_dims = item.get("dimensions") or {}
            for dim_name in dimension_names:
                dim_value = item_dims.get(dim_name) or {}
                values.extend(
                    [
                        dim_value.get("status", ""),
                        dim_value.get("medical", ""),
                        dim_value.get("nursing", ""),
                        dim_value.get("explanation", ""),
                    ]
                )
            for col_idx, value in enumerate(values, 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.value = value
                cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return output.getvalue(), "xlsx"
