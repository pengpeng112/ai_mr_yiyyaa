# -*- coding: utf-8 -*-
"""046 T1a AI 自动匹配服务：评分项 → 候选规则（不自动发布、不自动配置临床阈值）。

流程（046 §4.1.1）：
- 先精确匹配：FID 已有 confirmed 覆盖（含已发布 rule_ids）→ 直接复用，不经模型；
- 其余 FID 走模型通道（本地可控 stub / 院内 OpenAI 兼容通道，独立配置）；
- 模型输出受 JSON Schema 约束 + 确定性校验器（FID 存在、字段可解析、规则存在、
  DSL 合法、禁任意代码/SQL）；编造字段/非法 DSL 进 blocked，高 confidence 不能绕过；
- 任务分批、可取消、断点恢复（processed_fids 游标）、超时重试一次、相同输入复用；
- 用户对候选接受/驳回留痕；接受 ≠ 发布（发布走规则中心既有状态机，T4/T5）。

输入只含：评分项原文、阈值出处、已发布规则摘要、字段注册表——
不含患者病历/姓名等 PHI（serialize 前有哨兵自检）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime
from typing import Callable, Optional, Protocol

from sqlalchemy import delete, select, update

from .closed_loop_models import (
    MATCH_CANCELLED,
    MATCH_COMPLETED,
    MATCH_FAILED,
    MATCH_PARTIAL,
    MATCH_PENDING,
    MATCH_RUNNING,
    CatalogItemRow,
    CoverageMapRow,
    MatchCandidateRow,
    MatchTaskRow,
)
from .coverage import build_coverage_records, load_snapshot_items
from .field_registry import known_field_names, publishable_fields
from .rule_models import new_id
from .rule_service import validate_rule_content

logger = logging.getLogger("prearchive.match")

PROMPT_VERSION = "match-v1-20260910"

# 模型单 FID 调用超时/重试（测试可注入）
DEFAULT_MODEL_TIMEOUT_SECONDS = 60
DEFAULT_MAX_ATTEMPTS_PER_FID = 2


class ModelTimeout(Exception):
    pass


class MatchModelClient(Protocol):
    """模型通道抽象：complete(prompt) -> JSON 文本。"""

    name: str

    def complete(self, prompt: str) -> str: ...


class StubMatchModel:
    """本地可控 stub：从覆盖账本确定性生成候选（演示/测试专用，不联网）。

    overrides: {fid: "timeout" | "badjson" | "fabricate" | "bad_dsl"} 注入故障形态。
    """

    name = "stub-match-v1"

    def __init__(self, overrides: Optional[dict] = None):
        self.overrides = dict(overrides or {})

    def complete(self, prompt: str) -> str:
        payload = json.loads(prompt)          # stub 约定：prompt 即结构化输入 JSON
        fid = int(payload["fid"])
        mode = self.overrides.get(fid)
        if mode == "timeout":
            raise ModelTimeout(f"stub timeout for FID {fid}")
        if mode == "badjson":
            return "{not-valid-json"
        clauses = payload["clauses"]
        out_clauses = []
        for clause in clauses:
            entry = {
                "clause_id": clause["clause_id"],
                "matched_rule_ids": clause.get("rule_ids") or [],
                "suggested_dsl": {},
                "field_refs": clause.get("fields") or [],
                "covered_clauses": clause.get("covered_clauses") or "",
                "uncovered_clauses": clause.get("uncovered_clauses") or "",
                "rationale": f"stub: {clause['clause_text']}",
                "confidence": "high" if clause["method_hint"] == "deterministic"
                              else "low",
                "blocking_reasons":
                    [clause["blocked_reason"]] if clause.get("blocked_reason") else [],
            }
            if mode == "fabricate":
                entry["field_refs"] = ["totally_made_up_field"]
            if mode == "bad_dsl" and clause["method_hint"] == "deterministic":
                entry["suggested_dsl"] = {
                    "rule_id": f"R-STUB-{fid}", "type": "sql_injection",
                    "name": "x", "message": "m", "version": "1",
                    "sql": "SELECT * FROM patients",
                }
            else:
                hints = clause.get("hints") or {}
                if hints.get("kind") == "time_limit":
                    entry["suggested_dsl"] = self._time_limit_dsl(fid, clause, hints)
                elif hints.get("kind") == "missing_doc":
                    entry["suggested_dsl"] = self._missing_doc_dsl(fid, clause, hints)
            out_clauses.append(entry)
        return json.dumps({"fid": fid, "clauses": out_clauses}, ensure_ascii=False)

    @staticmethod
    def _time_limit_dsl(fid: int, clause: dict, hints: dict) -> dict:
        return {
            "rule_id": f"R-STUB-TIME-{fid}", "type": "time_limit",
            "name": clause["clause_text"][:40], "message": clause["clause_text"][:60],
            "severity": "medium", "version": "stub-1",
            "mark_item_fid": fid, "doc_name": hints.get("doc_name") or "入院记录",
            "event": hints.get("event") or "admission",
            "threshold_hours": hints.get("threshold_hours") or 24,
            "doc_time_source": hints.get("doc_time_source") or "blws",
            "match": {"sources": clause.get("sources") or ["jhemr_blws"]},
        }

    @staticmethod
    def _missing_doc_dsl(fid: int, clause: dict, hints: dict) -> dict:
        return {
            "rule_id": f"R-STUB-MISS-{fid}", "type": "missing_doc",
            "name": clause["clause_text"][:40], "message": clause["clause_text"][:60],
            "severity": "medium", "version": "stub-1",
            "mark_item_fid": fid,
            "trigger": {"patient_has": "surgery",
                        "evidence": {"surgery_evidence": "sm_itf_entry"}},
            "expect": hints.get("family") or ["术前访视"],
            "match": {"sources": clause.get("sources") or ["sm_itf"]},
        }


class HttpMatchModel:
    """院内 OpenAI 兼容通道（独立配置与预算；未配置时不可用，不冒称已真实匹配）。"""

    name = "openai-compat"

    def __init__(self, base_url: str, api_key: str, model: str,
                 timeout_seconds: int = DEFAULT_MODEL_TIMEOUT_SECONDS,
                 transport=None):
        if not base_url or not api_key or not model:
            raise ValueError("http match model requires base_url/api_key/model")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = int(timeout_seconds)
        self._transport = transport

    def complete(self, prompt: str) -> str:
        if self._transport is not None:
            return self._transport(prompt)
        import httpx

        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model,
                  "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0,
                  "response_format": {"type": "json_object"}},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# 输入构造与确定性校验
# ---------------------------------------------------------------------------

_PHI_SENTINELS = ("patient_name", "病历原文", "mr_text:", "身份证")


def build_match_input(record: dict, published_rules: list[dict]) -> str:
    """单 FID 模型输入（结构化 JSON 文本；stub 直接解析，真实通道作为 prompt）。"""
    published_summary = [
        {"rule_id": r.get("rule_id"), "fid": r.get("mark_item_fid"),
         "type": r.get("type"), "version": r.get("version")}
        for r in published_rules or []
    ]
    payload = {
        "fid": record["fid"],
        "original_text": record["original_text"],
        "interpretation": record["interpretation"],
        "score": record["score"],
        "clauses": [
            {"clause_id": c["clause_id"], "clause_text": c["clause_text"],
             "method_hint": c["method"], "coverage": c["coverage"],
             "rule_ids": c["rule_ids"], "fields": c["fields"],
             "threshold_source": c["threshold_source"],
             "blocked_reason": c["blocked_reason"], "hints": c.get("hints") or {}}
            for c in record["clauses"]
        ],
        "published_rules": published_summary,
        "field_registry": sorted(known_field_names()),
    }
    text = json.dumps(payload, ensure_ascii=False)
    for token in _PHI_SENTINELS:
        if token in text:
            raise ValueError(f"match input contains PHI sentinel: {token}")
    return text


def input_hash_for(records: list[dict], published_rules: list[dict]) -> str:
    digest = hashlib.sha256()
    for record in sorted(records or [], key=lambda r: r["fid"]):
        digest.update(build_match_input(record, published_rules).encode("utf-8"))
    return digest.hexdigest()[:32]


def validate_model_output(parsed: dict, known_fids: set,
                          published_rule_ids: set) -> tuple:
    """确定性校验器：返回 (candidates, errors)。

    校验不通过不丢弃整份输出——逐条款降级为 blocked（保留模型理由供人工看）。
    """
    errors: list[str] = []
    fid = parsed.get("fid")
    if fid is None or int(fid) not in known_fids:
        return [], [f"unknown fid: {fid!r}"]
    fid = int(fid)

    known_fields = known_field_names()
    publishable = set(publishable_fields())
    candidates = []
    for clause in parsed.get("clauses") or []:
        problems: list[str] = []
        field_refs = [str(f) for f in (clause.get("field_refs") or [])]
        for field in field_refs:
            if field not in known_fields:
                problems.append(f"field not in registry: {field}")
        matched_ids = [str(r) for r in (clause.get("matched_rule_ids") or [])]
        for rule_id in matched_ids:
            if rule_id not in published_rule_ids:
                problems.append(f"matched rule not published: {rule_id}")
        suggested = clause.get("suggested_dsl") or {}
        if suggested:
            dsl = dict(suggested)
            dsl.setdefault("rule_id", f"R-MATCH-{fid}")
            dsl.setdefault("name", clause.get("clause_id") or f"FID{fid}")
            dsl.setdefault("message", clause.get("rationale") or "")
            dsl.setdefault("version", f"match-{PROMPT_VERSION}")
            dsl.setdefault("mark_item_fid", fid)
            content_errors = validate_rule_content(dsl)
            if content_errors:
                problems.extend(content_errors)
            if dsl.get("type") == "time_limit":
                # 时限候选必须引用可发布时间字段（臆造阈值进 blocked）
                if dsl.get("doc_time_source") not in (None, "", "blws",
                                                      "file_index_topic"):
                    problems.append(f"unknown doc_time_source: "
                                    f"{dsl.get('doc_time_source')!r}")
            if any(f not in publishable for f in field_refs):
                problems.append("field_refs include non-publishable field(s): "
                                + ",".join(f for f in field_refs if f not in publishable))
        blocking = [str(b) for b in (clause.get("blocking_reasons") or [])]
        if problems:
            blocking = blocking + problems     # 模型自报缺口 + 校验问题合并
        candidates.append({
            "fid": fid,
            "clause_id": str(clause.get("clause_id") or f"FID{fid}-C1"),
            "matched_rule_ids": matched_ids,
            "suggested_dsl": suggested if not problems else {},
            "field_refs": field_refs,
            "covered_clauses": str(clause.get("covered_clauses") or ""),
            "uncovered_clauses": str(clause.get("uncovered_clauses") or ""),
            "rationale": str(clause.get("rationale") or ""),
            "confidence": str(clause.get("confidence") or ""),
            "blocking_reasons": blocking,
            "validation_ok": not problems,
            "validation_errors": problems,
        })
    return candidates, errors


# ---------------------------------------------------------------------------
# 匹配服务（任务生命周期）
# ---------------------------------------------------------------------------

class MatchService:
    def __init__(self, session_factory, snapshot_path=None):
        self.session_factory = session_factory
        self._snapshot_path = snapshot_path

    # ---- 数据供给 ----

    def coverage_records(self) -> list[dict]:
        return build_coverage_records(load_snapshot_items(self._snapshot_path))

    def known_fids(self) -> set:
        return {r["fid"] for r in self.coverage_records()}

    def published_rule_ids(self) -> set:
        """已知规则全集：注册表 published ∪ 账本条款关联 rule_ids（文件轨规则未导入
        注册表时不得被误判为编造，046 T3）。"""
        from .rule_repository import RuleRepository
        repo = RuleRepository(self.session_factory)
        known = {row.rule_key for row in repo.published_rules()}
        for record in self.coverage_records():
            for clause in record["clauses"]:
                known.update(clause.get("rule_ids") or [])
        return known

    def published_rules_summary(self) -> list[dict]:
        from .rule_repository import RuleRepository
        repo = RuleRepository(self.session_factory)
        summary = []
        for row in repo.published_rules():
            content = json.loads(row.content_json)
            summary.append({"rule_id": row.rule_key, "mark_item_fid":
                            content.get("mark_item_fid"),
                            "type": content.get("type"), "version": row.rule_version})
        return summary

    def _exact_match_record(self, record: dict) -> Optional[list[dict]]:
        """已确认覆盖（coverage 行 status=confirmed 且有 rule_ids）→ 精确命中复用。"""
        with self.session_factory() as session:
            rows = session.execute(
                select(CoverageMapRow).where(CoverageMapRow.fid == record["fid"],
                                             CoverageMapRow.status == "confirmed")
            ).scalars().all()
        if not rows:
            return None
        out = []
        for row in rows:
            out.append({
                "fid": record["fid"],
                "clause_id": row.clause_id,
                "matched_rule_ids": json.loads(row.rule_ids_json or "[]"),
                "suggested_dsl": {},
                "field_refs": json.loads(row.fields_json or "[]"),
                "covered_clauses": row.covered_clauses,
                "uncovered_clauses": row.uncovered_clauses,
                "rationale": "exact match: confirmed coverage row (no model call)",
                "confidence": "exact",
                "blocking_reasons": [],
                "validation_ok": True,
                "validation_errors": [],
                "exact_match": True,
            })
        return out

    # ---- 任务生命周期 ----

    def create_task(self, *, fids: Optional[list], actor_id: str,
                    model_name: str = "stub", model_config: Optional[dict] = None,
                    model_client: Optional[MatchModelClient] = None,
                    reuse: bool = True) -> MatchTaskRow:
        records = self.coverage_records()
        if fids:
            unknown = sorted(set(int(f) for f in fids) - {r["fid"] for r in records})
            if unknown:
                raise ValueError(f"unknown fids: {unknown}")
            records = [r for r in records if r["fid"] in set(int(f) for f in fids)]
        published = self.published_rules_summary()
        digest = input_hash_for(records, published)

        if reuse:
            with self.session_factory() as session:
                row = session.execute(
                    select(MatchTaskRow).where(
                        MatchTaskRow.input_hash == digest,
                        MatchTaskRow.status.in_([MATCH_PENDING, MATCH_RUNNING,
                                                 MATCH_COMPLETED, MATCH_PARTIAL]))
                    .order_by(MatchTaskRow.created_at.desc())
                ).scalars().first()
                if row is not None:
                    return row        # 相同输入复用（进行中复用任务，完成复用结果）

        with self.session_factory() as session:
            row = MatchTaskRow(
                id=new_id(), status=MATCH_PENDING,
                fid_filter_json=json.dumps(sorted(int(r["fid"]) for r in records)),
                input_hash=digest,
                model_config_json=json.dumps(model_config or {}, ensure_ascii=False),
                model_name=model_name, prompt_version=PROMPT_VERSION,
                progress_total=len(records),
                created_by=actor_id,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def get_task(self, task_id: str) -> Optional[MatchTaskRow]:
        with self.session_factory() as session:
            return session.get(MatchTaskRow, task_id)

    def list_candidates(self, task_id: str, fid: Optional[int] = None) -> list:
        with self.session_factory() as session:
            stmt = select(MatchCandidateRow).where(MatchCandidateRow.task_id == task_id)
            if fid is not None:
                stmt = stmt.where(MatchCandidateRow.fid == int(fid))
            return list(session.execute(
                stmt.order_by(MatchCandidateRow.fid, MatchCandidateRow.clause_id)
            ).scalars().all())

    def cancel_task(self, task_id: str, actor_id: str) -> Optional[MatchTaskRow]:
        with self.session_factory() as session:
            row = session.get(MatchTaskRow, task_id)
            if row is None:
                return None
            if row.status in (MATCH_RUNNING, MATCH_PENDING):
                row.status = MATCH_CANCELLED
                row.updated_at = datetime.now()
                session.commit()
            session.refresh(row)
            return row

    def run_task(self, task_id: str,
                 model_client: Optional[MatchModelClient] = None,
                 per_call_timeout: float = DEFAULT_MODEL_TIMEOUT_SECONDS,
                 max_attempts: int = DEFAULT_MAX_ATTEMPTS_PER_FID,
                 clock: Callable[[], datetime] = datetime.now) -> MatchTaskRow:
        """同步执行任务（API/worker 共用入口）；断点恢复 + 取消 + 部分成功。

        048 T4 事务边界：
        - 启动=条件 UPDATE（仅 pending/partial/failed 可进入 running）——同 task
          重复/并发 run 只有一个执行器持有，其余幂等返回当前行；
        - 候选持久化与进度游标同一事务（崩溃不会出现"候选已写、游标未记"），
          且写入前替换该 (task_id, fid) 既有候选（重启重跑不重复）；
        - 终态=条件 UPDATE（仅 running→终态）——取消竞争不会被 completed 覆盖；
        - 执行中任务被删除 → ValueError 明确报错（不再 refresh(None) 崩溃）。
        模型调用始终在会话之外，不占用数据库写事务。
        """
        model = model_client or StubMatchModel()
        known = self.known_fids()
        published_ids = self.published_rule_ids()
        published_summary = self.published_rules_summary()
        records_by_fid = {r["fid"]: r for r in self.coverage_records()}

        started = time.monotonic()
        total_attempts = 0
        with self.session_factory() as session:
            task = session.get(MatchTaskRow, task_id)
            if task is None:
                raise ValueError(f"task not found: {task_id}")
            if task.status in (MATCH_COMPLETED, MATCH_CANCELLED):
                session.refresh(task)
                return task
            if task.status == MATCH_RUNNING:
                # 并发重复 run：另一执行器持有，幂等返回不重复执行
                return task
            claimed = session.execute(
                update(MatchTaskRow)
                .where(MatchTaskRow.id == task_id,
                       MatchTaskRow.status.in_([MATCH_PENDING, MATCH_PARTIAL,
                                                MATCH_FAILED]))
                .values(status=MATCH_RUNNING, updated_at=datetime.now()))
            if claimed.rowcount == 0:
                session.rollback()
                current = session.get(MatchTaskRow, task_id)
                if current is None:
                    raise ValueError(f"task not found: {task_id}")
                return current
            session.commit()
            processed = set(json.loads(task.processed_fids_json or "[]"))
            failed = list(json.loads(task.failed_fids_json or "[]"))
            fids = [int(f) for f in json.loads(task.fid_filter_json or "[]")]

        for fid in fids:
            with self.session_factory() as session:
                current = session.get(MatchTaskRow, task_id)
                if current is None:
                    raise ValueError(
                        f"task disappeared during run: {task_id}")
                if current.status == MATCH_CANCELLED:
                    session.refresh(current)
                    return current
            if fid in processed:
                continue
            record = records_by_fid[fid]

            exact = self._exact_match_record(record)
            if exact is not None:
                self._commit_fid_progress(task_id, fid, exact,
                                          exact_match=True, failed=failed)
                processed.add(fid)
                continue

            prompt = build_match_input(record, published_summary)
            attempt = 0
            result_parsed: Optional[dict] = None
            last_error = ""
            while attempt < max_attempts:
                attempt += 1
                total_attempts += 1
                try:
                    raw = model.complete(prompt)
                    result_parsed = json.loads(raw)
                    break
                except ModelTimeout:
                    last_error = f"model timeout (attempt {attempt})"
                except json.JSONDecodeError as exc:
                    last_error = f"model returned invalid json (attempt {attempt}): {exc}"
                except Exception as exc:  # noqa: BLE001 —— 单 FID 失败不毒化任务
                    last_error = f"{type(exc).__name__}: {exc} (attempt {attempt})"

            if result_parsed is None:
                failed.append({"fid": fid, "error": last_error})
                self._commit_fid_progress(task_id, fid, [], failed=failed)
                processed.add(fid)
                continue

            candidates, errors = validate_model_output(result_parsed, known,
                                                       published_ids)
            if errors:
                failed.append({"fid": fid, "error": "; ".join(errors)})
            self._commit_fid_progress(task_id, fid, candidates, failed=failed)
            processed.add(fid)

        duration_ms = int((time.monotonic() - started) * 1000)
        with self.session_factory() as session:
            task = session.get(MatchTaskRow, task_id)
            if task is None:
                raise ValueError(f"task not found: {task_id}")
            failed_final = json.loads(task.failed_fids_json or "[]")
            if task.status == MATCH_CANCELLED:
                session.refresh(task)
                return task
            if task.progress_done == 0:
                final_status = MATCH_FAILED
            elif failed_final:
                final_status = MATCH_PARTIAL
            else:
                final_status = MATCH_COMPLETED
            # 条件终态：仅 running 可迁移——取消/并发竞争不覆盖
            moved = session.execute(
                update(MatchTaskRow)
                .where(MatchTaskRow.id == task_id,
                       MatchTaskRow.status == MATCH_RUNNING)
                .values(status=final_status, duration_ms=duration_ms,
                        attempts=max(1, total_attempts),
                        updated_at=datetime.now()))
            if moved.rowcount == 0:
                session.rollback()
            session.commit()
            final = session.get(MatchTaskRow, task_id)
            if final is None:
                raise ValueError(f"task not found: {task_id}")
            session.refresh(final)
            return final

    def _commit_fid_progress(self, task_id: str, fid: int, candidates: list,
                             failed: Optional[list] = None,
                             exact_match: bool = False) -> None:
        """单 FID 候选持久化 + 游标推进 = 同一事务；同 (task_id, fid) 先替换。"""
        with self.session_factory() as session:
            task = session.get(MatchTaskRow, task_id)
            if task is None:
                raise ValueError(f"task disappeared during run: {task_id}")
            session.execute(delete(MatchCandidateRow).where(
                MatchCandidateRow.task_id == task_id,
                MatchCandidateRow.fid == int(fid)))
            for cand in candidates:
                session.add(MatchCandidateRow(
                    id=new_id(), task_id=task_id, fid=int(fid),
                    clause_id=cand.get("clause_id", f"FID{fid}-C1"),
                    matched_rule_ids_json=json.dumps(
                        cand.get("matched_rule_ids") or [], ensure_ascii=False),
                    suggested_dsl_json=json.dumps(
                        cand.get("suggested_dsl") or {}, ensure_ascii=False),
                    field_refs_json=json.dumps(cand.get("field_refs") or [],
                                               ensure_ascii=False),
                    covered_clauses=cand.get("covered_clauses", ""),
                    uncovered_clauses=cand.get("uncovered_clauses", ""),
                    rationale=cand.get("rationale", ""),
                    confidence=cand.get("confidence", ""),
                    blocking_reasons_json=json.dumps(
                        cand.get("blocking_reasons") or [], ensure_ascii=False),
                    validation_ok=1 if cand.get("validation_ok") else 0,
                    validation_errors_json=json.dumps(
                        cand.get("validation_errors") or [], ensure_ascii=False),
                    exact_match=1 if exact_match else 0,
                ))
            task.progress_done = int(task.progress_done or 0) + 1
            processed = set(json.loads(task.processed_fids_json or "[]"))
            processed.add(int(fid))
            task.processed_fids_json = json.dumps(sorted(processed))
            if failed is not None:
                task.failed_fids_json = json.dumps(failed, ensure_ascii=False)
            task.updated_at = datetime.now()
            session.commit()

    # ---- 候选决策 ----

    def decide_candidate(self, candidate_id: str, decision: str, actor,
                         note: str = "") -> MatchCandidateRow:
        if decision not in ("accepted", "rejected"):
            raise ValueError("decision must be accepted/rejected")
        with self.session_factory() as session:
            row = session.get(MatchCandidateRow, candidate_id)
            if row is None:
                raise ValueError(f"candidate not found: {candidate_id}")
            if row.decision not in ("pending",):
                raise ValueError(f"candidate already decided: {row.decision}")
            if not row.validation_ok and decision == "accepted":
                raise ValueError(
                    "candidate failed deterministic validation; cannot accept")
            row.decision = decision
            row.decided_by = actor.id
            row.decided_at = datetime.now()
            row.decided_note = note[:500]
            session.commit()
            session.refresh(row)
            return row


# ---------------------------------------------------------------------------
# 覆盖账本仓储（导入/查询）
# ---------------------------------------------------------------------------

class CoverageRepository:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    def import_snapshot(self, records: list[dict], *, apply: bool,
                        actor_id: str) -> dict:
        """目录+覆盖行导入（幂等：同 snapshot 同 FID 跳过；保留历史批次）。"""
        report = {"apply": apply, "catalog_created": 0, "catalog_skipped": 0,
                  "coverage_upserted": 0, "diff": {"added": [], "renamed": [],
                                                   "rescored": [], "retyped": [],
                                                   "disabled": []}}
        with self.session_factory() as session:
            existing_texts = {
                row.fid: row.original_text for row in session.execute(
                    select(CatalogItemRow)).scalars().all()}
            for record in records:
                row = session.execute(
                    select(CatalogItemRow).where(
                        CatalogItemRow.snapshot_id == record["snapshot_id"],
                        CatalogItemRow.fid == record["fid"])
                ).scalar_one_or_none()
                if row is not None:
                    report["catalog_skipped"] += 1
                    continue
                old_text = existing_texts.get(record["fid"])
                if old_text is None:
                    report["diff"]["added"].append(record["fid"])
                elif old_text != record["original_text"]:
                    report["diff"]["renamed"].append(record["fid"])
                if apply:
                    session.add(CatalogItemRow(
                        id=new_id(),
                        source_system=record["source_system"],
                        snapshot_id=record["snapshot_id"],
                        fid=record["fid"],
                        original_text=record["original_text"],
                        original_text_sha256=record["original_text_sha256"],
                        score=record["score"],
                        group_code=record["group_code"],
                        group_name=record["group_name"],
                        enabled=1 if record["enabled"] else 0,
                        imported_by=actor_id,
                    ))
                report["catalog_created"] += 1
            if apply:
                for record in records:
                    for clause in record["clauses"]:
                        row = session.execute(
                            select(CoverageMapRow).where(
                                CoverageMapRow.fid == record["fid"],
                                CoverageMapRow.clause_id == clause["clause_id"])
                        ).scalar_one_or_none()
                        data = dict(
                            clause_text=clause["clause_text"],
                            method=clause["method"],
                            coverage=clause["coverage"],
                            rule_ids_json=json.dumps(clause["rule_ids"],
                                                     ensure_ascii=False),
                            covered_clauses=clause["covered_clauses"],
                            uncovered_clauses=clause["uncovered_clauses"],
                            fields_json=json.dumps(clause["fields"],
                                                   ensure_ascii=False),
                            sources_json=json.dumps(clause["sources"],
                                                    ensure_ascii=False),
                            threshold_source=clause["threshold_source"],
                            blocked_reason=clause["blocked_reason"],
                            example_positive=clause["example_positive"],
                            example_negative=clause["example_negative"],
                            severity_suggestion=record["severity_suggestion"],
                            ref_score=record["score"],
                            linked_tests_json=json.dumps(clause["linked_tests"],
                                                         ensure_ascii=False),
                        )
                        if row is None:
                            session.add(CoverageMapRow(
                                id=new_id(), fid=record["fid"],
                                clause_id=clause["clause_id"], **data))
                        else:
                            for key, value in data.items():
                                setattr(row, key, value)
                        report["coverage_upserted"] += 1
                session.commit()
        return report

    def list_coverage(self, *, fid: Optional[int] = None, method: str = "",
                      status: str = "", q: str = "", page: int = 1,
                      page_size: int = 50) -> tuple:
        """覆盖账本检索（FID 聚合视角；q 匹配目录原文/条款文本/阻塞原因）。"""
        with self.session_factory() as session:
            rows = session.execute(select(
                CoverageMapRow).order_by(CoverageMapRow.fid,
                                         CoverageMapRow.clause_id)
            ).scalars().all()
            catalog_texts = {row.fid: row.original_text for row in session.execute(
                select(CatalogItemRow)).scalars().all()}
        items: dict[int, dict] = {}
        for row in rows:
            if fid is not None and row.fid != int(fid):
                continue
            if method and row.method != method:
                continue
            if status and row.status != status:
                continue
            entry = items.setdefault(row.fid, {
                "fid": row.fid, "clauses": [], "status": "draft",
                "original_text": catalog_texts.get(row.fid, ""),
                "severity_suggestion": row.severity_suggestion,
                "ref_score": row.ref_score})
            entry["clauses"].append(self._clause_dict(row))
            entry["status"] = row.status
        # FID 无覆盖行时也保留目录占位（账本完整性）
        if fid is not None and int(fid) not in items:
            items[int(fid)] = {"fid": int(fid), "clauses": [], "status": "none",
                               "original_text": catalog_texts.get(int(fid), "")}
        result = list(items.values())
        if q:
            needle = q.strip()
            result = [e for e in result if needle in (e.get("original_text") or "")
                      or any(needle in (c.get("clause_text") or "")
                             or needle in (c.get("blocked_reason") or "")
                             for c in e["clauses"])]
        total = len(result)
        start = max(0, (page - 1) * page_size)
        return result[start:start + page_size], total

    @staticmethod
    def _clause_dict(row: CoverageMapRow) -> dict:
        return {
            "clause_id": row.clause_id,
            "clause_text": row.clause_text,
            "method": row.method,
            "coverage": row.coverage,
            "rule_ids": json.loads(row.rule_ids_json or "[]"),
            "fields": json.loads(row.fields_json or "[]"),
            "sources": json.loads(row.sources_json or "[]"),
            "threshold_source": row.threshold_source,
            "blocked_reason": row.blocked_reason,
            "status": row.status,
            "linked_tests": json.loads(row.linked_tests_json or "[]"),
        }

    def catalog_counts(self) -> dict:
        with self.session_factory() as session:
            rows = session.execute(select(CoverageMapRow)).scalars().all()
        from .coverage import coverage_counts
        by_fid: dict[int, dict] = {}
        for row in rows:
            entry = by_fid.setdefault(row.fid, {"fid": row.fid, "clauses": []})
            entry["clauses"].append({"coverage": row.coverage, "method": row.method})
        return coverage_counts(list(by_fid.values()))

    def confirm_fid(self, fid: int, actor) -> int:
        """人工确认某 FID 覆盖行（confirmed 后匹配精确命中复用，不被模型覆盖）。"""
        with self.session_factory() as session:
            rows = session.execute(select(CoverageMapRow).where(
                CoverageMapRow.fid == int(fid))).scalars().all()
            if not rows:
                raise ValueError(f"no coverage rows for fid {fid}")
            for row in rows:
                row.status = "confirmed"
                row.confirmed_by = actor.id
                row.confirmed_at = datetime.now()
                row.verified_at = datetime.now()
            session.commit()
            return len(rows)
