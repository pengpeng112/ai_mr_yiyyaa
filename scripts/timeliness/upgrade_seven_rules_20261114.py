"""七规则种子幂等升级脚本（2026-11-14 HIS 接口轮）。

用途：84 容器/本地应用库中 7 条规则（ATTENDING_FIRST_ROUND / RESCUE_REC /
OP_REC / POSTOP_FIRST_COURSE / PREOP_SUMMARY / DEATH_DISCUSS / DEATH_REC）
升级到 2026-11-14 新种子口径（HIS 医嘱/手术/职称数据接口与审签判定），
并全部置为 ``enabled=True, action_mode='SHADOW'``（任务书 §3.2：仅影子，
严禁 WARN_ONLY/LOCK_EMR 实发）。

幂等与边界：
- 按当前版本内容与目标字段比对，一致则跳过；不一致追加新版本（旧版本不动）；
- 只覆盖 7 条目标规则的版本内容字段与启停，**不触碰**其余 11 条规则
  （含 11-14 已启用的试点 WARN_ONLY 四条——保持原配置不动）；
- 不改 timeliness.jhemr_write 写闸（保持 false）；不连 177/216 写任何数据。

用法（84 容器）：
    docker exec -w /app med-audit python scripts/timeliness/upgrade_seven_rules_20261114.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# 保证以 `python scripts/timeliness/...` 直跑时可导入 app 包。
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("upgrade_seven_rules")

from app.database import SessionLocal  # noqa: E402
from app.timeliness.models import TLRule, TLRuleVersion  # noqa: E402
from app.timeliness.rules_seed import (  # noqa: E402
    VERSION_FIELDS,
    RULE_SEEDS,
    append_rule_version,
)

SEVEN_RULE_CODES = (
    "ATTENDING_FIRST_ROUND",
    "RESCUE_REC",
    "OP_REC",
    "POSTOP_FIRST_COURSE",
    "PREOP_SUMMARY",
    "DEATH_DISCUSS",
    "DEATH_REC",
)
CREATED_BY = "deploy_20261114_his_shadow"


def _seed_fields(rule_code: str) -> dict:
    seed = next(s for s in RULE_SEEDS if s.rule_code == rule_code)
    from app.timeliness.rules_seed import _seed_version_fields

    fields = _seed_version_fields(seed)
    # 任务书 §3.2：7 条全部 SHADOW 影子（种子默认即 SHADOW，显式钉死防漂移）。
    fields["action_mode"] = "SHADOW"
    fields["dept_scope_json"] = "[]"  # 全院影子（不继承试点 dept_scope）
    return fields


def upgrade_seven_rules(db, *, commit: bool = True) -> dict:
    """把 7 条规则升级到新种子口径并启用为 SHADOW；返回升级/跳过/错误清单。

    ``commit=False`` 供 --dry-run 使用：只试算不落库（fix：此前 commit 在函数
    内、dry-run 的外层 rollback 无效，2026-11-14 首次执行时 dry-run 实写——
    内容与真实目标一致且幂等，无副作用差异，已登记；本修复杜绝复发）。
    """
    report = {"upgraded": [], "skipped": [], "enabled": [], "errors": []}
    try:
        for code in SEVEN_RULE_CODES:
            rule = db.query(TLRule).filter(TLRule.rule_code == code).one_or_none()
            if rule is None:
                report["errors"].append(f"{code}: rule not found（先跑 seed_rules）")
                continue
            current = db.get(TLRuleVersion, rule.current_version_id) if rule.current_version_id else None
            if current is None or current.rule_id != rule.id:
                report["errors"].append(f"{code}: missing current version")
                continue
            target = _seed_fields(code)
            differs = any(getattr(current, name) != value for name, value in target.items())
            if differs:
                append_rule_version(db, code, created_by=CREATED_BY, **target)
                report["upgraded"].append(code)
            else:
                report["skipped"].append(code)
            if not rule.enabled:
                rule.enabled = True
                report["enabled"].append(code)
        if commit:
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="7 条规则升级到 2026-11-14 HIS 口径并启用 SHADOW")
    parser.add_argument("--dry-run", action="store_true", help="只打印将升级清单，不写库")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        report = upgrade_seven_rules(db, commit=not args.dry_run)
        if args.dry_run:
            logger.info("dry-run：以下升级未写库 upgraded=%s", report["upgraded"])
        else:
            logger.info("升级完成 upgraded=%s skipped=%s enabled=%s errors=%s",
                        report["upgraded"], report["skipped"], report["enabled"], report["errors"])
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if not report["errors"] else 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
