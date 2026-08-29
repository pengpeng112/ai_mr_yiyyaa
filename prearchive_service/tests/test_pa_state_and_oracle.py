# -*- coding: utf-8 -*-
"""Oracle 结果库接线 + DbStateStore 单测（031 T2-3 / T2-5）。

- T2-3：DSN 串构造正确（mock create_engine 捕获 URL，断言零真实连接）；
  cx_Oracle 缺失时集成冒烟 skip 不算失败（R15 skipif ImportError 写法）；
  口令占位符 fail-fast（ConfigError，不回落 sqlite）。
- T2-5：独立 metadata（不挂 models.Base，create_all 不建状态表）；
  表缺失首用报错（不自动建表）；两后端契约一致（同 key 读写语义）。
"""
import json
from unittest import mock

import pytest

import prearchive.models as models
from prearchive.config import (
    ConfigError,
    Fernet,
    encrypt_value,
    resolve_result_store_password,
    validate_config,
    DEFAULTS,
)
from prearchive.models import Base, build_sqlite_engine
from prearchive.state_store import (
    STATE_TABLE_NAME,
    DbStateStore,
    StateStoreError,
)
from prearchive.trigger import StateStore as JsonStateStore


# ---------------------------------------------------------------------------
# T2-3 Oracle 结果库
# ---------------------------------------------------------------------------
def test_oracle_result_url_format():
    url = models.oracle_result_url("10.0.0.1:1521/ORCLPDB", "PREARCH", "secret")
    assert url == "oracle+cx_oracle://PREARCH:secret@10.0.0.1:1521/ORCLPDB"


def test_build_oracle_engine_lazy_no_connect(monkeypatch):
    """构造 engine 不触发任何连接（惰性建连）；URL 正确（mock 断言）。"""
    captured = {}

    def fake_create_engine(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        engine = mock.MagicMock()
        engine.url = url
        # 任何 connect 调用都视为违规
        engine.connect.side_effect = AssertionError("must not connect during build")
        return engine

    monkeypatch.setattr(models, "create_engine", fake_create_engine)
    engine = models.build_oracle_engine("db.example:1521/SVC", "USER1", "PASS1")
    assert captured["url"] == "oracle+cx_oracle://USER1:PASS1@db.example:1521/SVC"
    assert captured["kwargs"].get("pool_pre_ping") is True
    engine.connect.assert_not_called()


def test_build_oracle_session_factory_does_no_ddl(monkeypatch):
    engine = mock.MagicMock()
    factory = models.build_oracle_session_factory(engine)
    assert factory.kw.get("expire_on_commit") is False
    engine.connect.assert_not_called()
    engine.execute.assert_not_called()


def test_result_store_password_placeholder_fails_fast():
    cfg = json.loads(json.dumps(DEFAULTS))
    cfg["result_store"]["type"] = "oracle"
    cfg = validate_config(cfg)
    fernet = Fernet(Fernet.generate_key())
    # 占位符 → ConfigError（fail-fast），禁止回落 sqlite
    with pytest.raises(ConfigError):
        resolve_result_store_password(cfg, fernet)


def test_result_store_password_roundtrip():
    key = Fernet.generate_key()
    fernet = Fernet(key)
    cfg = json.loads(json.dumps(DEFAULTS))
    cfg["result_store"]["oracle_password_enc"] = encrypt_value(fernet, "real-pass")
    assert resolve_result_store_password(cfg, fernet) == "real-pass"


def test_real_oracle_engine_smoke_skipif_no_driver():
    """cx_Oracle 未安装时跳过（不算失败，R15）；安装后验证方言可解析。"""
    pytest.importorskip("cx_Oracle")
    engine = models.build_oracle_engine("localhost:1521/XEPDB1", "u", "p")
    assert "cx_oracle" in str(engine.url)


# ---------------------------------------------------------------------------
# T2-5 DbStateStore
# ---------------------------------------------------------------------------
def test_state_table_not_in_base_metadata():
    """独立 metadata：Base.metadata.create_all 不得建出状态表（R14）。"""
    engine = build_sqlite_engine(":memory:")
    Base.metadata.create_all(engine)
    from sqlalchemy import inspect

    assert not inspect(engine).has_table(STATE_TABLE_NAME)


def test_db_state_store_errors_when_table_missing():
    engine = build_sqlite_engine(":memory:")
    store = DbStateStore(engine)
    with pytest.raises(StateStoreError):
        store.load()
    with pytest.raises(StateStoreError):
        store.save({"watermark": "x"})


def _db_store_with_table():
    engine = build_sqlite_engine(":memory:")
    DbStateStore.create_table(engine)   # 测试显式建表（运行路径绝不调用）
    return engine, DbStateStore(engine)


def test_db_state_store_roundtrip():
    engine, store = _db_store_with_table()
    assert store.load() == {"watermark": None, "last_processed": {}, "iterations": 0}
    state = {"watermark": "2026-08-27T11:00:00",
             "last_processed": {"TEST0001|1": "2026-08-26T10:00:00"},
             "iterations": 3}
    store.save(state)
    assert store.load() == state
    # 覆盖保存（非追加）
    state2 = dict(state, iterations=4)
    store.save(state2)
    assert store.load() == state2


def test_state_store_contract_both_backends(tmp_path):
    """契约一致性：同 key 读写语义在 JSON/DB 两实现等价。"""
    sample = {"watermark": "2026-08-28T09:00:00",
              "last_processed": {"P1|1": "2026-08-28T08:00:00",
                                 "P2|2": "2026-08-28T09:00:00"},
              "iterations": 7}
    json_store = JsonStateStore(tmp_path / "state.json")
    _, db_store = _db_store_with_table()

    for store in (json_store, db_store):
        assert store.load() == {"watermark": None, "last_processed": {}, "iterations": 0}
        store.save(dict(sample))
        loaded = store.load()
        assert loaded == sample
        # 增量更新语义等价：改一个键再保存
        loaded["last_processed"]["P3|1"] = "2026-08-28T10:00:00"
        store.save(loaded)
        assert store.load()["last_processed"]["P3|1"] == "2026-08-28T10:00:00"
        assert store.load()["iterations"] == 7
