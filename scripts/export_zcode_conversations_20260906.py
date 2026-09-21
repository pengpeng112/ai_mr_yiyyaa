# -*- coding: utf-8 -*-
"""导出 ZCode 在指定项目下的全部会话对话，供其他 AI/工具获取分析（2026-09-06）。

数据源：ZCode CLI 本地库 ``C:\\Users\\<user>\\.zcode\\cli\\db\\db.sqlite``（只读打开）。
表结构：session(directory=项目路径) → message(role) → part(type=text/tool/reasoning)。

用法（仓库根运行）::

    # 默认：本项目全部主会话 → review/conversations-export-20260906/
    python scripts/export_zcode_conversations_20260906.py

    # 含子代理会话 + 工具调用详情 + 敏感串打码
    python scripts/export_zcode_conversations_20260906.py --include-subagents \
        --include-tools --redact --out review/conversations-export-20260906-full

注意：导出内容可能含生产服务器地址/端口等运维信息；按
`开发起步包/00_AI协作规则.md` §7，外发公网模型前请先人工过一遍或保持 --redact。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = r"C:\Users\Administrator\.zcode\cli\db\db.sqlite"
DEFAULT_PROJECT = r"F:\python\前后端代码\ai_mrzk"

# 敏感串打码（--redact）：长 hex / Bearer / 常见 password= 形态
_HEX32 = re.compile(r"\b[0-9a-fA-F]{32,}\b")
_BEARER = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]{16,}", re.IGNORECASE)
_PASSY = re.compile(r"(password|secret|token)([\"\s:=]+)([^\"'\s,;]{6,})", re.IGNORECASE)


def _ts(ms) -> str:
    if not ms:
        return "-"
    return _dt.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


def redact(text: str) -> str:
    text = _BEARER.sub(r"\1***REDACTED***", text)
    text = _HEX32.sub("***HEX***", text)
    text = _PASSY.sub(r"\1\2***REDACTED***", text)
    return text


def _slug(text: str, limit: int = 40) -> str:
    keep = re.sub(r"[\\/:*?\"<>|\r\n\t ]+", "-", (text or "").strip())
    return (keep[:limit] or "untitled")


def load_sessions(cur, project: str, include_subagents: bool):
    sql = "SELECT id, title, parent_id, time_created, time_updated, task_type FROM session WHERE directory = ?"
    if not include_subagents:
        sql += " AND parent_id IS NULL"
    sql += " ORDER BY time_created"
    return cur.execute(sql, (project,)).fetchall()


def render_session(cur, sess, include_tools: bool, do_redact: bool,
                   tool_output_chars: int) -> tuple[str, dict]:
    sid, title, parent, t0, t1, task_type = sess
    messages = cur.execute(
        "SELECT id, data, sequence FROM message WHERE session_id = ? ORDER BY sequence",
        (sid,)).fetchall()

    heading = title or "(无标题会话)"
    lines = [f"# {heading}", ""]
    meta = {"id": sid, "messages": 0, "texts": 0, "tools": 0}
    lines += [
        f"- 会话ID：`{sid}`",
        f"- 类型：{'子代理' if parent else '主会话'}（{task_type or '-'}）",
        f"- 时间：{_ts(t0)} ~ {_ts(t1)}",
        f"- 消息数：{len(messages)}",
        "",
        "---",
        "",
    ]

    for mid, mdata, _seq in messages:
        try:
            md = json.loads(mdata)
        except (ValueError, TypeError):
            md = {}
        role = str(md.get("role") or "unknown")
        parts = cur.execute(
            "SELECT data, sequence FROM part WHERE message_id = ? ORDER BY sequence",
            (mid,)).fetchall()
        body: list[str] = []
        for pdata, _pseq in parts:
            try:
                pd = json.loads(pdata)
            except (ValueError, TypeError):
                continue
            ptype = pd.get("type")
            if ptype == "text":
                text = str(pd.get("text") or "").strip()
                if text:
                    body.append(text)
                    meta["texts"] += 1
            elif ptype == "tool" and include_tools:
                tool = pd.get("tool") or "?"
                state = pd.get("state") or {}
                inp = state.get("input") or {}
                key_input = ", ".join(
                    f"{k}={str(v)[:60]}" for k, v in list(inp.items())[:3])
                status = state.get("status") or "?"
                one = f"> 🔧 {tool}({key_input}) → {status}"
                out = str(state.get("output") or "").strip()
                if out and tool_output_chars > 0:
                    one += "\n> ```\n> " + "\n> ".join(
                        out[:tool_output_chars].splitlines()[:12]) + "\n> ```"
                body.append(one)
                meta["tools"] += 1
        if not body:
            continue
        meta["messages"] += 1
        stamp = _ts(md.get("time")) if isinstance(md.get("time"), (int, float)) else ""
        who = {"user": "👤 用户", "assistant": "🤖 助手", "system": "⚙️ 系统"}.get(role, role)
        lines.append(f"## [{meta['messages']}] {who}  {stamp}")
        lines.append("")
        text_out = "\n\n".join(body)
        if do_redact:
            text_out = redact(text_out)
        lines.append(text_out)
        lines.append("")

    return "\n".join(lines), meta


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="导出 ZCode 项目会话供其他 AI 分析")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--out", default="review/conversations-export-20260906")
    parser.add_argument("--include-subagents", action="store_true",
                        help="包含子代理（Explore/任务分派）会话")
    parser.add_argument("--include-tools", action="store_true",
                        help="包含工具调用摘要（默认只导对话正文）")
    parser.add_argument("--tool-output-chars", type=int, default=0,
                        help="工具输出截取长度（0=不附输出，仅状态行）")
    parser.add_argument("--redact", action="store_true",
                        help="打码 Bearer/32+hex/password 形态的敏感串")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"[export] 找不到 ZCode 库: {db_path}", file=sys.stderr)
        return 2
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
    cur = con.cursor()
    sessions = load_sessions(cur, args.project, args.include_subagents)
    print(f"[export] 项目 {args.project} 会话 {len(sessions)} 个"
          f"（子代理={'含' if args.include_subagents else '不含'}）→ {out_dir}")

    index_rows = []
    for i, sess in enumerate(sessions, 1):
        sid, title = sess[0], sess[1]
        markdown, meta = render_session(cur, sess, args.include_tools,
                                        args.redact, args.tool_output_chars)
        fname = f"{i:02d}_{_ts(sess[3])[:10]}_{_slug(title)}.md"
        (out_dir / fname).write_text(markdown, encoding="utf-8")
        index_rows.append((fname, sid, title or "(无标题)", meta))
        print(f"  [{i:02d}/{len(sessions)}] {fname} "
              f"(消息 {meta['messages']}/文本 {meta['texts']})")

    con.close()

    readme = [
        "# ZCode 会话导出（供其他 AI 分析）",
        "",
        f"- 生成时间：{_dt.datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- 项目目录：`{args.project}`",
        f"- 会话数：{len(index_rows)}（{'含' if args.include_subagents else '不含'}子代理；"
        f"工具调用{'含摘要' if args.include_tools else '不含'}；"
        f"敏感串{'已打码' if args.redact else '未打码'}）",
        "- 数据源：ZCode CLI 本地 SQLite（session/message/part 三表），只读导出",
        "",
        "## 阅读顺序建议",
        "1. 先看本 INDEX.md 了解全部会话清单；",
        "2. 按编号顺序读（时间序）；",
        "3. 结合仓库内 `开发起步包/01_统一修改记录.md`（跨 AI 权威交接台账）与 `docs/INDEX.md` 交叉验证。",
        "",
        "## 隐私提示",
        "对话可能含生产服务器地址/端口/容器名与运维细节；请勿将未打码导出上传公网服务。",
        "",
        "## 会话清单",
        "",
        "| # | 文件 | 会话ID | 标题 | 消息/文本 |",
        "|---|---|---|---|---|",
    ]
    for fname, sid, title, meta in index_rows:
        readme.append(f"| {fname[:2]} | {fname} | `{sid[:36]}` | {title} | {meta['messages']}/{meta['texts']} |")
    (out_dir / "INDEX.md").write_text("\n".join(readme), encoding="utf-8")
    print(f"[export] 完成：{len(index_rows)} 个会话 + INDEX.md → {out_dir.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
