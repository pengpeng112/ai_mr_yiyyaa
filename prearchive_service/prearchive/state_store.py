# -*- coding: utf-8 -*-
"""状态存储后端：JSON 文件（默认）与 MED_PREARCHIVE_STATE 表（可选）。

T2-5（031）：
- JSON 后端 = trigger.StateStore（现状不变，默认）；
- Db 后端 = DbStateStore：水位/last_processed/iterations 落库；
  * **独立 metadata**——不挂 models.Base（防 SQLite 测试 create_all 自动建表，R14）；
  * 首用显式检查表存在，缺失即抛 StateStoreError（**不自动建表**；
    DDL 在 sql/create_prearchive_state_oracle.sql，手工执行）；
- 两实现契约一致：load/save 语义与默认状态结构同 JSON 版。

接口（与 trigger.StateStore 互换）：
    load() -> dict          # {"watermark", "last_processed", "iterations"}
    save(state: dict)       # 整体覆盖保存
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    insert,
    select,
    update,
)

logger = logging.getLogger("prearchive.state_store")

DEFAULT_STATE = {"watermark": None, "last_processed": {}, "iterations": 0}

STATE_TABLE_NAME = "MED_PREARCHIVE_STATE"

# 独立 metadata：绝不挂 models.Base.metadata（R14）
_STATE_METADATA = MetaData()

STATE_TABLE = Table(
    STATE_TABLE_NAME,
    _STATE_METADATA,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("state_key", String(64), nullable=False, unique=True, index=True),
    Column("state_json", Text, nullable=False),
    Column("updated_at", DateTime, nullable=False, default=datetime.now),
    comment="028/031 预检轮询状态（水位/检查键去重/迭代数；独立表不自动建）",
)

DEFAULT_STATE_KEY = "default"


class StateStoreError(Exception):
    """状态库后端错误（表缺失/读写失败）。"""


class DbStateStore:
    """MED_PREARCHIVE_STATE 单行 JSON 文档式状态存储（state_key='default'）。"""

    def __init__(self, engine, state_key: str = DEFAULT_STATE_KEY):
        self.engine = engine
        self.state_key = state_key
        self._lock = threading.Lock()

    def _table_exists(self) -> bool:
        from sqlalchemy import inspect

        return inspect(self.engine).has_table(STATE_TABLE_NAME)

    def _ensure_table(self) -> None:
        if not self._table_exists():
            raise StateStoreError(
                f"state table {STATE_TABLE_NAME} not found: run "
                "sql/create_prearchive_state_oracle.sql manually first "
                "(no auto-DDL by design)")

    def load(self) -> dict:
        try:
            self._ensure_table()
            with self.engine.connect() as conn:
                row = conn.execute(
                    select(STATE_TABLE.c.state_json).where(
                        STATE_TABLE.c.state_key == self.state_key)
                ).scalar_one_or_none()
            if row is None:
                return dict(DEFAULT_STATE)
            data = json.loads(str(row))
            return data if isinstance(data, dict) else dict(DEFAULT_STATE)
        except StateStoreError:
            raise
        except Exception:
            logger.exception("[state-db] load failed; return default state")
            return dict(DEFAULT_STATE)

    def save(self, state: dict) -> None:
        payload = json.dumps(state or {}, ensure_ascii=False)
        with self._lock:
            try:
                self._ensure_table()
                with self.engine.begin() as conn:
                    exists = conn.execute(
                        select(STATE_TABLE.c.id).where(
                            STATE_TABLE.c.state_key == self.state_key)
                    ).scalar_one_or_none()
                    if exists is None:
                        conn.execute(insert(STATE_TABLE).values(
                            state_key=self.state_key,
                            state_json=payload,
                            updated_at=datetime.now(),
                        ))
                    else:
                        conn.execute(
                            update(STATE_TABLE)
                            .where(STATE_TABLE.c.state_key == self.state_key)
                            .values(state_json=payload, updated_at=datetime.now())
                        )
            except StateStoreError:
                raise
            except Exception:
                logger.exception("[state-db] save failed (keep last good state)")

    @staticmethod
    def create_table(engine) -> None:
        """仅测试/运维显式建表用；服务运行路径绝不调用（不自动建表红线）。"""
        STATE_TABLE.create(engine, checkfirst=True)
