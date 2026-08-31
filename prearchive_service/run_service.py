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
    ItfSourceCollector,
    JhemrCollector,
    LisCollector,
    PatientContextBuilder,
    SmCollector,
    SqlBlGateway,
    SqlDcnGateway,
    SqlEsGateway,
    SqlHisGateway,
    SqlJhemrGateway,
    SqlLisGateway,
    SqlPacsGateway,
    SqlQgjGateway,
    SqlSmGateway,
    SqlXdGateway,
    SqlXtGateway,
)
from prearchive.context import (                                     # noqa: E402
    SRC_BL_ITF,
    SRC_DCN_REPORT,
    SRC_ES_ITF,
    SRC_PACS_ITF,
    SRC_QGJ_ITF,
    SRC_XD_ITF,
    SRC_XT_ITF,
)
from prearchive.engine import RuleEngine                             # noqa: E402
from prearchive.fixture_sources import build_demo_fixtures           # noqa: E402
from prearchive.heartbeat import Heartbeat                           # noqa: E402
from prearchive.models import (  # noqa: E402
    build_oracle_engine,
    build_oracle_session_factory,
    build_session_factory,
    build_sqlite_engine,
)
from prearchive.config import resolve_result_store_password  # noqa: E402
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

    fernet = None
    try:
        fernet = get_fernet(config)
    except ConfigError:
        # fixtures 演示模式允许无密钥（sqlite 结果库不需要）；oracle 模式首用再 fail-fast
        if not fixtures:
            raise

    # T8-3：工号映射/科室规范化源开关（默认 passthrough/off 完全不改变现状）
    receiver_cfg_pre = dict(config.get("receiver") or {})
    userid_mapper_source = str(receiver_cfg_pre.get("userid_mapper_source")
                               or "passthrough")
    dept_normalizer_source = str(receiver_cfg_pre.get("dept_normalizer_source")
                                 or "off")
    need_his_base = (userid_mapper_source == "hisbase"
                     or dept_normalizer_source == "hisbase")
    his_base_gw = None

    # T8-2 新七源标签 → (config 节名, Sql 网关类)；enabled 才构造（默认全 disabled）
    NEW_SOURCE_WIRING = (
        ("pacs", SqlPacsGateway, SRC_PACS_ITF),
        ("es", SqlEsGateway, SRC_ES_ITF),
        ("bl", SqlBlGateway, SRC_BL_ITF),       # 病理实测列已回填；TDS 7.0 由连接配置负责
        ("xt", SqlXtGateway, SRC_XT_ITF),
        ("xd", SqlXdGateway, SRC_XD_ITF),       # BLOCKED：对接信息待用户提供
        ("dcn", SqlDcnGateway, SRC_DCN_REPORT),
        ("qgj", SqlQgjGateway, SRC_QGJ_ITF),
    )

    extra_itf_collectors = {}
    if fixtures:
        gateways = build_demo_fixtures()
        jhemr_collector = JhemrCollector(gateways["jhemr"])
        for name, _gw_cls, label in NEW_SOURCE_WIRING:
            gw = gateways.get(name)
            if gw is not None:
                extra_itf_collectors[label] = ItfSourceCollector(gw, label)
        if need_his_base:
            from prearchive.his_base import FixtureHisBaseGateway
            his_base_gw = FixtureHisBaseGateway()
        context_builder = PatientContextBuilder(
            jhemr=jhemr_collector,
            his=HisCollector(gateways["his"]),
            sm=SmCollector(gateways["sm"]),
            lis=LisCollector(gateways["lis"]),
            extra_itf_collectors=extra_itf_collectors,
        )
    else:
        sources = config.get("sources") or {}

        def _resolver(source_name):
            return lambda: resolve_source_password(config, fernet, source_name)

        jhemr_collector = JhemrCollector(
            SqlJhemrGateway(sources.get("jhemr") or {}, _resolver("jhemr")))
        if need_his_base:
            from prearchive.his_base import SqlHisBaseGateway
            his_base_gw = SqlHisBaseGateway(sources.get("his_base") or {},
                                            _resolver("his_base"))
        for name, gw_cls, label in NEW_SOURCE_WIRING:
            src_cfg = sources.get(name) or {}
            if src_cfg.get("enabled"):
                extra_itf_collectors[label] = ItfSourceCollector(
                    gw_cls(src_cfg, _resolver(name)), label)
        context_builder = PatientContextBuilder(
            jhemr=jhemr_collector,
            his=HisCollector(SqlHisGateway(sources.get("his") or {}, _resolver("his"))),
            sm=SmCollector(SqlSmGateway(sources.get("sm") or {}, _resolver("sm"))),
            lis=LisCollector(SqlLisGateway(sources.get("lis") or {}, _resolver("lis"))),
            extra_itf_collectors=extra_itf_collectors,
        )

    # T8-3：科室字典在规则引擎与推送文案间复用；加载失败 fail-open 为原代码匹配。
    dept_normalizer = None
    if dept_normalizer_source == "hisbase" and his_base_gw is not None:
        from prearchive.his_base import HisBaseDeptNormalizer

        try:
            dept_normalizer = HisBaseDeptNormalizer(his_base_gw.fetch_dept_dict())
        except Exception as exc:   # noqa: BLE001
            logging.getLogger("prearchive").warning(
                "[hisbase] dept dict load failed, normalizer disabled: %s", exc)

    # T8-4：多文件合并加载——example（质控科签字硬序轨）+ system_push（系统推送豁免轨）
    rules_cfg = config.get("rules") or {}
    rules_paths = [resolve_path(base_dir, rules_cfg.get("rules_file"))]
    for extra in (rules_cfg.get("extra_rules_files") or
                  ["rules/system_push_rules.json"]):
        rules_paths.append(resolve_path(base_dir, extra))
    from prearchive.rules import load_rules_multi
    rules, combined_version = load_rules_multi([str(p) for p in rules_paths])
    engine = RuleEngine(
        rules,
        rule_version=combined_version,
        dept_matcher=dept_normalizer.matches if dept_normalizer is not None else None,
    )

    store_cfg = config.get("result_store") or {}
    store_type = str(store_cfg.get("type") or "sqlite")
    result_engine = None
    if store_type == "sqlite":
        db_path = resolve_path(base_dir, store_cfg.get("sqlite_path") or "data/prearchive_result.db")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        result_engine = build_sqlite_engine(str(db_path))
        session_factory = build_session_factory(result_engine)
    elif store_type == "oracle":
        # T2-3：仅构造 engine（惰性建连，不 DDL）；建表走 sql/ 手工执行；
        # 口令占位/解密失败即 ConfigError（fail-fast，禁止回落 sqlite）
        result_engine = build_oracle_engine(
            dsn=str(store_cfg.get("oracle_dsn") or ""),
            user=str(store_cfg.get("oracle_user") or ""),
            password=resolve_result_store_password(config, fernet),
        )
        session_factory = build_oracle_session_factory(result_engine)
    else:
        raise ConfigError(f"result_store.type must be sqlite/oracle, got {store_type!r}")
    repository = ResultRepository(session_factory)

    push_cfg = dict(config.get("push") or {})
    receiver_cfg = dict(config.get("receiver") or {})
    fallback_order = tuple(receiver_cfg.get("fallback_order")
                           or ("first_finished_doctor", "attending_doctor"))
    from prearchive.receivers import (
        DefaultReceiverResolver,
        HisBaseUserIdMapper,
        passthrough_userid_mapper,
    )
    userid_mapper = passthrough_userid_mapper
    if userid_mapper_source == "hisbase" and his_base_gw is not None:
        userid_mapper = HisBaseUserIdMapper(his_base_gw)
    resolver = DefaultReceiverResolver(userid_mapper=userid_mapper,
                                       fallback_order=fallback_order)
    pusher = WeComPusher(
        push_config=push_cfg,
        secret_provider=lambda: resolve_push_secret(config, get_fernet(config))
        if push_cfg.get("enabled") else "",
        sender=UrllibSender(),
        resolver=resolver,
        dept_normalizer=dept_normalizer,
    )

    anchor_mode = str(service_cfg.get("anchor_mode") or "finished")
    # T8-1：RPA 过渡锚点（用户已拍板）——水位门整体禁用（R5）+ RPA 采集器注入
    paperless_rpa_collector = None
    source_ready_gate_disabled = False
    if anchor_mode == "paperless_rpa":
        from prearchive.paperless import SqlPaperlessGateway
        from prearchive.paperless_rpa import PaperlessRpaCollector

        paperless_cfg = (config.get("sources") or {}).get("paperless") or {}
        if fixtures:
            from prearchive.fixture_sources import build_paperless_rpa_fixtures
            paperless_gw = build_paperless_rpa_fixtures()
        else:
            paperless_gw = SqlPaperlessGateway(
                paperless_cfg, _resolver("paperless"))
        paperless_rpa_collector = PaperlessRpaCollector(paperless_gw)
        source_ready_gate_disabled = True

    processor = PrecheckProcessor(context_builder, engine, repository, pusher,
                                  source_ready_gate_disabled=source_ready_gate_disabled)

    state_backend = str(service_cfg.get("state_backend") or "json")
    if state_backend == "db":
        from prearchive.state_store import DbStateStore

        state_store = DbStateStore(result_engine)
    else:
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
        anchor_mode=service_cfg.get("anchor_mode", "finished"),
        paperless_rpa_collector=paperless_rpa_collector,
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
