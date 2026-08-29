# -*- coding: utf-8 -*-
"""无纸化 CDMS 第五源网关（031 T2-7）：规则目录/元数据源，**不是患者文书源**。

边界（R15 红线）：
- 本网关只拉 T_MARK_ITEM 规则库（92 条评分项）与 T_MARK_MAIN/T_MARK_DETAIL
  **聚合元数据**（按日计数/扣分项频次）——禁止接入 PatientContextBuilder.documents；
- meta SQL 禁止出现患者列（FPATIENTID/FBIHID/FBINCU/FNAME 黑名单，测试文本断言）；
- per-visit 金标准回测通道独立：W9 批准后在生产只读侧库内 join 产出脱敏命中集合
  （FID 列表，零患者标识导出）供 backtest.py 消费；
- 真实网关惰性建连，默认 disabled，DSN/凭据全占位（零生产接触）。
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

logger = logging.getLogger("prearchive.paperless")

# 患者标识列黑名单：meta SQL 一律不得出现（PHI 红线）
META_SQL_PATIENT_COLUMN_BLACKLIST = ("FPATIENTID", "FBIHID", "FBINCU", "FNAME")


class PaperlessGateway(ABC):
    """无纸化 CDMS 网关（规则目录 + 聚合金标准元数据）。"""

    @abstractmethod
    def fetch_mark_items(self, since_fid: int = 0, limit: int = 50) -> list:
        """分页拉取启用中的评分项（连接器 50 行封顶实证过）。"""

    @abstractmethod
    def fetch_gold_standard_meta(self, date_from: str, date_to: str) -> list:
        """金标准**聚合元数据**（覆盖面监控用，不是回测数据源，R13）。

        返回行：{"stat_date", "marked_count", "fid", "hit_count"}——按日计数 +
        扣分项频次 GROUP BY；零患者明细。
        """


class SqlPaperlessGateway(PaperlessGateway):
    """真实 CDMS Oracle 网关（惰性建连；oracle 12c+ FETCH FIRST——11g 需 W9 核对后改 ROWNUM）。"""

    MARK_ITEMS_SQL = (
        "SELECT FID, FNAME, FTYPEID, FSCORE, FSCOREDESC, FISENABLE "
        "FROM CDMS.T_MARK_ITEM "
        "WHERE FISENABLE = 1 AND FID > :since_fid "
        "ORDER BY FID "
        "FETCH FIRST :limit ROWS ONLY"
    )

    # 聚合口径：零患者列（黑名单见模块头）；FNAME 此处是 T_MARK_ITEM 的规则名
    # 列名碰撞说明：黑名单针对**患者明细表**的患者姓名列，本 SQL 不 touch 患者表。
    GOLD_META_SQL = (
        "SELECT TRUNC(m.FCREATETIME) AS stat_date, "
        "       COUNT(DISTINCT m.FID) AS marked_count, "
        "       d.FMARKITEMID AS fid, COUNT(d.FID) AS hit_count "
        "FROM CDMS.T_MARK_MAIN m "
        "JOIN CDMS.T_MARK_DETAIL d ON d.FMAINID = m.FID "
        "WHERE m.FCREATETIME >= TO_DATE(:date_from, 'yyyy-mm-dd') "
        "  AND m.FCREATETIME < TO_DATE(:date_to, 'yyyy-mm-dd') + 1 "
        "GROUP BY TRUNC(m.FCREATETIME), d.FMARKITEMID "
        "ORDER BY stat_date, fid"
    )

    def __init__(self, source_config: dict, password_resolver):
        self._config = source_config or {}
        self._password_resolver = password_resolver
        self._engine = None

    def _get_engine(self):
        if self._engine is None:
            from sqlalchemy import create_engine

            cfg = dict(self._config)
            cfg["password"] = self._password_resolver()
            service = cfg.get("service_name") or ""
            url = (f"oracle+cx_oracle://{cfg['user']}:{cfg['password']}"
                   f"@{cfg['host']}:{cfg.get('port', 1521)}/?service_name={service}")
            self._engine = create_engine(url, pool_pre_ping=True)
        return self._engine

    def _query(self, sql: str, params: dict) -> list:
        engine = self._get_engine()
        with engine.connect() as conn:
            from sqlalchemy import text

            result = conn.execute(text(sql), params)
            return [dict(row._mapping) for row in result]

    def fetch_mark_items(self, since_fid: int = 0, limit: int = 50):
        rows = self._query(self.MARK_ITEMS_SQL,
                           {"since_fid": int(since_fid), "limit": int(limit)})
        return [_normalize_mark_item(r) for r in rows]

    def fetch_gold_standard_meta(self, date_from: str, date_to: str):
        return self._query(self.GOLD_META_SQL,
                           {"date_from": date_from, "date_to": date_to})


def _normalize_mark_item(row: dict) -> dict:
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    return {
        "fid": int(lowered.get("fid") or 0),
        "fname": str(lowered.get("fname") or ""),
        "ftypeid": str(lowered.get("ftypeid") or ""),
        "fscore": str(lowered.get("fscore") or ""),
        "fscoredesc": str(lowered.get("fscoredesc") or ""),
        "fisenable": int(lowered.get("fisenable") or 0),
    }


class FixturePaperlessGateway(PaperlessGateway):
    """假源：数据=031 附录 A 固化快照（评分项定义，非 PHI）。"""

    def __init__(self, snapshot_path, meta_rows: Optional[list] = None):
        payload = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
        self.items = list(payload.get("items") or [])
        self.meta_rows = list(meta_rows or [])
        self.mark_items_calls: list = []

    def fetch_mark_items(self, since_fid: int = 0, limit: int = 50):
        self.mark_items_calls.append((since_fid, limit))
        rows = [dict(r) for r in self.items if int(r["fid"]) > int(since_fid)]
        rows.sort(key=lambda r: int(r["fid"]))
        return rows[:int(limit)]

    def fetch_gold_standard_meta(self, date_from: str, date_to: str):
        return [dict(r) for r in self.meta_rows]


def load_snapshot_items(snapshot_path) -> list:
    payload = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    return list(payload.get("items") or [])
