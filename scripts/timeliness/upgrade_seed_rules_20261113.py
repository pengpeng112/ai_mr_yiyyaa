"""时效规则种子 v1 幂等升级脚本（2026-11-13 返工整改配套；2026-11-14 增量沿用）。

用途：84 容器/本地应用库已按旧口径（T2 种子 v1：DISCHARGE_REC 只有 EMR12.00、
penalty_amount 全 None、ADM_REC 带 D8 封锁备注）种过 18 条规则的老库，把仍处于
初始种子版本（version_no==1 且 created_by=system_seed，即未被人工改过）的规则
升级到**当前代码口径**（upgrade_seeded_v1_rules 从 rules_seed.RULE_SEEDS 现值取
目标字段，故 2026-11-14 扩围精度修正自动包含）：

- ADM_REC / DISCHARGE_REC 的 target_json.mr_class 扩充
  （EMR09.00.01/02/03 已含；DISCHARGE_REC + EMR10.00.13）；
- 12 条意图 LOCK_EMR 的可锁定规则 penalty_amount=200（元/次，主方案 §1.2）；
- ADM_REC 的 D8 封锁备注更新为“2026-11-10 生产销账解除”；
- 2026-11-14：CONSULT_NORMAL/CONSULT_EMERGENCY 目标三 mr_class+“会诊”关键词、
  OP_REC mr_class 扩 EMR10.00.16、OP_REC/POSTOP_FIRST_COURSE 的
  trigger_filter_json 排除 operation_type='0'。

已被人工保存过新版本（version_no>=2）的规则一律不动（幂等、不覆盖人工口径）；
重复执行安全（升级后当前版本变为 v2，不再命中 v1 判定）。

用法（84 容器，真实应用库）：
    docker exec -w /app med-audit python scripts/timeliness/upgrade_seed_rules_20261113.py [--dry-run]

本脚本只写应用库 tl_rule / tl_rule_version（追加版本行），不连接 177 业务库、
不对 JHEMR 做任何写操作。
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# 保证以 `python scripts/timeliness/upgrade_seed_rules_20261113.py` 直跑时可导入 app 包。
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("upgrade_seed_rules")

from app.database import SessionLocal  # noqa: E402
from app.timeliness.rules_seed import upgrade_seeded_v1_rules  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="时效规则种子 v1 → 2026-11-13 口径幂等升级")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印将升级的规则清单，不写库（实现方式：跑完即回滚）")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        # 2026-11-14 补丁 4：--dry-run 真只读——commit=False 在函数内部回滚
        #（此前函数内部 commit 使外层 rollback 无效，dry-run 实写）。
        result = upgrade_seeded_v1_rules(db, commit=not args.dry_run)
        if args.dry_run:
            logger.info("dry-run：以下升级未写库 upgraded=%s", result["upgraded"])
        else:
            logger.info("升级完成 upgraded=%s skipped=%s",
                        result["upgraded"], result["skipped"])
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
