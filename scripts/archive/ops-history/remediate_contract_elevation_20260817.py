#!/usr/bin/env python3
"""20260817 契约校验器抬升整改：把不合格高危维度降回 medium/yellow（或 low/blue）。

背景：result_contract_validator.normalize_dimension_combo 曾把 (fail, medium, yellow)
强制"修复"为 (fail, high, red)（STATUS_TO_SEVERITY fail→high），发生在高危守卫之后，
导致工作流按 general 规则输出的中风险问题被抬成高危落库。代码已于 20260817 修复为
"只降不升"；本脚本负责回滚 2026-07-14 以来已被抬升的历史数据。

规则（与后端硬门槛完全一致，复用 _qualified_high_risk_issue）：
- 范围：push_time >= 2026-07-14，PushLog.status='success' 且 superseded_by IS NULL，
  AuditDimensionResult.severity='high' 的维度。
- 判定：用维度存储的 extra.issues + 双侧证据跑 _qualified_high_risk_issue，
  不合格者视为被抬升的假高危。
- 目标等级：issues 全为 hint → low/blue；否则 medium/yellow（general→medium 契约）。
- 汇总同步：受影响 PushLog 与 AuditConclusion 的 severity/alert_level/risk_score
  按维度最大有效等级重算（high=red/90, medium=yellow/60, low=blue/20）。
- 不触碰：维度 status、response_json、QCRecordAlertLog（发送时点快照）、QCFeedback。

用法（容器内或本地应用库）：
  python scripts/remediate_contract_elevation_20260817.py            # dry-run（默认）
  python scripts/remediate_contract_elevation_20260817.py --apply    # 生产写入（需批准）
  python scripts/remediate_contract_elevation_20260817.py --verify   # 写后校验
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

SINCE = "2026-07-14"
_ORACLE_IN_LIMIT = 900

_SUMMARY_BY_SEVERITY = {
    "high": ("red", 90),
    "medium": ("yellow", 60),
    "low": ("blue", 20),
}
_RANK = {"low": 1, "medium": 2, "high": 3}


def _load_list(text):
    try:
        v = json.loads(text or "[]")
        return v if isinstance(v, list) else []
    except Exception:
        return []


def _rebuild_dim(row) -> tuple[dict, dict]:
    """从 DB 行重建解析器同构的 dim dict（evidence 兼容 legacy 列与 extra legacy）。"""
    extra = {}
    try:
        extra = json.loads(row.extra_json or "{}")
    except Exception:
        extra = {}
    med = _load_list(row.medical_evidence_json) or extra.get("medical_evidence_legacy") or []
    nur = _load_list(row.nursing_evidence_json) or extra.get("nursing_evidence_legacy") or []
    dim = {
        "dimension_code": row.dimension_code or "",
        "status": row.status,
        "confidence": row.confidence or 0,
        "severity": row.severity,
        "medical_evidence": med,
        "nursing_evidence": nur,
        "extra": extra,
    }
    return dim, extra


def _target_level(extra: dict) -> tuple[str, str]:
    """issues 全为 hint → low/blue；否则 medium/yellow。无 issues 视为 general。"""
    levels = [
        str(i.get("level") or "").strip().lower()
        for i in (extra.get("issues") or [])
        if isinstance(i, dict)
    ]
    if levels and all(l == "hint" for l in levels):
        return "low", "blue"
    return "medium", "yellow"


class _Row:
    """把 SQL 行的映射统一成属性访问。"""

    _FIELDS = (
        "id", "push_log_id", "dimension_code", "status", "severity", "alert_level",
        "confidence", "extra_json", "medical_evidence_json", "nursing_evidence_json",
        "audit_type_code", "patient_id", "push_time",
    )

    def __init__(self, r):
        m = dict(r._mapping) if hasattr(r, "_mapping") else dict(r)
        for f in self._FIELDS:
            setattr(self, f, m.get(f))


_HIGH_DIM_SQL = f"""
    SELECT d.id, d.push_log_id, d.dimension_code, d.status, d.severity,
           d.alert_level, d.confidence, d.extra_json,
           d.medical_evidence_json, d.nursing_evidence_json,
           p.audit_type_code, p.patient_id, p.push_time
    FROM MED_AUDIT_DIMENSION_RESULT d
    JOIN MED_PUSH_LOG p ON p.id = d.push_log_id
    WHERE d.severity = 'high'
      AND p.push_time >= DATE'{SINCE}'
      AND p.status = 'success'
      AND p.superseded_by IS NULL
"""


def _find_false_highs(db, sql_text, parser_checks):
    """返回 (downgrade 明细 list, dim_id -> 目标 severity 的映射)。"""
    _is_high_risk_dimension, _qualified_high_risk_issue = parser_checks
    downgrade = []
    dim_target: dict[int, str] = {}
    for r in db.execute(sql_text(_HIGH_DIM_SQL)).all():
        m = _Row(r)
        dim, extra = _rebuild_dim(m)
        if _is_high_risk_dimension(dim) and _qualified_high_risk_issue(dim, m.audit_type_code):
            continue
        sev, alert = _target_level(extra)
        downgrade.append({
            "dim_id": m.id, "push_log_id": m.push_log_id,
            "audit_type_code": m.audit_type_code, "patient_id": m.patient_id,
            "push_time": str(m.push_time), "dimension_code": m.dimension_code,
            "from": "high/red", "to": f"{sev}/{alert}",
        })
        dim_target[m.id] = sev
    return downgrade, dim_target


def _chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _load_log_dims(db, sql_text, log_ids):
    """批量取受影响 push_log 的全部维度 (push_log_id, dim_id, severity)，规避 IN 上限。"""
    rows = []
    for chunk in _chunked(list(log_ids), _ORACLE_IN_LIMIT):
        placeholders = ",".join(f":i{n}" for n in range(len(chunk)))
        params = {f"i{n}": v for n, v in enumerate(chunk)}
        rows.extend(db.execute(sql_text(
            f"SELECT push_log_id, id, severity FROM MED_AUDIT_DIMENSION_RESULT "
            f"WHERE push_log_id IN ({placeholders})"
        ), params).all())
    return rows


def _recompute_summaries(db, sql_text, log_ids, dim_target):
    """按维度最大有效等级重算每个受影响 push_log 的汇总目标等级。"""
    log_best: dict[int, str] = {}
    for plid, dim_id, sev in _load_log_dims(db, sql_text, log_ids):
        eff = dim_target.get(dim_id, sev or "")
        if _RANK.get(eff, 0) > _RANK.get(log_best.get(plid, ""), 0):
            log_best[plid] = eff

    summary_plan = []
    log_rows = []
    for chunk in _chunked(list(log_ids), _ORACLE_IN_LIMIT):
        placeholders = ",".join(f":i{n}" for n in range(len(chunk)))
        params = {f"i{n}": v for n, v in enumerate(chunk)}
        log_rows.extend(db.execute(sql_text(
            f"SELECT id, patient_id, severity, alert_level FROM MED_PUSH_LOG "
            f"WHERE id IN ({placeholders})"
        ), params).all())
    for r in log_rows:
        plid, pid, old_sev, old_alert = tuple(r)
        new_sev = log_best.get(plid, "low")
        if (old_sev or "") == new_sev:
            continue
        alert, score = _SUMMARY_BY_SEVERITY[new_sev]
        summary_plan.append({
            "push_log_id": plid, "patient_id": pid,
            "from": f"{old_sev}/{old_alert}", "to": f"{new_sev}/{alert}",
            "risk_score": score,
        })
    return summary_plan


def _count_residual(db, sql_text, parser_checks) -> int:
    """写后校验：仍为 high 但不合格的维度数。"""
    _is_high_risk_dimension, _qualified_high_risk_issue = parser_checks
    n = 0
    for r in db.execute(sql_text(_HIGH_DIM_SQL)).all():
        m = _Row(r)
        dim, _ = _rebuild_dim(m)
        if not (_is_high_risk_dimension(dim) and _qualified_high_risk_issue(dim, m.audit_type_code)):
            n += 1
    return n


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="执行写入（默认 dry-run）")
    parser.add_argument("--verify", action="store_true", help="写后校验残留假高危数")
    parser.add_argument("--report-dir", default="/tmp", help="备份与报告输出目录")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from sqlalchemy import text as sql_text
    from app.database import SessionLocal
    from app.services.dify_schema_parser import (
        _is_high_risk_dimension,
        _qualified_high_risk_issue,
    )
    parser_checks = (_is_high_risk_dimension, _qualified_high_risk_issue)
    db = SessionLocal()

    if args.verify:
        residual = _count_residual(db, sql_text, parser_checks)
        print(f"[verify] 残留不合格 high 维度: {residual}")
        db.close()
        return 0 if residual == 0 else 1

    downgrade, dim_target = _find_false_highs(db, sql_text, parser_checks)
    log_ids = {d["push_log_id"] for d in downgrade}
    summary_plan = _recompute_summaries(db, sql_text, log_ids, dim_target) if log_ids else []

    by_month = Counter(d["push_time"][:7] for d in downgrade)
    by_type = Counter(d["audit_type_code"] for d in downgrade)
    by_target = Counter(d["to"] for d in downgrade)
    sev_moves = Counter(s["to"].split("/")[0] for s in summary_plan)
    patients = len({d["patient_id"] for d in downgrade})

    total_high = db.execute(sql_text(
        f"SELECT count(*) FROM MED_AUDIT_DIMENSION_RESULT d JOIN MED_PUSH_LOG p "
        f"ON p.id = d.push_log_id WHERE d.severity = 'high' "
        f"AND p.push_time >= DATE'{SINCE}' AND p.status = 'success' "
        f"AND p.superseded_by IS NULL"
    )).scalar()
    print(f"[plan] 自 {SINCE} 起 current high 维度总数: {total_high}")
    print(f"[plan] 待降级维度: {len(downgrade)}  (按目标: {dict(by_target)})")
    print(f"[plan] 涉及 push_log: {len(log_ids)}  患者: {patients}")
    print(f"[plan] 汇总级需调整的 push_log: {len(summary_plan)} "
          f"(降为medium: {sev_moves.get('medium', 0)}, 降为low: {sev_moves.get('low', 0)})")
    print(f"[plan] 按月: {dict(sorted(by_month.items()))}")
    print(f"[plan] 按类型: {dict(by_type)}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = Path(args.report_dir) / f"contract_elevation_dryrun_{stamp}.json"
    report_path.write_text(json.dumps({
        "generated_at": stamp, "since": SINCE,
        "dims_total": total_high, "dims_to_downgrade": len(downgrade),
        "push_logs_affected": len(log_ids), "patients_affected": patients,
        "summary_plan": summary_plan, "downgrade": downgrade,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[plan] 明细备份: {report_path}")

    if not args.apply:
        print("[dry-run] 未写库。加 --apply 执行。")
        db.close()
        return 0

    done = 0
    for chunk in _chunked(downgrade, 200):
        for item in chunk:
            sev, alert = item["to"].split("/")
            db.execute(sql_text(
                "UPDATE MED_AUDIT_DIMENSION_RESULT SET severity = :s, alert_level = :a "
                "WHERE id = :id AND severity = 'high'"
            ), {"s": sev, "a": alert, "id": item["dim_id"]})
        db.commit()
        done += len(chunk)

    for s in summary_plan:
        new_sev = s["to"].split("/")[0]
        alert, score = _SUMMARY_BY_SEVERITY[new_sev]
        db.execute(sql_text(
            "UPDATE MED_PUSH_LOG SET severity = :s, alert_level = :a, risk_score = :r "
            "WHERE id = :id"
        ), {"s": new_sev, "a": alert, "r": score, "id": s["push_log_id"]})
        db.execute(sql_text(
            "UPDATE MED_AUDIT_CONCLUSION SET severity = :s, alert_level = :a, risk_score = :r "
            "WHERE push_log_id = :id"
        ), {"s": new_sev, "a": alert, "r": score, "id": s["push_log_id"]})
    db.commit()
    print(f"[apply] 已降级维度 {done} 条，汇总级 {len(summary_plan)} 条 push_log/conclusion 已同步。")

    residual = _count_residual(db, sql_text, parser_checks)
    print(f"[apply] 写后残留不合格 high 维度: {residual}")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
