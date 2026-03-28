"""
质控报告路由：
  GET /report/{log_id}              — 完整 HTML 报告（支持 ?embed=1 嵌入模式）
  GET /popup/{log_id}               — 轻量弹窗 HTML（供 window.open / iframe）
  GET /api/report/{log_id}/data     — JSON 数据接口
"""
import json
import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PushLog, AuditDimensionResult, AuditConclusion
from app.dify_pusher import parse_dify_structured_output

router = APIRouter()
logger = logging.getLogger(__name__)

# 状态图标对应颜色
_STATUS_COLORS = {
    "✅": "#52c41a",
    "❌": "#ff4d4f",
    "⚠️": "#fa8c16",
    "❓": "#8c8c8c",
}


def _load_report_data(log_id: int, db: Session) -> dict:
    """加载报告数据，兼容新旧结构"""
    log = db.query(PushLog).filter(PushLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="日志不存在")

    dimensions = db.query(AuditDimensionResult).filter(
        AuditDimensionResult.push_log_id == log_id
    ).all()
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


def _build_dimension_rows(dim_list: list) -> str:
    rows = ""
    for dim in dim_list:
        icon = dim.get("status", "❓")
        color = _STATUS_COLORS.get(icon, "#8c8c8c")
        has_content = dim.get("medical_content") or dim.get("nursing_content")
        content_rows = ""
        if has_content:
            if dim.get("medical_content"):
                content_rows += (
                    f'<tr><td colspan="3" style="padding:4px 16px 4px 32px;background:#fafafa;'
                    f'color:#555;font-size:13px;">'
                    f'<span style="color:#1890ff">病程记录：</span>{dim["medical_content"]}</td></tr>'
                )
            if dim.get("nursing_content"):
                content_rows += (
                    f'<tr><td colspan="3" style="padding:4px 16px 4px 32px;background:#fafafa;'
                    f'color:#555;font-size:13px;">'
                    f'<span style="color:#52c41a">护理记录：</span>{dim["nursing_content"]}</td></tr>'
                )
        rows += (
            f'<tr>'
            f'<td style="padding:10px 16px;font-weight:500;">{dim.get("dimension","")}</td>'
            f'<td style="padding:10px 16px;text-align:center;font-size:18px;color:{color};">{icon}</td>'
            f'<td style="padding:10px 16px;color:{color};">{dim.get("explanation","")}</td>'
            f'</tr>{content_rows}'
        )
    if not rows:
        rows = '<tr><td colspan="3" style="text-align:center;padding:20px;color:#999;">暂无结构化审计数据</td></tr>'
    return rows


def _build_focus_html(focus_items: list) -> str:
    if not focus_items:
        return ""
    items_li = "".join(f"<li style='margin:6px 0;'>{item}</li>" for item in focus_items)
    return (
        '<div style="margin-top:20px;padding:16px;background:#fff7e6;'
        'border-left:4px solid #fa8c16;border-radius:4px;">'
        '<div style="font-weight:bold;color:#fa8c16;margin-bottom:8px;">重点关注项</div>'
        f'<ol style="margin:0;padding-left:20px;color:#555;">{items_li}</ol></div>'
    )


@router.get("/api/report/{log_id}/data", summary="质控报告 JSON 数据")
def get_report_data(log_id: int, db: Session = Depends(get_db)):
    """返回结构化 JSON，供前端 SPA 渲染或外部系统调用。"""
    data = _load_report_data(log_id, db)
    if isinstance(data.get("push_time"), datetime):
        data["push_time"] = data["push_time"].strftime("%Y-%m-%d %H:%M:%S")
    return data


@router.get("/report/{log_id}", response_class=HTMLResponse, summary="质控报告 HTML 页面（支持 embed 模式）")
def get_report_html(
    log_id: int,
    embed: bool = Query(False, description="True=嵌入 iframe 模式，隐藏操作按钮"),
    db: Session = Depends(get_db),
):
    """
    完整 HTML 质控报告。
    - embed=false（默认）：含打印/返回按钮，独立浏览
    - embed=true：无操作按钮，适合嵌入 iframe
    """
    data = _load_report_data(log_id, db)
    push_time_str = (
        data["push_time"].strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(data["push_time"], datetime)
        else str(data["push_time"])
    )

    dimension_rows = _build_dimension_rows(data["dimensions"])
    focus_html = _build_focus_html(data["focus_items"])
    overall_icon = "❌" if data["inconsistency"] else "✅"
    conclusion_cls = "warn" if data["inconsistency"] else ""
    conclusion_text = data["overall_conclusion"] or (
        "存在不一致，请核查。" if data["inconsistency"] else "记录一致，未发现问题。"
    )

    actions_html = "" if embed else """
    <div class="actions">
      <button class="btn btn-primary" onclick="window.print()">打印报告</button>
      <button class="btn btn-default" onclick="window.history.back()">返回</button>
    </div>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>病历一致性核查报告 - {data['patient_name']} ({data['query_date']})</title>
  <style>
    *{{box-sizing:border-box;}}
    body{{margin:0;padding:{'10px' if embed else '20px'};
      font-family:"Microsoft YaHei","Helvetica Neue",Arial,sans-serif;
      background:{('#fff' if embed else '#f5f7fa')};color:#333;}}
    .report-container{{max-width:900px;margin:0 auto;background:#fff;
      border-radius:{'0' if embed else '8px'};
      box-shadow:{('none' if embed else '0 2px 12px rgba(0,0,0,.1)')};overflow:hidden;}}
    .report-header{{background:linear-gradient(135deg,#1890ff,#096dd9);
      color:#fff;padding:{('12px 20px' if embed else '24px 32px')};}}
    .report-header h1{{margin:0 0 6px;font-size:{'16px' if embed else '22px'};font-weight:bold;}}
    .report-header .meta{{font-size:13px;opacity:.9;line-height:1.8;}}
    .report-body{{padding:{('12px 16px' if embed else '24px 32px')};}}
    .section-title{{font-size:15px;font-weight:bold;color:#1890ff;
      border-bottom:2px solid #e8f4ff;padding-bottom:6px;margin:16px 0 10px;}}
    table{{width:100%;border-collapse:collapse;font-size:14px;}}
    th{{background:#f0f5ff;padding:8px 16px;text-align:left;
      font-weight:600;color:#333;border-bottom:2px solid #d6e4ff;}}
    tr:hover{{background:#fafcff;}}
    td{{border-bottom:1px solid #f0f0f0;}}
    .conclusion-box{{padding:12px;background:#f6ffed;
      border-left:4px solid #52c41a;border-radius:4px;margin-top:6px;
      color:#389e0d;font-size:14px;}}
    .conclusion-box.warn{{background:#fff2f0;border-left-color:#ff4d4f;color:#cf1322;}}
    .actions{{padding:16px 32px;border-top:1px solid #f0f0f0;display:flex;gap:12px;}}
    .btn{{padding:8px 20px;border-radius:4px;cursor:pointer;font-size:14px;border:none;}}
    .btn-primary{{background:#1890ff;color:#fff;}}
    .btn-default{{background:#f0f0f0;color:#333;}}
    @media print{{
      body{{background:#fff;padding:0;}}
      .report-container{{box-shadow:none;}}
      .actions{{display:none!important;}}
      .report-header{{-webkit-print-color-adjust:exact;print-color-adjust:exact;}}
    }}
  </style>
</head>
<body>
  <div class="report-container">
    <div class="report-header">
      <h1>病历一致性核查报告</h1>
      <div class="meta">
        患者：<strong>{data['patient_name']}</strong> &nbsp;|&nbsp;
        住院号：<strong>{data['admission_no'] or '—'}</strong> &nbsp;|&nbsp;
        科室：<strong>{data['dept'] or '—'}</strong> &nbsp;|&nbsp;
        核查日期：<strong>{data['query_date']}</strong><br>
        患者ID：{data['patient_id']} &nbsp;|&nbsp; 生成时间：{push_time_str}
      </div>
    </div>
    <div class="report-body">
      <div class="section-title">审计维度详情</div>
      <table>
        <thead><tr>
          <th width="25%">核查维度</th>
          <th width="10%" style="text-align:center;">状态</th>
          <th>说明</th>
        </tr></thead>
        <tbody>{dimension_rows}</tbody>
      </table>
      <div class="section-title">总体结论</div>
      <div class="conclusion-box {conclusion_cls}">{overall_icon} {conclusion_text}</div>
      {focus_html}
    </div>
    {actions_html}
  </div>
</body>
</html>"""

    headers = {"X-Frame-Options": "SAMEORIGIN"}
    return HTMLResponse(content=html, headers=headers)


@router.get("/popup/{log_id}", response_class=HTMLResponse, summary="质控提醒弹窗（轻量，可 window.open 或 iframe）")
def get_popup_html(log_id: int, db: Session = Depends(get_db)):
    """
    轻量质控提醒弹窗，设计用于：
    - window.open('/popup/{log_id}', '_blank', 'width=800,height=620')
    - 嵌入 iframe：<iframe src="/popup/{log_id}"></iframe>
    """
    data = _load_report_data(log_id, db)
    push_time_str = (
        data["push_time"].strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(data["push_time"], datetime)
        else str(data["push_time"])
    )

    # 维度列表（紧凑版，仅显示状态+说明）
    dim_rows = ""
    for dim in data["dimensions"]:
        icon = dim.get("status", "❓")
        color = _STATUS_COLORS.get(icon, "#8c8c8c")
        dim_rows += (
            f'<tr>'
            f'<td style="padding:6px 10px;font-weight:500;font-size:13px;">{dim.get("dimension","")}</td>'
            f'<td style="padding:6px 10px;text-align:center;font-size:16px;">{icon}</td>'
            f'<td style="padding:6px 10px;color:{color};font-size:13px;">{dim.get("explanation","")}</td>'
            f'</tr>'
        )
    if not dim_rows:
        dim_rows = '<tr><td colspan="3" style="text-align:center;color:#999;padding:12px;">暂无结构化数据</td></tr>'

    focus_items_html = ""
    if data["focus_items"]:
        items = "".join(f"<li>{item}</li>" for item in data["focus_items"])
        focus_items_html = (
            f'<div style="margin-top:10px;padding:10px;background:#fff7e6;'
            f'border-left:3px solid #fa8c16;border-radius:3px;font-size:13px;">'
            f'<b style="color:#fa8c16;">重点关注项</b>'
            f'<ol style="margin:4px 0 0;padding-left:18px;color:#555;">{items}</ol></div>'
        )

    header_bg = "#ff4d4f" if data["inconsistency"] else "#52c41a"
    status_text = "发现不一致 ❌" if data["inconsistency"] else "记录一致 ✅"
    conclusion_text = data["overall_conclusion"] or status_text

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>质控提醒 - {data['patient_name']}</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0;}}
    body{{font-family:"Microsoft YaHei",Arial,sans-serif;background:#f5f7fa;font-size:14px;}}
    .popup-header{{background:{header_bg};color:#fff;padding:12px 16px;}}
    .popup-header h2{{font-size:16px;margin-bottom:4px;}}
    .popup-header .meta{{font-size:12px;opacity:.9;}}
    .popup-body{{padding:12px 16px;}}
    .section{{font-weight:bold;color:#1890ff;margin:10px 0 6px;font-size:13px;
      border-bottom:1px solid #e8f4ff;padding-bottom:4px;}}
    table{{width:100%;border-collapse:collapse;}}
    th{{background:#f0f5ff;padding:6px 10px;text-align:left;font-size:12px;font-weight:600;}}
    td{{border-bottom:1px solid #f5f5f5;}}
    .conclusion{{padding:8px 12px;background:{'#fff2f0' if data['inconsistency'] else '#f6ffed'};
      border-left:3px solid {header_bg};border-radius:3px;
      color:{'#cf1322' if data['inconsistency'] else '#389e0d'};font-size:13px;margin-top:6px;}}
    .popup-footer{{padding:8px 16px;border-top:1px solid #f0f0f0;
      display:flex;justify-content:space-between;align-items:center;}}
    .btn{{padding:6px 16px;border-radius:4px;cursor:pointer;border:none;font-size:13px;}}
    .btn-view{{background:#1890ff;color:#fff;}}
    .btn-close{{background:#f0f0f0;color:#333;}}
  </style>
</head>
<body>
  <div class="popup-header">
    <h2>质控提醒：{status_text}</h2>
    <div class="meta">
      患者：{data['patient_name']} | 科室：{data['dept']} | 日期：{data['query_date']} | 住院号：{data['admission_no'] or '—'}
    </div>
  </div>
  <div class="popup-body">
    <div class="section">审计维度</div>
    <table>
      <thead><tr>
        <th>维度</th><th style="text-align:center;width:50px;">状态</th><th>说明</th>
      </tr></thead>
      <tbody>{dim_rows}</tbody>
    </table>
    <div class="section">总体结论</div>
    <div class="conclusion">{conclusion_text}</div>
    {focus_items_html}
  </div>
  <div class="popup-footer">
    <span style="color:#999;font-size:12px;">推送时间：{push_time_str}</span>
    <div style="display:flex;gap:8px;">
      <button class="btn btn-view" onclick="window.open('/report/{log_id}','_blank')">查看完整报告</button>
      <button class="btn btn-close" onclick="window.close()">关闭</button>
    </div>
  </div>
</body>
</html>"""

    headers = {"X-Frame-Options": "SAMEORIGIN"}
    return HTMLResponse(content=html, headers=headers)
