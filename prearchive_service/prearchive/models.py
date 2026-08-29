# -*- coding: utf-8 -*-
"""预检结果独立存储：SQLAlchemy 模型 MED_PREARCHIVE_RESULT。

- 检查键 (patient_id, visit_id, finished_date_time) 三列联合唯一，每检一行（A1 复检语义：
  完成时间更新 = 新检查键 = 新行；旧行保留、current 置 0）；
- problems 以 JSON 文本存储（跨 SQLite/Oracle 兼容，避免方言 JSON 类型差异）；
- 双通道去重字段：push_wecom_status / push_agent_status（同一 result_id 每通道至多一次）；
- 建表：测试/本地用 SQLAlchemy 自动建 SQLite；生产 Oracle 用 sql/ 下 DDL 手工执行，
  服务启动不做任何自动 DDL。

注意：本模块不定义与应用库其他表的任何外键——与六类质控表零耦合（D5 隔离）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()

PUSH_PENDING = "pending"
PUSH_SENT = "sent"
PUSH_FAILED = "failed"
PUSH_SKIPPED = "skipped"


class PrearchiveResult(Base):
    """一次预检查的结果行。"""

    __tablename__ = "MED_PREARCHIVE_RESULT"

    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(String(64), nullable=False)
    visit_id = Column(String(32), nullable=False)
    finished_date_time = Column(DateTime(), nullable=False)   # 检查键之三：完成时间
    current = Column(Integer, nullable=False, default=1)      # 1=该患者最新一次检查

    dept_code = Column(String(64), nullable=False, default="")
    dept_name = Column(String(128), nullable=False, default="")
    patient_name = Column(String(128), nullable=False, default="")   # 虚构/最小化，不含病历原文
    doctor_id = Column(String(64), nullable=False, default="")       # 解析出的提醒对象工号
    doctor_name = Column(String(128), nullable=False, default="")
    receiver_fallback = Column(Integer, nullable=False, default=0)   # 1=走了管床兜底

    problem_count = Column(Integer, nullable=False, default=0)
    severity_top = Column(String(16), nullable=False, default="")    # low/medium/high 最高级
    problems_json = Column(Text, nullable=False, default="[]")
    rule_version = Column(String(64), nullable=False, default="")

    push_wecom_status = Column(String(16), nullable=False, default=PUSH_PENDING)
    push_wecom_at = Column(DateTime(), nullable=True)
    push_wecom_detail = Column(String(512), nullable=False, default="")
    push_agent_status = Column(String(16), nullable=False, default=PUSH_PENDING)
    push_agent_at = Column(DateTime(), nullable=True)
    push_agent_detail = Column(String(512), nullable=False, default="")

    created_at = Column(DateTime(), nullable=False, default=datetime.now)
    updated_at = Column(DateTime(), nullable=False, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        UniqueConstraint("patient_id", "visit_id", "finished_date_time",
                         name="UQ_PREARCHIVE_CHECK_KEY"),
        Index("IX_PREARCHIVE_CURRENT", "patient_id", "visit_id", "current"),
        Index("IX_PREARCHIVE_PUSH_PENDING", "push_wecom_status"),
        {
            "comment": "028 归档前预检结果（独立表，与六类质控零耦合）",
        },
    )

    def problems(self) -> list:
        import json

        try:
            data = json.loads(self.problems_json or "[]")
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def to_public_dict(self) -> dict:
        """只读 API 返回体（最小化字段）。"""
        return {
            "result_id": self.id,
            "patient_id": self.patient_id,
            "visit_id": self.visit_id,
            "finished_date_time": self.finished_date_time.isoformat(timespec="seconds")
            if self.finished_date_time else None,
            "current": bool(self.current),
            "dept_code": self.dept_code,
            "dept_name": self.dept_name,
            "problem_count": self.problem_count,
            "severity_top": self.severity_top,
            "problems": self.problems(),
            "rule_version": self.rule_version,
            "push_wecom_status": self.push_wecom_status,
            "push_agent_status": self.push_agent_status,
        }


def build_sqlite_engine(db_path: str = ":memory:", echo: bool = False):
    """本地/测试用 SQLite 引擎（StaticPool 支持内存库多连接共享）。"""
    if db_path == ":memory:":
        from sqlalchemy.pool import StaticPool

        return create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            echo=echo,
        )
    return create_engine(f"sqlite:///{db_path}", echo=echo)


def build_session_factory(engine) -> sessionmaker:
    Base.metadata.create_all(engine)   # 仅 SQLite 原型/测试自动建表；Oracle 走 sql/ DDL
    return sessionmaker(bind=engine, expire_on_commit=False)


def oracle_result_url(dsn: str, user: str, password: str) -> str:
    """Oracle 结果库连接 URL（cx_Oracle 方言；DSN 形如 host:port/service）。"""
    return f"oracle+cx_oracle://{user}:{password}@{dsn}"


def build_oracle_engine(dsn: str, user: str, password: str, echo: bool = False):
    """Oracle 结果库引擎（T2-3）：构造即返回，惰性建连——不 connect、不建表。

    生产前置：先手工执行 sql/create_prearchive_result_oracle.sql；
    连接失败不回落 SQLite（fail-fast 由首查触发，不静默降级）。
    """
    return create_engine(oracle_result_url(dsn, user, password),
                         pool_pre_ping=True, echo=echo)


def build_oracle_session_factory(engine) -> sessionmaker:
    """Oracle 会话工厂：不做任何自动 DDL（建表走 sql/ 手工执行）。"""
    return sessionmaker(bind=engine, expire_on_commit=False)
