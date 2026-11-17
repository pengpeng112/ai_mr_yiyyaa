"""一次性清理换源前遗留的旧 jhemr.operation 手术事件（2026-11-14 补丁 4）。

背景：手术源切换 HIS.OPERATION_MASTER（operation_no 统一 "HIS-{OPER_ID}"）后，
tl_event 中仍冻结着换源前按 jhemr.operation_no 建的旧事件（uid 第四段无 HIS-
前缀），干扰影子统计与未来对账。本脚本仅操作 84 本地应用库 tl_event /
tl_event_history（任务书授权），不连 177/216。

范围：rule_code IN ('OP_REC','POSTOP_FIRST_COURSE','PREOP_SUMMARY') 且
source_ref_json 的 source_unique_id 不以 "HIS-" 开头（json.dumps 固定格式
'{"source_unique_id": "...'}，按前缀 LIKE 精确命中）。

用法（84 容器）：
    docker exec -w /app med-audit python scripts/timeliness/cleanup_legacy_op_events_20261114.py [--dry-run]

幂等：清理后无匹配行，重复执行返回 0。
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("cleanup_legacy_op_events")

from sqlalchemy import text  # noqa: E402

from app.database import SessionLocal  # noqa: E402

LEGACY_RULES = ("OP_REC", "POSTOP_FIRST_COURSE", "PREOP_SUMMARY")
# source_ref_json 由 json.dumps({"source_unique_id": x}, ensure_ascii=False) 生成，
# 键序固定、分隔符固定（": "），前缀 LIKE 可精确区分 HIS-/非 HIS- 源。
LEGACY_LIKE = '{"source_unique_id": "HIS-%'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="清理换源前旧 jhemr 手术冻结事件（幂等）")
    parser.add_argument("--dry-run", action="store_true", help="只打印将清理条数，不写库")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        # cx_Oracle 兼容：IN 展开 + NOT LIKE 转义（JSON 定界符含 { " : 无需转义）。
        binds = {f"r{i}": code for i, code in enumerate(LEGACY_RULES)}
        in_sql = ", ".join(f":{k}" for k in binds)
        count = db.execute(text(f"""
            SELECT COUNT(*) FROM med_tl_event
            WHERE rule_code IN ({in_sql})
              AND source_ref_json NOT LIKE :his_prefix
              AND source_ref_json LIKE :ref_prefix
        """), {**binds, "his_prefix": LEGACY_LIKE, "ref_prefix": '{"source_unique_id": "%'}).scalar()
        logger.info("待清理旧源手术事件: %s 条（规则=%s）", count, list(LEGACY_RULES))
        if args.dry_run or not count:
            if args.dry_run:
                db.rollback()
            else:
                db.commit()
            print(json.dumps({"dry_run": args.dry_run, "legacy_events": int(count), "deleted": 0}))
            return 0
        deleted_hist = db.execute(text(f"""
            DELETE FROM med_tl_event_history WHERE event_id IN (
                SELECT id FROM med_tl_event
                WHERE rule_code IN ({in_sql})
                  AND source_ref_json NOT LIKE :his_prefix
                  AND source_ref_json LIKE :ref_prefix
            )
        """), {**binds, "his_prefix": LEGACY_LIKE, "ref_prefix": '{"source_unique_id": "%'}).rowcount
        deleted = db.execute(text(f"""
            DELETE FROM med_tl_event
            WHERE rule_code IN ({in_sql})
              AND source_ref_json NOT LIKE :his_prefix
              AND source_ref_json LIKE :ref_prefix
        """), {**binds, "his_prefix": LEGACY_LIKE, "ref_prefix": '{"source_unique_id": "%'}).rowcount
        db.commit()
        logger.info("已删除事件 %s 条 / 历史 %s 条", deleted, deleted_hist)
        print(json.dumps({"dry_run": False, "legacy_events": int(count),
                          "deleted_events": int(deleted), "deleted_history": int(deleted_hist)}))
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
