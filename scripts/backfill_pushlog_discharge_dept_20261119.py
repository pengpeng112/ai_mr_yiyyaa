# -*- coding: utf-8 -*-
"""PushLog.discharge_dept 历史行回填脚本（WP01 T4，064 总计划）。

默认 --dry-run 只统计；--apply --batch 2000 --limit N 才分批写。
每批只读 id/request_json（Python 侧 json.loads 解析出院科室），每批独立提交、
失败回滚并继续；只处理 discharge_dept IS NULL 的行；输出脱敏统计。
本脚本不在生产自动执行——生产运行需运维批准：
    python scripts/backfill_pushlog_discharge_dept_20261119.py                # dry-run
    python scripts/backfill_pushlog_discharge_dept_20261119.py --apply --batch 2000
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_discharge_dept")


def _extract_discharge_dept(request_json: str) -> str:
    """从 request_json 提取出院科室名称（与 push_log_writer._extract_discharge_dept 同口径）。"""
    try:
        payload = json.loads(request_json) if request_json else {}
    except (ValueError, TypeError):
        return ""
    info = payload.get("patient_info", {}) if isinstance(payload.get("patient_info"), dict) else {}
    value = str(info.get("discharge_dept_name") or info.get("discharge_dept_code") or "").strip()
    return value[:120] if value else ""


def run_backfill(db, *, apply: bool = False, batch_size: int = 2000, limit: int = 0) -> dict:
    """按主键游标分批回填 PushLog.discharge_dept（常数内存，避免全表 CLOB 驻留）。"""
    from app.models import PushLog

    step = max(1, int(batch_size or 2000))
    last_id = 0
    processed = updated = skipped_empty = failed_batches = batches = 0
    logger.info("开始回填 apply=%s batch=%d limit=%d", apply, step, limit)

    while True:
        if limit > 0:
            remaining = limit - processed
            if remaining <= 0:
                break
            fetch_limit = min(step, remaining)
        else:
            fetch_limit = step

        rows = (
            db.query(PushLog.id, PushLog.request_json)
            .filter(PushLog.discharge_dept.is_(None), PushLog.id > last_id)
            .order_by(PushLog.id)
            .limit(fetch_limit)
            .all()
        )
        if not rows:
            break

        batches += 1
        last_id = int(rows[-1][0])
        processed += len(rows)

        dept_map: dict[int, str] = {}
        for rid, req in rows:
            value = _extract_discharge_dept(req or "")
            if value:
                dept_map[int(rid)] = value
            else:
                skipped_empty += 1

        if apply and dept_map:
            try:
                for rid, value in dept_map.items():
                    db.query(PushLog).filter(
                        PushLog.id == rid, PushLog.discharge_dept.is_(None)
                    ).update({"discharge_dept": value}, synchronize_session=False)
                db.commit()
                updated += len(dept_map)
            except Exception as exc:
                db.rollback()
                failed_batches += 1
                logger.error("批次提交失败(已回滚继续): error_type=%s", type(exc).__name__)
        elif apply:
            db.commit()

        db.expire_all()
        logger.info(
            "进度 processed=%d updated=%d skipped_empty=%d failed_batches=%d",
            processed, updated, skipped_empty, failed_batches,
        )

    # dry-run 时回滚任何意外变更（不该有）
    if not apply:
        db.rollback()

    return {
        "updated": updated,
        "total": processed,
        "skipped_empty": skipped_empty,
        "failed_batches": failed_batches,
        "batches": batches,
        "apply": bool(apply),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="回填 PushLog.discharge_dept（默认 dry-run）")
    parser.add_argument("--apply", action="store_true", help="真实写库（缺省 dry-run 只统计）")
    parser.add_argument("--batch", type=int, default=2000, help="每批行数（默认 2000）")
    parser.add_argument("--limit", type=int, default=0, help="最多处理行数（0=不限）")
    args = parser.parse_args()

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        stats = run_backfill(
            db, apply=args.apply, batch_size=args.batch, limit=args.limit,
        )
        print(
            f"BACKFILL_DONE updated={stats['updated']} total={stats['total']} "
            f"skipped_empty={stats['skipped_empty']} "
            f"failed_batches={stats['failed_batches']} apply={stats['apply']}"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
