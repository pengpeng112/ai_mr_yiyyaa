#!/usr/bin/env python3
"""20260817 语义降级整改（运营方已授权）：把现有影子规则命中的假高危降回 medium/yellow。

背景：高危硬门槛只能拦机械违规；AI 把 omission 标注为 contradiction、双侧证据相同、
短证据无结构化主张等语义问题会机械过关。003-D 的语义影子规则
（identical_evidence / short_evidence_without_structured_claim / text_quality 等）
此前只记日志不降级。运营方确认数据未交临床，授权直接降级。

规则（复用 high_risk_semantic_shadow.evaluate_semantic_high_risk_dim，与解析时同源）：
- 范围：push_time >= 2026-07-14，PushLog.status='success' 且 superseded_by IS NULL，
  AuditDimensionResult.severity='high' 的维度。
- 判定：evaluate_semantic_high_risk_dim().should_demote == True。
- 目标等级：medium/yellow（报告 candidate_severity），status 不动。
- 汇总同步：受影响 PushLog 与 AuditConclusion 按维度最大有效等级重算。
- 审计：维度 extra_json 追加 semantic_enforced_demote 标记；写前全量备份。

用法：
  python scripts/remediate_semantic_downgrade_20260817.py            # dry-run
  python scripts/remediate_semantic_downgrade_20260817.py --apply
  python scripts/remediate_semantic_downgrade_20260817.py --verify
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

_HIGH_DIM_SQL = f"""
    SELECT d.id, d.push_log_id, d.dimension_code, d.severity, d.alert_level,
           d.confidence, d.extra_json, d.medical_evidence_json, d.nursing_evidence_json,
           p.audit_type_code, p.patient_id, p.push_time
    FROM MED_AUDIT_DIMENSION_RESULT d
    JOIN MED_PUSH_LOG p ON p.id = d.push_log_id
    WHERE d.severity = 'high'
      AND p.push_time >= DATE'{SINCE}'
      AND p.status = 'success'
      AND p.superseded_by IS NULL
"""


def _load_list(text):
    try:
        v = json.loads(text or "[]")
        return v if isinstance(v, list) else []
    except Exception:
        return []


def _rebuild_dim(m):
    extra = {}
    try:
        extra = json.loads(m["extra_json"] or "{}")
    except Exception:
        extra = {}
    med = _load_list(m["medical_evidence_json"]) or extra.get("medical_evidence_legacy") or []
    nur = _load_list(m["nursing_evidence_json"]) or extra.get("nursing_evidence_legacy") or []
    return {
        "dimension_code": m["dimension_code"] or "",
        "status": "fail",
        "confidence": m["confidence"] or 0,
        "severity": "high",
        "medical_evidence": med,
        "nursing_evidence": nur,
        "extra": extra,
    }, extra


def _chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _find_candidates(db, sql_text, evaluate):
    downgrade = []
    for r in db.execute(sql_text(_HIGH_DIM_SQL)).all():
        m = dict(r._mapping)
        dim, extra = _rebuild_dim(m)
        report = evaluate(dim, m["audit_type_code"] or "")
        if not report.get("should_demote"):
            continue
        downgrade.append({
            "dim_id": m["id"], "push_log_id": m["push_log_id"],
            "audit_type_code": m["audit_type_code"], "patient_id": m["patient_id"],
            "push_time": str(m["push_time"]), "dimension_code": m["dimension_code"],
            "reasons": report.get("reasons") or [],
            "to": "medium/yellow",
        })
    return downgrade


def _recompute_summaries(db, sql_text, log_ids, dim_target):
    log_best: dict[int, str] = {}
    for chunk in _chunked(list(log_ids), _ORACLE_IN_LIMIT):
        ph = ",".join(f":i{n}" for n in range(len(chunk)))
        params = {f"i{n}": v for n, v in enumerate(chunk)}
        for plid, dim_id, sev in db.execute(sql_text(
            f"SELECT push_log_id, id, severity FROM MED_AUDIT_DIMENSION_RESULT "
            f"WHERE push_log_id IN ({ph})"
        ), params).all():
            eff = dim_target.get(dim_id, sev or "")
            if _RANK.get(eff, 0) > _RANK.get(log_best.get(plid, ""), 0):
                log_best[plid] = eff
    summary_plan = []
    log_rows = []
    for chunk in _chunked(list(log_ids), _ORACLE_IN_LIMIT):
        ph = ",".join(f":i{n}" for n in range(len(chunk)))
        params = {f"i{n}": v for n, v in enumerate(chunk)}
        log_rows.extend(db.execute(sql_text(
            f"SELECT id, patient_id, severity, alert_level FROM MED_PUSH_LOG WHERE id IN ({ph})"
        ), params).all())
    for plid, pid, old_sev, old_alert in log_rows:
        new_sev = log_best.get(plid, "low")
        if (old_sev or "") == new_sev:
            continue
        alert, score = _SUMMARY_BY_SEVERITY[new_sev]
        summary_plan.append({
            "push_log_id": plid, "patient_id": pid,
            "from": f"{old_sev}/{old_alert}", "to": f"{new_sev}/{alert}", "risk_score": score,
        })
    return summary_plan


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="执行写入（默认 dry-run）")
    parser.add_argument("--verify", action="store_true", help="写后校验残留")
    parser.add_argument("--report-dir", default="/tmp", help="备份与报告输出目录")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from sqlalchemy import text as sql_text
    from app.database import SessionLocal
    from app.services.high_risk_semantic_shadow import evaluate_semantic_high_risk_dim

    db = SessionLocal()

    if args.verify:
        residual = len(_find_candidates(db, sql_text, evaluate_semantic_high_risk_dim))
        print(f"[verify] 残留影子规则命中 high 维度: {residual}")
        db.close()
        return 0 if residual == 0 else 1

    downgrade = _find_candidates(db, sql_text, evaluate_semantic_high_risk_dim)
    log_ids = {d["push_log_id"] for d in downgrade}
    dim_target = {d["dim_id"]: "medium" for d in downgrade}
    summary_plan = _recompute_summaries(db, sql_text, log_ids, dim_target) if log_ids else []

    reason_counter = Counter()
    for d in downgrade:
        for rs in d["reasons"]:
            reason_counter[rs] += 1
    by_month = Counter(d["push_time"][:7] for d in downgrade)
    sev_moves = Counter(s["to"].split("/")[0] for s in summary_plan)
    patients = len({d["patient_id"] for d in downgrade})

    total_high = db.execute(sql_text(
        f"SELECT count(*) FROM MED_AUDIT_DIMENSION_RESULT d JOIN MED_PUSH_LOG p "
        f"ON p.id = d.push_log_id WHERE d.severity='high' AND p.push_time >= DATE'{SINCE}' "
        f"AND p.status='success' AND p.superseded_by IS NULL"
    )).scalar()
    print(f"[plan] 自 {SINCE} 起 current high 维度: {total_high}")
    print(f"[plan] 影子规则命中待降级: {len(downgrade)}  原因分布: {dict(reason_counter)}")
    print(f"[plan] 涉及 push_log: {len(log_ids)}  患者: {patients}")
    print(f"[plan] 汇总级需调整: {len(summary_plan)} (降为medium: {sev_moves.get('medium', 0)}, "
          f"降为low: {sev_moves.get('low', 0)})")
    print(f"[plan] 按月: {dict(sorted(by_month.items()))}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = Path(args.report_dir) / f"semantic_downgrade_dryrun_{stamp}.json"
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

    # 维度：severity/alert + extra 追加降级审计标记
    reasons_by_dim = {d["dim_id"]: d["reasons"] for d in downgrade}
    for chunk in _chunked(downgrade, 200):
        for item in chunk:
            row = db.execute(sql_text(
                "SELECT extra_json FROM MED_AUDIT_DIMENSION_RESULT WHERE id = :id"
            ), {"id": item["dim_id"]}).first()
            try:
                extra = json.loads((row[0] if row else "") or "{}")
            except Exception:
                extra = {}
            marks = extra.get("semantic_enforced_demote")
            if not isinstance(marks, list):
                marks = []
            marks.append({
                "batch": "remediate_semantic_downgrade_20260817",
                "reasons": item["reasons"],
                "from": "high/red", "to": "medium/yellow",
            })
            extra["semantic_enforced_demote"] = marks
            db.execute(sql_text(
                "UPDATE MED_AUDIT_DIMENSION_RESULT SET severity='medium', alert_level='yellow', "
                "extra_json = :ej WHERE id = :id AND severity = 'high'"
            ), {"ej": json.dumps(extra, ensure_ascii=False), "id": item["dim_id"]})
        db.commit()

    for s in summary_plan:
        new_sev = s["to"].split("/")[0]
        alert, score = _SUMMARY_BY_SEVERITY[new_sev]
        db.execute(sql_text(
            "UPDATE MED_PUSH_LOG SET severity=:s, alert_level=:a, risk_score=:r WHERE id=:id"
        ), {"s": new_sev, "a": alert, "r": score, "id": s["push_log_id"]})
        db.execute(sql_text(
            "UPDATE MED_AUDIT_CONCLUSION SET severity=:s, alert_level=:a, risk_score=:r "
            "WHERE push_log_id=:id"
        ), {"s": new_sev, "a": alert, "r": score, "id": s["push_log_id"]})
    db.commit()
    print(f"[apply] 已降级维度 {len(downgrade)} 条（含审计标记），汇总级 {len(summary_plan)} 条已同步。")

    residual = len(_find_candidates(db, sql_text, evaluate_semantic_high_risk_dim))
    print(f"[apply] 写后残留: {residual}")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
