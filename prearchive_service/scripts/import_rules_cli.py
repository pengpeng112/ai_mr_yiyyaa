# -*- coding: utf-8 -*-
"""规则导入 CLI（WP07 影子激活 6 步之第 4 步；薄包装，不重写导入逻辑）。

复用 `prearchive.rule_service.RuleService.import_files`（幂等：同版本同 SHA 跳过）
与 `prearchive.rule_admin._build_repository` 的配置→仓储构造；本 CLI 只补三个能力：
1. 显式 `--files` 指定规则文件（rule_admin 固定读 config.rules.rules_file 单文件）；
2. `--actor` 自定义操作者（入规则仓审计）；
3. `--apply` 显式落库（不传即 dry-run，零写入）。

用法（WP07 runbook 第 4 步）：
  python prearchive_service/scripts/import_rules_cli.py \
      --config prearchive_service/config.shadow.prod.template.json \
      --files prearchive_service/rules/example_rules.json prearchive_service/rules/system_push_rules.json
  python ... --apply --actor "med-audit-wp07"   # 确认 dry-run 报告无误后落库
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prearchive.config import load_config, resolve_base_dir  # noqa: E402
from prearchive.rule_admin import _build_repository  # noqa: E402  复用配置→仓储构造
from prearchive.rule_service import Actor, RuleService  # noqa: E402


def build_actor(name: str) -> Actor:
    text = str(name or "").strip() or "cli:import_rules"
    return Actor(id=text, name=text, permissions=["*"])


def run_import(config_path: str, files: list[str], apply: bool, actor_name: str) -> dict:
    """加载配置 → 构造 RuleService → import_files；返回报告（不打印）。"""
    config = load_config(config_path)
    base_dir = resolve_base_dir(config_path)
    repository = _build_repository(config, base_dir)
    service = RuleService(repository)
    report = service.import_files(
        files, apply=apply, actor=build_actor(actor_name))
    report["config"] = str(config_path)
    report["actor"] = actor_name
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="规则导入 CLI（薄包装 RuleService.import_files）")
    parser.add_argument("--config", required=True, help="预检服务配置路径（决定规则仓落库位置）")
    parser.add_argument("--files", nargs="+", required=True,
                        help="规则 JSON 文件列表（如 rules/example_rules.json rules/system_push_rules.json）")
    parser.add_argument("--apply", action="store_true", help="显式落库（不传即 dry-run，零写入）")
    parser.add_argument("--actor", default="cli:import_rules", help="操作者名称（入规则仓审计）")
    args = parser.parse_args(argv)

    missing = [f for f in args.files if not Path(f).exists()]
    if missing:
        print(json.dumps({"errors": [f"file not found: {p}" for p in missing]},
                         ensure_ascii=False))
        return 2

    report = run_import(args.config, args.files, args.apply, args.actor)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report.get("conflicts") or report.get("errors"):
        return 2
    if not args.apply:
        print("[import] dry-run 完成（零写入）；确认无误后加 --apply 落库", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
