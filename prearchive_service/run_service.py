# -*- coding: utf-8 -*-
"""预检服务入口（本地原型）。

用法（在 prearchive_service/ 目录下）::

    # fixture 演示模式：假源数据跑一轮（不连任何真实库），随后起 API 常驻
    python run_service.py --fixtures

    # fixture 演示模式：只跑一轮就退出（联调/冒烟）
    python run_service.py --fixtures --once

    # 真实模式：需先配置 config.json（加密凭据）+ 网络开通（当前全部占位，未开通）
    python run_service.py --config config.json

零生产接触：真实模式在四源未配置/未开通时会因占位符在首查时失败并被
fail-open 记录，不会对任何真实库发起连接（占位 DSN 无法解析即失败）。
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from prearchive import __version__                                   # noqa: E402
from prearchive.config import (                                      # noqa: E402
    ConfigError,
    get_fernet,
    load_config,
    resolve_base_dir,
    resolve_path,
    resolve_push_secret,
    resolve_source_password,
)
from prearchive.collectors import (                                  # noqa: E402
    HisCollector,
    JhemrCollector,
    LisCollector,
    PatientContextBuilder,
    SmCollector,
    SqlHisGateway,
    SqlJhemrGateway,
    SqlLisGateway,
    SqlSmGateway,
)
from prearchive.engine import RuleEngine                             # noqa: E402
from prearchive.fixture_sources import build_demo_fixtures           # noqa: E402
from prearchive.heartbeat import Heartbeat                           # noqa: E402
from prearchive.models import build_session_factory, build_sqlite_engine  # noqa: E402
from prearchive.pusher import UrllibSender, WeComPusher              # noqa: E402
from prearchive.rules import load_rules, rules_version               # noqa: E402
from prearchive.store import ResultRepository                        # noqa: E402
from prearchive.trigger import (                                     # noqa: E402
    PrecheckProcessor,
    RunLock,
    StateStore,
    TriggerPoller,
)


def setup_logging(log_config: dict) -> None:
    level = str((log_config or {}).get("level") or "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    log_file = (log_config or {}).get("file")
    if log_file:
        try:
            path = Path(log_file)
            if not path.is_absolute():
                path = BASE_DIR / path
            path.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(path, encoding="utf-8")
            handler.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)s [%(name)s] %(message)s"))
            logging.getLogger().addHandler(handler)
        except Exception:
            pass   # 日志文件失败不阻断服务


def build_stack(config: dict, config_path: str, fixtures: bool):
    """组装采集/引擎/存储/推送/轮询栈。fixtures=True 全假源。"""
    base_dir = resolve_base_dir(config_path)
    service_cfg = config.get("service") or {}

    if fixtures:
        gateways = build_demo_fixtures()
        jhemr_collector = JhemrCollector(gateways["jhemr"])
        context_builder = PatientContextBuilder(
            jhemr=jhemr_collector,
            his=HisCollector(gateways["his"]),
            sm=SmCollector(gateways["sm"]),
            lis=LisCollector(gateways["lis"]),
        )
    else:
        fernet = get_fernet(config)
        sources = config.get("sources") or {}

        def _resolver(source_name):
            return lambda: resolve_source_password(config, fernet, source_name)

        jhemr_collector = JhemrCollector(
            SqlJhemrGateway(sources.get("jhemr") or {}, _resolver("jhemr")))
        context_builder = PatientContextBuilder(
            jhemr=jhemr_collector,
            his=HisCollector(SqlHisGateway(sources.get("his") or {}, _resolver("his"))),
            sm=SmCollector(SqlSmGateway(sources.get("sm") or {}, _resolver("sm"))),
            lis=LisCollector(SqlLisGateway(sources.get("lis") or {}, _resolver("lis"))),
        )

    rules_path = resolve_path(base_dir, (config.get("rules") or {}).get("rules_file"))
    rules = load_rules(rules_path)
    engine = RuleEngine(rules, rule_version=rules_version(rules_path))

    store_cfg = config.get("result_store") or {}
    if str(store_cfg.get("type") or "sqlite") == "sqlite":
        db_path = resolve_path(base_dir, store_cfg.get("sqlite_path") or "data/prearchive_result.db")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        session_factory = build_session_factory(build_sqlite_engine(str(db_path)))
    else:
        raise ConfigError("oracle result store 尚未接线：请先用 sql/ DDL 手工建表，"
                          "再补 oracle engine 构造（一期原型交付 sqlite 路径）")
    repository = ResultRepository(session_factory)

    push_cfg = dict(config.get("push") or {})
    pusher = WeComPusher(
        push_config=push_cfg,
        secret_provider=lambda: resolve_push_secret(config, get_fernet(config))
        if push_cfg.get("enabled") else "",
        sender=UrllibSender(),
    )

    processor = PrecheckProcessor(context_builder, engine, repository, pusher)

    state_store = StateStore(resolve_path(base_dir, service_cfg.get("state_file")))
    lock = RunLock(resolve_path(base_dir, service_cfg.get("lock_file")))
    heartbeat = Heartbeat(resolve_path(base_dir, service_cfg.get("heartbeat_file")))
    poller = TriggerPoller(
        jhemr_collector=jhemr_collector,
        processor=processor,
        state_store=state_store,
        lock=lock,
        heartbeat=heartbeat,
        interval_seconds=service_cfg.get("poll_interval_seconds", 300),
        batch_limit=service_cfg.get("batch_limit", 100),
        lookback_seconds=service_cfg.get("lookback_seconds", 86400),
    )
    return poller, repository, heartbeat, state_store


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="归档前预检服务（028 一期原型）")
    parser.add_argument("--config", default=str(BASE_DIR / "config.json"),
                        help="配置文件路径（默认 prearchive_service/config.json）")
    parser.add_argument("--fixtures", action="store_true",
                        help="fixture 演示模式（假源，零生产依赖）")
    parser.add_argument("--once", action="store_true",
                        help="只跑一轮轮询即退出（配合 --fixtures 冒烟）")
    parser.add_argument("--no-api", action="store_true", help="不启动 HTTP API")
    args = parser.parse_args(argv)

    if args.fixtures and not Path(args.config).exists():
        config_path = str(BASE_DIR / "config.example.json")
    else:
        config_path = args.config
    config = load_config(config_path)
    setup_logging(config.get("logging") or {})
    logging.getLogger("prearchive").info("prearchive-service %s starting (fixtures=%s)",
                                         __version__, args.fixtures)

    poller, repository, heartbeat, state_store = build_stack(config, config_path,
                                                             fixtures=args.fixtures)

    if args.once:
        stats = poller.poll_once()
        print(f"[once] fetched={stats.fetched} processed={stats.processed} "
              f"skipped_seen={stats.skipped_seen} lock_skipped={stats.lock_skipped} "
              f"watermark={stats.watermark} errors={stats.errors}")
        return 0

    stop_event = threading.Event()
    poll_thread = threading.Thread(
        target=poller.run_forever, kwargs={"stop_event": stop_event},
        name="prearchive-poller", daemon=True)
    poll_thread.start()

    if args.no_api:
        try:
            poll_thread.join()
        except KeyboardInterrupt:
            pass
        finally:
            stop_event.set()
        return 0

    from prearchive.api import create_app

    application = create_app(
        config=config,
        repository=repository,
        heartbeat=heartbeat,
        watermark_provider=lambda: state_store.load().get("watermark"),
        poller=poller,
    )
    api_cfg = config.get("api") or {}
    import uvicorn

    uvicorn.run(application, host=str(api_cfg.get("host") or "127.0.0.1"),
                port=int(api_cfg.get("port") or 8600), log_level="info")
    stop_event.set()
    return 0


if __name__ == "__main__":
    sys.exit(main())
