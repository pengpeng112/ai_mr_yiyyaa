# -*- coding: utf-8 -*-
"""规则中心管理 CLI（039 §5.5）::

    python -m prearchive.rule_admin import-files --dry-run   # 默认：只报告
    python -m prearchive.rule_admin import-files --apply     # 显式落库
    python -m prearchive.rule_admin compare-fixtures         # file vs registry 零差异

在 prearchive_service/ 目录下运行；--config 指定配置文件（默认 config.json）。
--apply 落库位置由 result_store 决定（sqlite 本地 / oracle 生产需 DDL 先行）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import ConfigError, load_config, resolve_base_dir, resolve_path
from .models import (
    build_oracle_engine,
    build_oracle_session_factory,
    build_session_factory,
    build_sqlite_engine,
)
from .rule_repository import RuleRepository
from .rule_service import Actor, RuleService, compare_outputs

DOMAIN_MAP = {
    "system_push_rules.json": ("system_push", "system_push"),
    "example_rules.json": ("medical_record", "paperless_t_mark_item"),
}


def _build_repository(config: dict, base_dir: Path) -> RuleRepository:
    store_cfg = config.get("result_store") or {}
    store_type = str(store_cfg.get("type") or "sqlite")
    if store_type == "sqlite":
        db_path = resolve_path(base_dir, store_cfg.get("sqlite_path")
                               or "data/prearchive_result.db")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        engine = build_sqlite_engine(str(db_path))
        session_factory = build_session_factory(engine)   # 自动建表（SQLite 原型）
    elif store_type == "oracle":
        engine = build_oracle_engine(
            dsn=str(store_cfg.get("oracle_dsn") or ""),
            user=str(store_cfg.get("oracle_user") or ""),
            password=str(store_cfg.get("oracle_password_enc") or ""),
        )
        session_factory = build_oracle_session_factory(engine)   # 不做自动 DDL
    else:
        raise ConfigError(f"result_store.type must be sqlite/oracle, got {store_type!r}")
    return RuleRepository(session_factory)


def _rule_paths(config: dict, base_dir: Path) -> list:
    rules_cfg = config.get("rules") or {}
    paths = [resolve_path(base_dir, rules_cfg.get("rules_file"))]
    for extra in (rules_cfg.get("extra_rules_files")
                  or ["rules/system_push_rules.json"]):
        paths.append(resolve_path(base_dir, extra))
    return paths


def cmd_import_files(args) -> int:
    config = load_config(args.config)
    base_dir = resolve_base_dir(args.config)
    repository = _build_repository(config, base_dir)
    service = RuleService(repository)
    paths = _rule_paths(config, base_dir)
    domain_map = {name: values[0] for name, values in DOMAIN_MAP.items()}
    origin_map = {name: values[1] for name, values in DOMAIN_MAP.items()}
    report = service.import_files(
        paths, apply=args.apply, actor=Actor(id="cli:rule_admin", name="rule_admin"),
        domain_map=domain_map, origin_map=origin_map)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["conflicts"] or report["errors"]:
        return 2
    return 0


def cmd_compare_fixtures(args) -> int:
    """fixture 零差异验证：file 与 registry 全 fixture 跑一遍比对问题集合。"""
    from .engine import RuleEngine
    from tests.helpers import make_ctx   # noqa: F401 — 供 --ctx 扩展用（当前用默认）

    config = load_config(args.config)
    base_dir = resolve_base_dir(args.config)
    repository = _build_repository(config, base_dir)
    service = RuleService(repository)
    paths = _rule_paths(config, base_dir)

    file_specs, file_version = __import__(
        "prearchive.rules", fromlist=["load_rules_multi"]).load_rules_multi(
        [str(p) for p in paths])
    effective = service.effective_rules("compare", paths)
    registry_specs = effective["registry_specs"]

    if len(file_specs) != len(registry_specs):
        print(json.dumps({
            "ok": False, "reason": "rule count mismatch",
            "file": len(file_specs), "registry": len(registry_specs),
        }, ensure_ascii=False))
        return 2

    file_engine = RuleEngine(file_specs, rule_version=file_version)
    reg_version = effective["rule_version"] if effective["rule_version"] else "+".join(
        effective["set_versions"])
    reg_engine = RuleEngine(registry_specs, rule_version=reg_version)

    ctx = make_ctx()
    file_output = file_engine.evaluate(ctx)
    reg_output = reg_engine.evaluate(ctx)
    diffs = compare_outputs(file_output, reg_output)
    verdict = {
        "ok": not diffs,
        "file_version": file_version,
        "registry_version": reg_version,
        "rule_count": len(file_specs),
        "diffs": diffs,
    }
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 0 if verdict["ok"] else 2


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m prearchive.rule_admin")
    parser.add_argument("--config", default="config.json")
    sub = parser.add_subparsers(dest="command", required=True)

    p_import = sub.add_parser("import-files")
    p_import.add_argument("--dry-run", action="store_true", default=True)
    p_import.add_argument("--apply", action="store_true")
    p_import.set_defaults(func=cmd_import_files)

    p_compare = sub.add_parser("compare-fixtures")
    p_compare.set_defaults(func=cmd_compare_fixtures)

    args = parser.parse_args(argv)
    if args.command == "import-files" and not args.apply:
        args.apply = False   # dry-run 默认
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
