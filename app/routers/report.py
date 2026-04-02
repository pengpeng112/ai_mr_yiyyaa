"""
审计报告路由 —— /report (HTML) + /api/report (JSON)
"""
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PushLog, AuditDimensionResult, AuditConclusion, User
from app.schemas import AuditReportResponse, AuditDimensionItem
from app.dify_pusher import parse_dify_structured_output
from app.auth import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)


def _load_report_data(log_id: int, db: Session) -> dict:
    """
    加载审计报告数据（结构化 + 兼容旧数据回退解析）

    Returns:
        {log, dimensions, conclusion, focus_items}
    """
    log = db.query(PushLog).filter(PushLog.id == log_id).first()
    if not log:
        return None

    # 查询结构化审计数据
    dimensions = (
        db.query(AuditDimensionResult)
        .filter(AuditDimensionResult.push_log_id == log_id)
        .order_by(AuditDimensionResult.id)
        .all()
    )
    conclusion = (
        db.query(AuditConclusion)
        .filter(AuditConclusion.push_log_id == log_id)
        .first()
    )

    # 兼容旧数据：如果没有结构化数据，尝试从 ai_result 重新解析
    if not dimensions and log.ai_result:
        try:
            outputs = json.loads(log.ai_result)
            if isinstance(outputs, dict):
                parsed = parse_dify_structured_output(outputs)
                if parsed.get("parse_success"):
                    return {
                        "log": log,
                        "dimensions": parsed.get("dimensions", []),
                        "overall_conclusion": parsed.get("overall_conclusion", ""),
                        "focus_items": parsed.get("focus_items", []),
                        "audit_date": parsed.get("audit_date", ""),
                        "from_fallback": True,
                    }
        except Exception:
            pass

    # 解析 focus_items
    focus_items = []
    if conclusion and conclusion.focus_items:
        try:
            focus_items = json.loads(conclusion.focus_items)
        except Exception:
            focus_items = []

    return {
        "log": log,
        "dimensions": [
            {
                "dimension": d.dimension,
                "status": d.status,
                "medical_content": d.medical_content,
                "nursing_content": d.nursing_content,
                "explanation": d.issue_summary or d.explanation,
            }
            for d in dimensions
        ],
        "overall_conclusion": conclusion.overall_conclusion if conclusion else "",
        "focus_items": focus_items,
        "audit_date": conclusion.audit_date if conclusion else "",
        "from_fallback": False,
    }


@router.get("/api/report/{log_id}/data", response_model=AuditReportResponse, summary="获取审计报告 JSON 数据")
def get_report_data(log_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    """返回结构化 JSON，供前端 SPA 在对话框内渲染报告"""
    data = _load_report_data(log_id, db)
    if not data:
        raise HTTPException(status_code=404, detail="日志不存在")

    log = data["log"]
    return AuditReportResponse(
        log_id=log.id,
        patient_id=log.patient_id,
        patient_name=log.patient_name,
        admission_no=getattr(log, "admission_no", ""),
        dept=log.dept,
        query_date=log.query_date,
        push_time=log.push_time,
        dimensions=[AuditDimensionItem(**d) for d in data["dimensions"]],
        overall_conclusion=data["overall_conclusion"],
        focus_items=data["focus_items"],
        status=log.status,
    )


@router.get("/report/{log_id}", response_class=HTMLResponse, summary="查看审计报告 HTML 页面")
def get_report_html(log_id: int, db: Session = Depends(get_db)):
    """返回自包含的 HTML 质控报告页面，供临床人员查看和打印"""
    data = _load_report_data(log_id, db)
    if not data:
        raise HTTPException(status_code=404, detail="日志不存在")

    log = data["log"]
    dimensions = data["dimensions"]
    overall_conclusion = data["overall_conclusion"]
    focus_items = data["focus_items"]
    audit_date = data.get("audit_date", "")

    # 构建维度行 HTML
    dim_rows = ""
    for d in dimensions:
        status = d.get("status", "❓")
        status_text = _status_label(status)
        status_class = _status_css_class(status)
        explanation = _escape_html(d.get("explanation", ""))
        dimension = _escape_html(d.get("dimension", ""))
        medical = _escape_html(d.get("medical_content", ""))
        nursing = _escape_html(d.get("nursing_content", ""))

        detail_html = ""
        if medical or nursing:
            detail_html = f"""
            <tr class="detail-row">
                <td colspan="3">
                    <div class="detail-box">
                        <div class="detail-item"><strong>病程记录：</strong>{medical if medical else '（无）'}</div>
                        <div class="detail-item"><strong>护理记录：</strong>{nursing if nursing else '（无）'}</div>
                    </div>
                </td>
            </tr>"""

        dim_rows += f"""
            <tr>
                <td class="dim-name">{dimension}</td>
                <td class="dim-status {status_class}">{status_text}</td>
                <td class="dim-explain">{explanation}</td>
            </tr>{detail_html}"""

    # 构建关注项列表
    focus_html = ""
    if focus_items:
        items = "".join(f"<li>{_escape_html(str(item))}</li>" for item in focus_items)
        focus_html = f"<ol>{items}</ol>"
    else:
        focus_html = "<p>无</p>"

    push_time_str = log.push_time.strftime("%Y-%m-%d %H:%M:%S") if log.push_time else ""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>病历一致性核查报告 - {_escape_html(log.patient_name)}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, "Microsoft YaHei", "Segoe UI", sans-serif; background: #f5f5f5; color: #333; line-height: 1.6; }}
.container {{ max-width: 900px; margin: 20px auto; background: #fff; border-radius: 8px; box-shadow: 0 2px 12px rgba(0,0,0,0.1); overflow: hidden; }}
.header {{ background: linear-gradient(135deg, #409eff, #2d8cf0); color: #fff; padding: 24px 32px; text-align: center; }}
.header h1 {{ font-size: 22px; margin-bottom: 12px; }}
.header .meta {{ display: flex; flex-wrap: wrap; justify-content: center; gap: 16px; font-size: 14px; opacity: 0.95; }}
.header .meta span {{ background: rgba(255,255,255,0.15); padding: 2px 10px; border-radius: 4px; }}
.section {{ padding: 20px 32px; }}
.section-title {{ font-size: 16px; font-weight: 600; color: #303133; border-bottom: 2px solid #409eff; padding-bottom: 8px; margin-bottom: 16px; }}
table {{ width: 100%; border-collapse: collapse; }}
th {{ background: #f5f7fa; color: #606266; font-weight: 600; text-align: left; padding: 10px 12px; border-bottom: 2px solid #ebeef5; }}
td {{ padding: 10px 12px; border-bottom: 1px solid #ebeef5; vertical-align: top; }}
.dim-name {{ font-weight: 500; width: 140px; }}
.dim-status {{ width: 60px; text-align: center; font-size: 18px; }}
.dim-explain {{ color: #606266; }}
.status-pass {{ color: #52c41a; }}
.status-fail {{ color: #ff4d4f; }}
.status-warn {{ color: #fa8c16; }}
.status-unknown {{ color: #8c8c8c; }}
.detail-row td {{ padding: 0 12px 10px 12px; border-bottom: 1px solid #ebeef5; }}
.detail-box {{ background: #fafafa; border-radius: 4px; padding: 10px 14px; margin-top: 4px; font-size: 13px; color: #666; }}
.detail-item {{ margin-bottom: 6px; }}
.detail-item:last-child {{ margin-bottom: 0; }}
.conclusion {{ background: #f0f9ff; border-left: 4px solid #409eff; padding: 16px 20px; border-radius: 0 4px 4px 0; margin: 12px 0; }}
.conclusion p {{ font-size: 15px; }}
.focus-list ol {{ padding-left: 20px; }}
.focus-list li {{ margin-bottom: 6px; color: #e6a23c; font-weight: 500; }}
.actions {{ display: flex; gap: 12px; justify-content: center; padding: 20px 32px; border-top: 1px solid #ebeef5; }}
.btn {{ padding: 8px 24px; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }}
.btn-print {{ background: #409eff; color: #fff; }}
.btn-print:hover {{ background: #2d8cf0; }}
.btn-back {{ background: #f5f7fa; color: #606266; border: 1px solid #dcdfe6; }}
.btn-back:hover {{ background: #e9ecf1; }}
.footer {{ text-align: center; padding: 12px; color: #999; font-size: 12px; border-top: 1px solid #ebeef5; }}
@media print {{
    body {{ background: #fff; }}
    .container {{ box-shadow: none; margin: 0; }}
    .actions {{ display: none; }}
    .header {{ background: #409eff !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
}}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>病历一致性核查报告</h1>
        <div class="meta">
            <span>患者：{_escape_html(log.patient_name)}</span>
            <span>住院号：{_escape_html(getattr(log, 'admission_no', '') or '')}</span>
            <span>科室：{_escape_html(log.dept)}</span>
            <span>查询日期：{_escape_html(log.query_date)}</span>
            <span>推送时间：{push_time_str}</span>
        </div>
    </div>

    <div class="section">
        <div class="section-title">核查结果</div>
        <table>
            <thead>
                <tr>
                    <th>核查维度</th>
                    <th style="text-align:center">状态</th>
                    <th>说明</th>
                </tr>
            </thead>
            <tbody>
                {dim_rows if dim_rows else '<tr><td colspan="3" style="text-align:center;color:#999;">暂无结构化审计数据</td></tr>'}
            </tbody>
        </table>
    </div>

    <div class="section">
        <div class="section-title">总体结论</div>
        <div class="conclusion">
            <p>{_escape_html(overall_conclusion) if overall_conclusion else '暂无结论'}</p>
        </div>
    </div>

    <div class="section">
        <div class="section-title">重点关注项</div>
        <div class="focus-list">
            {focus_html}
        </div>
    </div>

    <div class="actions">
        <button class="btn btn-print" onclick="window.print()">打印报告</button>
        <button class="btn btn-back" onclick="history.back()">返回</button>
    </div>

    <div class="footer">
        医疗记录一致性审计系统 | 报告生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 日志ID：{log_id}
    </div>
</div>
</body>
</html>"""

    return HTMLResponse(content=html)


def _status_css_class(status: str) -> str:
    """根据状态返回 CSS class"""
    if status == "pass" or "✅" in status:
        return "status-pass"
    elif status == "fail" or "❌" in status:
        return "status-fail"
    elif status == "warn" or "⚠" in status:
        return "status-warn"
    else:
        return "status-unknown"


def _status_label(status: str) -> str:
    if status == "pass":
        return "通过"
    if status == "fail":
        return "不一致"
    if status == "warn":
        return "警告"
    if status == "unknown":
        return "未知"
    return status or "未知"


def _escape_html(text: str) -> str:
    """转义 HTML 特殊字符"""
    if not text:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )
