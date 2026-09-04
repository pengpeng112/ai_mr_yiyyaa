# -*- coding: utf-8 -*-
"""规则中心仓储（039 T2）：RuleVersion/Pointer/Audit 的数据访问。

并发纪律：
- draft 编辑走 DRAFT_EDIT_VERSION 乐观锁（不匹配→RuleConflictError）；
- 发布指针更新走 POINTER_VERSION 乐观锁；
- 双发布只能一胜：publish 事务内先锁行（SELECT ... FOR UPDATE 方言差异用
  乐观重试替代——SQLite 无 FOR UPDATE，统一按"读-比-写"乐观并发）。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select

from .rule_models import (
    AUDIT_ACTIONS,
    RULE_STATUS_DRAFT,
    RULE_STATUSES,
    DeliveryLogRow,
    DestinationRow,
    OutboxRow,
    RuleAuditRow,
    RulePointerRow,
    RuleVersionRow,
    canonical_json,
    content_sha256,
    new_id,
)


class RuleConflictError(Exception):
    """乐观锁冲突 / 非法状态迁移。"""


class RuleNotFoundError(Exception):
    """规则或版本不存在。"""


def _as_aware(value):
    """SQLite 往返会丢 tzinfo：统一按 +08:00 补回，避免 naive/aware 比较崩。"""
    if value is None or value.tzinfo is not None:
        return value
    from datetime import timedelta, timezone
    return value.replace(tzinfo=timezone(timedelta(hours=8)))


class RuleRepository:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    # ---- 版本 ----

    def get_version(self, rule_key: str, rule_version: str) -> Optional[RuleVersionRow]:
        with self.session_factory() as session:
            row = session.execute(
                select(RuleVersionRow).where(
                    RuleVersionRow.rule_key == rule_key,
                    RuleVersionRow.rule_version == rule_version,
                )
            ).scalar_one_or_none()
            return row

    def get_version_by_id(self, version_id: str) -> Optional[RuleVersionRow]:
        with self.session_factory() as session:
            return session.get(RuleVersionRow, version_id)

    def latest_version(self, rule_key: str) -> Optional[RuleVersionRow]:
        """该规则最新的一行（按创建时间倒序第一）。"""
        with self.session_factory() as session:
            return session.execute(
                select(RuleVersionRow).where(RuleVersionRow.rule_key == rule_key)
                .order_by(RuleVersionRow.created_at.desc(), RuleVersionRow.id.desc())
            ).scalars().first()

    def list_versions(self, rule_key: str) -> List[RuleVersionRow]:
        with self.session_factory() as session:
            return list(session.execute(
                select(RuleVersionRow).where(RuleVersionRow.rule_key == rule_key)
                .order_by(RuleVersionRow.created_at.desc(), RuleVersionRow.id.desc())
            ).scalars().all())

    def list_rules(self, domain: str = "", track: str = "", status: str = "",
                   page: int = 1, page_size: int = 50) -> tuple:
        """规则列表（每 rule_key 取最新一行聚合）。返回 (rows, total)。"""
        with self.session_factory() as session:
            stmt = select(RuleVersionRow)
            if domain:
                stmt = stmt.where(RuleVersionRow.domain == domain)
            if track:
                stmt = stmt.where(RuleVersionRow.track == track)
            if status:
                stmt = stmt.where(RuleVersionRow.status == status)
            rows = session.execute(
                stmt.order_by(RuleVersionRow.created_at.desc(), RuleVersionRow.id.desc())
            ).scalars().all()
        latest_by_key: dict = {}
        for row in rows:                       # 已按新→旧排序，首个即最新
            latest_by_key.setdefault(row.rule_key, row)
        items = list(latest_by_key.values())
        total = len(items)
        start = max(0, (page - 1) * page_size)
        return items[start:start + page_size], total

    def insert_version(self, **fields) -> RuleVersionRow:
        with self.session_factory() as session:
            row = RuleVersionRow(id=new_id(), **fields)
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def update_draft_content(self, rule_key: str, rule_version: str,
                             content: dict, expect_edit_version: int,
                             name: str = "") -> RuleVersionRow:
        """仅 draft 态可编辑；乐观锁不匹配抛 RuleConflictError。"""
        with self.session_factory() as session:
            row = session.execute(
                select(RuleVersionRow).where(
                    RuleVersionRow.rule_key == rule_key,
                    RuleVersionRow.rule_version == rule_version,
                )
            ).scalar_one_or_none()
            if row is None:
                raise RuleNotFoundError(f"{rule_key}@{rule_version}")
            if row.status != RULE_STATUS_DRAFT:
                raise RuleConflictError(
                    f"rule {rule_key}@{rule_version} is {row.status}, only draft is editable")
            if int(row.draft_edit_version or 1) != int(expect_edit_version):
                raise RuleConflictError(
                    f"draft edit version conflict: expected {row.draft_edit_version}, "
                    f"got {expect_edit_version}")
            row.content_json = canonical_json(content)
            row.content_sha256 = content_sha256(content)
            row.draft_edit_version = int(row.draft_edit_version or 1) + 1
            if name:
                row.updated_at = datetime.now()
            session.commit()
            session.refresh(row)
            return row

    def transition(self, rule_key: str, rule_version: str, to_status: str,
                   **extra_fields) -> RuleVersionRow:
        if to_status not in RULE_STATUSES:
            raise RuleConflictError(f"unknown status: {to_status}")
        with self.session_factory() as session:
            row = session.execute(
                select(RuleVersionRow).where(
                    RuleVersionRow.rule_key == rule_key,
                    RuleVersionRow.rule_version == rule_version,
                )
            ).scalar_one_or_none()
            if row is None:
                raise RuleNotFoundError(f"{rule_key}@{rule_version}")
            row.status = to_status
            for key, value in extra_fields.items():
                setattr(row, key, value)
            session.commit()
            session.refresh(row)
            return row

    # ---- 指针 ----

    def get_pointer(self, domain: str, track: str, rule_key: str) -> Optional[RulePointerRow]:
        with self.session_factory() as session:
            return session.execute(
                select(RulePointerRow).where(
                    RulePointerRow.domain == domain,
                    RulePointerRow.track == track,
                    RulePointerRow.rule_key == rule_key,
                )
            ).scalar_one_or_none()

    def list_pointers(self, domain: str = "", track: str = "") -> List[RulePointerRow]:
        with self.session_factory() as session:
            stmt = select(RulePointerRow)
            if domain:
                stmt = stmt.where(RulePointerRow.domain == domain)
            if track:
                stmt = stmt.where(RulePointerRow.track == track)
            return list(session.execute(stmt).scalars().all())

    def set_pointer(self, domain: str, track: str, rule_key: str,
                    published_version: str, updated_by: str = "",
                    expect_pointer_version: Optional[int] = None) -> RulePointerRow:
        """发布/回滚指针写入；expect_pointer_version 提供时做乐观校验。"""
        with self.session_factory() as session:
            row = session.execute(
                select(RulePointerRow).where(
                    RulePointerRow.domain == domain,
                    RulePointerRow.track == track,
                    RulePointerRow.rule_key == rule_key,
                )
            ).scalar_one_or_none()
            if row is None:
                row = RulePointerRow(
                    id=new_id(), domain=domain, track=track, rule_key=rule_key,
                    published_version=published_version, pointer_version=1,
                    updated_by=updated_by,
                )
                session.add(row)
            else:
                if expect_pointer_version is not None \
                        and int(row.pointer_version or 1) != int(expect_pointer_version):
                    raise RuleConflictError(
                        f"pointer version conflict: expected {row.pointer_version}, "
                        f"got {expect_pointer_version}")
                row.published_version = published_version
                row.pointer_version = int(row.pointer_version or 1) + 1
                row.updated_by = updated_by
            session.commit()
            session.refresh(row)
            return row

    def published_rules(self, domain: str = "", track: str = "") -> List[RuleVersionRow]:
        """registry 模式运行时入口：指针指向的 published 版本（内容只读）。"""
        pointers = self.list_pointers(domain=domain, track=track)
        out: List[RuleVersionRow] = []
        with self.session_factory() as session:
            for pointer in pointers:
                row = session.execute(
                    select(RuleVersionRow).where(
                        RuleVersionRow.rule_key == pointer.rule_key,
                        RuleVersionRow.rule_version == pointer.published_version,
                        RuleVersionRow.status == "published",
                    )
                ).scalar_one_or_none()
                if row is not None:
                    out.append(row)
        return out

    # ---- 审计 ----

    def append_audit(self, *, action: str, rule_key: str = "", version_from: str = "",
                     version_to: str = "", actor_id: str = "", actor_name: str = "",
                     reason: str = "", request_id: str = "", detail: Optional[dict] = None) -> None:
        if action not in AUDIT_ACTIONS:
            raise RuleConflictError(f"unknown audit action: {action}")
        with self.session_factory() as session:
            session.add(RuleAuditRow(
                id=new_id(),
                action=action,
                rule_key=rule_key,
                version_from=version_from,
                version_to=version_to,
                actor_id=actor_id,
                actor_name=actor_name,
                reason=str(reason or "")[:500],
                request_id=str(request_id or "")[:60],
                detail_json=canonical_json(detail or {}),
            ))
            session.commit()

    def list_audit(self, rule_key: str = "", action: str = "", limit: int = 100,
                   offset: int = 0) -> List[RuleAuditRow]:
        with self.session_factory() as session:
            stmt = select(RuleAuditRow)
            if rule_key:
                stmt = stmt.where(RuleAuditRow.rule_key == rule_key)
            if action:
                stmt = stmt.where(RuleAuditRow.action == action)
            stmt = stmt.order_by(RuleAuditRow.created_at.desc()).offset(offset).limit(limit)
            return list(session.execute(stmt).scalars().all())

    # ---- Destination ----

    def list_destinations(self) -> List[DestinationRow]:
        with self.session_factory() as session:
            return list(session.execute(select(DestinationRow)).scalars().all())

    def get_destination(self, code: str) -> Optional[DestinationRow]:
        with self.session_factory() as session:
            return session.get(DestinationRow, code)

    def upsert_destination(self, **fields) -> DestinationRow:
        code = fields.get("code")
        with self.session_factory() as session:
            row = session.get(DestinationRow, code)
            if row is None:
                row = DestinationRow(**fields)
                session.add(row)
            else:
                for key, value in fields.items():
                    if key != "code":
                        setattr(row, key, value)
                row.config_version = int(row.config_version or 1) + 1
            session.commit()
            session.refresh(row)
            return row

    # ---- Outbox ----

    def enqueue_outbox(self, *, event_id: str, destination_code: str,
                       payload_json: str, idempotency_key: str = "") -> OutboxRow:
        """幂等入队：同 (event, destination) 已存在直接返回既有行。"""
        with self.session_factory() as session:
            row = session.execute(
                select(OutboxRow).where(
                    OutboxRow.event_id == event_id,
                    OutboxRow.destination_code == destination_code,
                )
            ).scalar_one_or_none()
            if row is None:
                row = OutboxRow(
                    id=new_id(),
                    event_id=event_id,
                    destination_code=destination_code,
                    idempotency_key=idempotency_key,
                    payload_json=payload_json,
                )
                session.add(row)
                session.commit()
                session.refresh(row)
            return row

    def claim_pending(self, *, owner: str, now: datetime, limit: int = 20,
                      lease_seconds: int = 120) -> List[OutboxRow]:
        """原子认领：pending/retry 且到达重试时间的行 → sending+lease。

        SQLite 无 FOR UPDATE，用"单事务内逐行条件 UPDATE"保证并发下只有一方
        认领成功（UPDATE ... WHERE status=旧值 返回 rowcount）。
        """
        from sqlalchemy import update
        claimed: List[OutboxRow] = []
        with self.session_factory() as session:
            rows = session.execute(
                select(OutboxRow).where(
                    OutboxRow.status.in_(["pending", "retry"]),
                ).order_by(OutboxRow.created_at).limit(limit * 2)
            ).scalars().all()
            for row in rows:
                next_retry = _as_aware(row.next_retry_at)
                lease_until = _as_aware(row.lease_until)
                if row.status == "retry" and next_retry and next_retry > now:
                    continue
                # 崩溃回收：sending 但 lease 已过期
                if row.status == "sending" and lease_until and lease_until > now:
                    continue
                result = session.execute(
                    update(OutboxRow)
                    .where(OutboxRow.id == row.id,
                           OutboxRow.status == row.status)
                    .values(status="sending", lease_owner=owner,
                            lease_until=datetime.fromtimestamp(
                                now.timestamp() + lease_seconds),
                            updated_at=datetime.now())
                )
                if result.rowcount == 1:
                    claimed.append(row)
                if len(claimed) >= limit:
                    break
            session.commit()
        # 重新读出最新状态（claim 后）
        with self.session_factory() as session:
            by_id = {r.id: r for r in session.execute(
                select(OutboxRow).where(OutboxRow.id.in_([c.id for c in claimed]))
            ).scalars().all()}
            return [by_id[c.id] for c in claimed if c.id in by_id]

    def finish_outbox(self, outbox_id: str, *, status: str,
                      http_status: Optional[int] = None, error: str = "",
                      next_retry_at: Optional[datetime] = None,
                      attempts: Optional[int] = None) -> bool:
        """终态/重试状态回写；sent 永不自动回退。"""
        with self.session_factory() as session:
            row = session.get(OutboxRow, outbox_id)
            if row is None:
                return False
            if row.status == "sent" and status != "sent":
                return False
            row.status = status
            row.last_http_status = http_status
            row.last_error = str(error or "")[:500]
            row.next_retry_at = next_retry_at
            row.lease_until = None
            row.lease_owner = ""
            if attempts is not None:
                row.attempts = attempts
            session.commit()
            return True

    def list_outbox(self, status: str = "", destination_code: str = "",
                    limit: int = 100, offset: int = 0) -> List[OutboxRow]:
        with self.session_factory() as session:
            stmt = select(OutboxRow)
            if status:
                stmt = stmt.where(OutboxRow.status == status)
            if destination_code:
                stmt = stmt.where(OutboxRow.destination_code == destination_code)
            stmt = stmt.order_by(OutboxRow.created_at.desc()).offset(offset).limit(limit)
            return list(session.execute(stmt).scalars().all())

    def get_outbox(self, outbox_id: str) -> Optional[OutboxRow]:
        with self.session_factory() as session:
            return session.get(OutboxRow, outbox_id)

    def append_delivery_log(self, *, outbox_id: str, event_id: str,
                            destination_code: str, attempt: int,
                            http_status: Optional[int], outcome: str,
                            ack_event_id: str = "", receiver_reference: str = "",
                            detail: str = "") -> None:
        with self.session_factory() as session:
            session.add(DeliveryLogRow(
                id=new_id(),
                outbox_id=outbox_id,
                event_id=event_id,
                destination_code=destination_code,
                attempt=attempt,
                http_status=http_status,
                outcome=outcome,
                ack_event_id=str(ack_event_id or "")[:60],
                receiver_reference=str(receiver_reference or "")[:250],
                detail=str(detail or "")[:500],
            ))
            session.commit()

    def list_delivery_logs(self, event_id: str = "", limit: int = 100) -> List[DeliveryLogRow]:
        with self.session_factory() as session:
            stmt = select(DeliveryLogRow)
            if event_id:
                stmt = stmt.where(DeliveryLogRow.event_id == event_id)
            stmt = stmt.order_by(DeliveryLogRow.created_at.desc()).limit(limit)
            return list(session.execute(stmt).scalars().all())
