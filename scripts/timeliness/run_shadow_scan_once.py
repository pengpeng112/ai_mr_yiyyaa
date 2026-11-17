"""一次性影子扫描入口（病历时效质控 T4）。

两种运行模式：
1. 本地假数据演练（本任务交付时验证用，不连生产、不碰应用库）：
   python scripts/timeliness/run_shadow_scan_once.py --fixture <json> \
       [--db-path review/timeliness/T4_shadow.sqlite] [--enable ADM_REC,FIRST_COURSE] \
       [--dry-run] [--json]
   fixture JSON 键：inpatients/discharges/operations/files/consult_applies/
   limit_logs（行结构同 T1 列口径）；可选键 permission_error_table=表名，
   用于演练 TimelinessPermissionMissing 安全退出路径。
   fixture 模式使用隔离 SQLite（只建 7 张 tl_* 表 + 种子），运行锁用进程内
   空实现（一次性脚本无需跨进程锁）。

2. 真实扫描（授权后由用户在 84 容器内运行，AI 不执行）：
   python scripts/timeliness/run_shadow_scan_once.py [--dry-run] [--enable ...] [--json]
   要求 config.json timeliness.enabled=true + 口令（环境变量
   TIMELINESS_JHEMR_PASSWORD 或 password_enc）；只读账号固定 aizk_user。
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# 保证以 `python scripts/timeliness/run_shadow_scan_once.py` 直跑时可导入 app 包。
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.timeliness.config import TimelinessPermissionMissing  # noqa: E402
from app.timeliness.models import (  # noqa: E402
    TLActionLog,
    TLApproval,
    TLEvent,
    TLEventHistory,
    TLRule,
    TLRuleVersion,
    TLScanRun,
)
from app.timeliness.rules_seed import seed_rules  # noqa: E402
from app.timeliness.scanner import (  # noqa: E402
    JhemrModuleReader,
    TimelinessScanner,
)

DEFAULT_FIXTURE_DB = "review/timeliness/T4_shadow.sqlite"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("run_shadow_scan_once")

TIMELINESS_TABLE_MODELS = (TLRule, TLRuleVersion, TLEvent, TLEventHistory,
                           TLActionLog, TLScanRun, TLApproval)


class FixtureReader:
    """按 fixture JSON 返回数据的假 Reader（本地演练专用）。"""

    def __init__(self, data: dict):
        self._data = data or {}

    def _permission_guard(self) -> None:
        table = str(self._data.get("permission_error_table") or "").strip()
        if table:
            raise TimelinessPermissionMissing(f"jhemr.{table}")

    def list_inpatients(self) -> list[dict]:
        self._permission_guard()
        return list(self._data.get("inpatients") or [])

    def list_recent_discharges(self, days: int) -> list[dict]:
        self._permission_guard()
        return list(self._data.get("discharges") or [])

    def _by_pairs(self, rows: list[dict], patient_visits) -> list[dict]:
        wanted = {
            (str(p[0]).strip(), str(p[1]).strip()) for p in patient_visits or ()
        }
        return [
            row for row in rows
            if (str(row.get("patient_id") or "").strip(),
                str(row.get("visit_id") or "").strip()) in wanted
        ]

    def list_files(self, patient_visits) -> list[dict]:
        self._permission_guard()
        return self._by_pairs(list(self._data.get("files") or []), patient_visits)

    def list_operations(self, patient_visits) -> list[dict]:
        self._permission_guard()
        return self._by_pairs(list(self._data.get("operations") or []), patient_visits)

    def list_consult_applies(self, since) -> list[dict]:
        self._permission_guard()
        return list(self._data.get("consult_applies") or [])

    def list_limit_logs(self, since) -> list[dict]:
        self._permission_guard()
        return list(self._data.get("limit_logs") or [])


class _NoopLock:
    """fixture 一次性演练的进程内空锁（真实模式用 scheduler_lock_service）。"""

    def acquire(self):
        return True, "fixture-local", "acquired"

    def release(self, owner_id: str) -> None:
        return None


def _build_fixture_session(db_path: str):
    """隔离 SQLite：只建 7 张 tl_* 表 + 幂等种子（不碰应用库与 data/）。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(
        engine, tables=[model.__table__ for model in TIMELINESS_TABLE_MODELS]
    )
    db = sessionmaker(bind=engine, autoflush=False)()
    result = seed_rules(db)
    logger.info("fixture 库种子: created=%s skipped=%s", result["created"], result["skipped"])
    return db


def _enable_rules(db, codes: list[str]) -> list[str]:
    enabled = []
    for code in codes:
        rule = db.query(TLRule).filter(TLRule.rule_code == code.strip()).first()
        if rule is None:
            logger.warning("待启用规则不存在: %s", code)
            continue
        rule.enabled = True
        enabled.append(rule.rule_code)
    db.commit()
    return enabled


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="病历时效影子扫描一次性入口（T4）")
    parser.add_argument("--fixture", help="本地假数据 JSON（演练模式，不连生产）")
    parser.add_argument("--db-path", default=DEFAULT_FIXTURE_DB,
                        help="fixture 模式隔离 SQLite 路径（默认 review/timeliness/T4_shadow.sqlite）")
    parser.add_argument("--enable", default="",
                        help="逗号分隔的规则编码，扫描前启用（fixture 写隔离库；真实模式写应用库）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只取数试算并输出统计，不写任何台账")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出摘要")
    args = parser.parse_args(argv)

    codes = [c.strip() for c in args.enable.split(",") if c.strip()]
    if args.fixture:
        data = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
        db = _build_fixture_session(args.db_path)
        reader = FixtureReader(data)
        acquire = _NoopLock().acquire
        release = _NoopLock().release
    else:
        from app.database import SessionLocal

        db = SessionLocal()
        reader = JhemrModuleReader()
        acquire = None   # 使用 scanner 默认（scheduler_lock_service, 锁名 timeliness_scan）
        release = None
        seed_result = seed_rules(db)
        # 2026-11-13 返工：seed_rules 返回值新增 upgraded（仍处 v1 初始种子且未被人工
        # 改过的规则被升级到当前种子口径：mr_class 扩充 + penalty 200 + D8 解锁备注）。
        logger.info("应用库种子幂等检查: created=%s skipped=%s upgraded=%s",
                    seed_result["created"], seed_result["skipped"],
                    seed_result.get("upgraded", []))

    try:
        if codes:
            enabled = _enable_rules(db, codes)
            logger.info("已启用规则: %s", enabled)
        scanner_kwargs = {"acquire_lock": acquire, "release_lock": release} if args.fixture else {}
        if not args.fixture:
            # 2026-11-14 七规则轮：真实模式接 HIS 医嘱/手术/职称源（与调度路径一致）；
            # fixture 演练模式保持纯假数据不连任何库。
            from app.timeliness.scanner import (
                build_default_his_reader,
                register_his_sources_if_available,
            )

            his_reader = build_default_his_reader()
            registered = register_his_sources_if_available(his_reader)
            logger.info("HIS 源: adapter=%s rescue_source_registered=%s",
                        "ready" if his_reader is not None else "disabled", registered)
            scanner_kwargs["his_reader"] = his_reader
        scanner = TimelinessScanner(db, reader, **scanner_kwargs)
        summary = scanner.dry_run() if args.dry_run else scanner.run_scan()
        if args.json:
            print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        else:
            logger.info("扫描摘要: %s", summary)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
