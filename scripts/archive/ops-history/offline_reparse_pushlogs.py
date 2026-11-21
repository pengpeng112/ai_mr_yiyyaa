#!/usr/bin/env python3
"""
003 G 安全轨：离线重解析已存 raw response（默认 dry-run）。

约束：
- 默认 dry_run=True，不写库、不调 Dify、不发告警
- 仅重新解析 response_json / ai_result 中的结构化输出
- 不覆盖原始 response
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True, help="含 push_logs[].response_json 的脱敏 fixture")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--write", action="store_true", help="显式关闭 dry-run（仍不写应用库，只输出报告）")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from app.dify_pusher import parse_dify_structured_output

    data = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    logs = data.get("push_logs") or []
    report = {"total": 0, "recovered": 0, "still_failed": 0, "items": []}
    for row in logs:
        if str(row.get("parse_status") or "") != "failed":
            continue
        report["total"] += 1
        raw = row.get("response_json") or row.get("ai_result") or "{}"
        try:
            outputs = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except json.JSONDecodeError:
            outputs = {"result": raw}
        if not isinstance(outputs, dict):
            outputs = {"result": outputs}
        parsed = parse_dify_structured_output(
            outputs,
            output_key="result",
            audit_type_code=str(row.get("audit_type_code") or ""),
        )
        ok = bool(parsed.get("parse_success"))
        if ok:
            report["recovered"] += 1
        else:
            report["still_failed"] += 1
        report["items"].append(
            {
                "id": row.get("id"),
                "audit_type_code": row.get("audit_type_code"),
                "recovered": ok,
                "parse_error": parsed.get("parse_error", ""),
                "dimensions": len(parsed.get("dimensions") or []),
            }
        )

    report["dry_run"] = not args.write
    report["note"] = "未写库、未调 Dify、未发告警；生产写回须 G 批准"
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
