"""
质控报告路由 —— /report/{log_id} (HTML) + /api/report/{log_id}/data (JSON)
"""
import json
import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PushLog, AuditDimensionResult, AuditConclusion
from app.schemas import AuditReportResponse, AuditDimensionItem
from app.dify_pusher import parse_dify_structured_output

router = APIRouter()
logger = logging.getLogger(__name__)


def _load_report_data(log_id: int, db: Session) -> dict:
    """加载报告数据，兼容新旧结构"""
    log = db.query(PushLog).filter(PushLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="日志不存在")

    # 查询结构化维度数据
    dimensions = db.query(AuditDimensionResult).filter(
        AuditDimensionResult.push_log_id == log_id
    ).all()

    # 查询总体结论
    conclusion = db.query(AuditConclusion).filter(
        AuditConclusion.push_log_id == log_id
    ).first()

    dim_list = []
    overall_conclusion = ""
    focus_items = []

    if dimensions:
        dim_list = [
            {
                "dimension": d.dimension,
                "status": d.status,
                "medical_content": d.medical_content or "",
                "nursing_content": d.nursing_content or "",
                "explanation": d.explanation or "",
            }
            for d in dimensions
        ]
        if conclusion:
            overall_conclusion = conclusion.overall_conclusion or ""
            try:
                focus_items = json.loads(conclusion.focus_items or "[]")
            except Exception:
                focus_items = []
    else:
        # 兼容旧数据：尝试从 ai_result JSON 重新解析
        if log.ai_result:
            try:
                raw_outputs = json.loads(log.ai_result)
                parsed = parse_dify_structured_output(raw_outputs, "aa")
                dim_list = parsed.get("dimensions", [])
                overall_conclusion = parsed.get("overall_conclusion", "")
                focus_items = parsed.get("focus_items", [])
                logger.info(f"旧数据兼容解析 | log_id={log_id} | dimensions={len(dim_list)}")
            except Exception as e:
                logger.warning(f"旧数据兼容解析失败 | log_id={log_id} | error={e}")

    return {
        "log_id": log_id,
        "patient_id": log.patient_id or "",
        "patient_name": log.patient_name or "",
        "admission_no": getattr(log, "admission_no", "") or "",
        "dept": log.dept or "",
        "query_date": log.query_date or "",
        "push_time": log.push_time,
        "dimensions": dim_list,
        "overall_conclusion": overall_conclusion,
        "focus_items": focus_items,
        "status": log.status or "",
        "inconsistency": log.inconsistency,
        "severity": log.severity or "",
    }


@router.get("/api/report/{log_id}/data", summary="质控报告 JSON 数据")
def get_report_data(log_id: int, db: Session = Depends(get_db)):
    """返回结构化 JSON，供前端 SPA 在对话框内渲染报告。"""
    data = _load_report_data(log_id, db)
    # 转换 push_time 为字符串
    if isinstance(data.get("push_time"), datetime):
        data["push_time"] = data["push_time"].strftime("%Y-%m-%d %H:%M:%S")
    return data


@router.get("/report/{log_id}", response_class=HTMLResponse, summary="质控报告 HTML 页面")
def get_report_html(log_id: int, db: Session = Depends(get_db)):
    """返回自包含 HTML 报告，供临床人员在浏览器查看和打印。"""
    data = _load_report_data(log_id, db)

    push_time_str = ""
    if isinstance(data["push_time"], datetime):
        push_time_str = data["push_time"].strftime("%Y-%m-%d %H:%M:%S")
    else:
        push_time_str = str(data["push_time"])

    # 状态颜色映射
    status_colors = {
        "✅": "#52c41a",
        "❌": "#ff4d4f",
        "⚠️": "#fa8c16",
        "❓": "#8c8c8c",
    }

    def status_badge(icon: str) -> str:
        color = status_colors.get(icon, "#8c8c8c")
        return f'<span style="color:{color}; font-size:18px;">{icon}</span>'

    # 构建维度行 HTML
    dimension_rows = ""
    for dim in data["dimensions"]:
        icon = dim.get("status", "❓")
        color = status_colors.get(icon, "#8c8c8c")
        has_content = dim.get("medical_content") or dim.get("nursing_content")
        content_rows = ""
        if has_content:
            if dim.get("medical_content"):
                content_rows += f"""
                <tr class="content-row">
                    <td colspan="3" style="padding: 4px 16px 4px 32px; background:#fafafa; color:#555; font-size:13px;">
                        <span style="color:#1890ff">病程记录：</span>{dim['medical_content']}
                    </td>
                </tr>"""
            if dim.get("nursing_content"):
                content_rows += f"""
                <tr class="content-row">
                    <td colspan="3" style="padding: 4px 16px 4px 32px; background:#fafafa; color:#555; font-size:13px;">
                        <span style="color:#52c41a">护理记录：</span>{dim['nursing_content']}
                    </td>
                </tr>"""
        dimension_rows += f"""
        <tr>
            <td style="padding: 10px 16px; font-weight:500;">{dim.get('dimension', '')}</td>
            <td style="padding: 10px 16px; text-align:center;">{status_badge(icon)}</td>
            <td style="padding: 10px 16px; color:{color};">{dim.get('explanation', '')}</td>
        </tr>
        {content_rows}"""

    if not dimension_rows:
        dimension_rows = '<tr><td colspan="3" style="text-align:center; padding:20px; color:#999;">暂无结构化审计数据</td></tr>'

    # 构建重点关注项
    focus_html = ""
    if data["focus_items"]:
        items_li = "".join(f"<li style='margin: 6px 0;'>{item}</li>" for item in data["focus_items"])
        focus_html = f"""
        <div style="margin-top: 20px; padding: 16px; background: #fff7e6; border-left: 4px solid #fa8c16; border-radius: 4px;">
            <div style="font-weight: bold; color: #fa8c16; margin-bottom: 8px;">重点关注项</div>
            <ol style="margin: 0; padding-left: 20px; color: #555;">{items_li}</ol>
        </div>"""

    overall_color = "#ff4d4f" if data["inconsistency"] else "#52c41a"
    overall_icon = "❌" if data["inconsistency"] else "✅"

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>病历一致性核查报告 - {data['patient_name']} ({data['query_date']})</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; padding: 20px;
      font-family: "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif;
      background: #f5f7fa; color: #333;
    }}
    .report-container {{
      max-width: 900px; margin: 0 auto;
      background: #fff; border-radius: 8px;
      box-shadow: 0 2px 12px rgba(0,0,0,0.1); overflow: hidden;
    }}
    .report-header {{
      background: linear-gradient(135deg, #1890ff, #096dd9);
      color: white; padding: 24px 32px;
    }}
    .report-header h1 {{
      margin: 0 0 8px; font-size: 22px; font-weight: bold;
    }}
    .report-header .meta {{
      font-size: 14px; opacity: 0.9; line-height: 1.8;
    }}
    .report-body {{ padding: 24px 32px; }}
    .section-title {{
      font-size: 16px; font-weight: bold; color: #1890ff;
      border-bottom: 2px solid #e8f4ff; padding-bottom: 8px;
      margin: 20px 0 12px;
    }}
    table {{
      width: 100%; border-collapse: collapse; font-size: 14px;
    }}
    th {{
      background: #f0f5ff; padding: 10px 16px;
      text-align: left; font-weight: 600; color: #333;
      border-bottom: 2px solid #d6e4ff;
    }}
    tr:hover {{ background: #fafcff; }}
    td {{ border-bottom: 1px solid #f0f0f0; }}
    .conclusion-box {{
      padding: 16px; background: #f6ffed; border-left: 4px solid #52c41a;
      border-radius: 4px; margin-top: 8px; color: #389e0d; font-size: 14px;
    }}
    .conclusion-box.warn {{
      background: #fff2f0; border-left-color: #ff4d4f; color: #cf1322;
    }}
    .actions {{
      padding: 20px 32px; border-top: 1px solid #f0f0f0;
      display: flex; gap: 12px;
    }}
    .btn {{
      padding: 8px 20px; border-radius: 4px; cursor: pointer;
      font-size: 14px; border: none;
    }}
    .btn-primary {{
      background: #1890ff; color: white;
    }}
    .btn-default {{
      background: #f0f0f0; color: #333;
    }}
    @media print {{
      body {{ background: white; padding: 0; }}
      .report-container {{ box-shadow: none; }}
      .actions {{ display: none !important; }}
      .report-header {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    }}
  </style>
</head>
<body>
  <div class="report-container">
    <div class="report-header">
      <h1>病历一致性核查报告</h1>
      <div class="meta">
        患者：<strong>{data['patient_name']}</strong>
        &nbsp;&nbsp;|&nbsp;&nbsp;
        住院号：<strong>{data['admission_no'] or '—'}</strong>
        &nbsp;&nbsp;|&nbsp;&nbsp;
        科室：<strong>{data['dept'] or '—'}</strong>
        &nbsp;&nbsp;|&nbsp;&nbsp;
        核查日期：<strong>{data['query_date']}</strong>
        <br>
        患者ID：{data['patient_id']}
        &nbsp;&nbsp;|&nbsp;&nbsp;
        生成时间：{push_time_str}
      </div>
    </div>

    <div class="report-body">
      <div class="section-title">审计维度详情</div>
      <table>
        <thead>
          <tr>
            <th width="25%">核查维度</th>
            <th width="10%" style="text-align:center;">状态</th>
            <th>说明</th>
          </tr>
        </thead>
        <tbody>
          {dimension_rows}
        </tbody>
      </table>

      <div class="section-title">总体结论</div>
      <div class="conclusion-box {'warn' if data['inconsistency'] else ''}">
        {overall_icon} {data['overall_conclusion'] or ('存在不一致，请核查。' if data['inconsistency'] else '记录一致，未发现问题。')}
      </div>

      {focus_html}
    </div>

    <div class="actions no-print">
      <button class="btn btn-primary" onclick="window.print()">打印报告</button>
      <button class="btn btn-default" onclick="window.history.back()">返回</button>
    </div>
  </div>
</body>
</html>"""

    return HTMLResponse(content=html)
