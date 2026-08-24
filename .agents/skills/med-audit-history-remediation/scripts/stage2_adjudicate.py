"""Stage 2 — 本地二次裁决：外部 AI 影子结果 × 本地规则。

按 skill Stage 2 强制顺序：
1. 重新运行后端复合门槛（_qualified_high_risk_issue）
   - 本集合全部为 formally_unqualified（Stage 1 筛选条件），
     按 skill 规则：不满足硬门槛 → 不得 keep_high，进降级候选。
2. 本地确定性语义辅助（evaluate_semantic_high_risk_dim）
   - should_demote=true → 至少 manual_review 或降级。
3. 类型特别限制（prompt-routing §4）
   - jyjc 所有 omission 最高 medium/manual_review，不得 high。
4. 生成四张清单：
   - approved_keep_high   （本集合理论上为空：门槛已不通过）
   - approved_downgrade   （AI 降级 + 门槛不通过，一致降级）
   - manual_review        （AI keep_high 但门槛不通过 / 解析问题 / 语义冲突）
   - rejected             （数据异常）

不写生产数据库。输出 token + 决定 + 理由码，不含患者标识。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

try:
    REPO_ROOT = Path(__file__).resolve().parents[4]
except IndexError:
    REPO_ROOT = Path("/app")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import func, or_

from app.database import SessionLocal
from app.models import AuditDimensionResult, PushLog
from app.services.dify_schema_parser import _qualified_high_risk_issue


def _loads(raw, fallback):
    if raw in (None, ""):
        return fallback
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return fallback


def _evidence_from_extra(extra, side):
    issue_key = "evidence_a" if side == "medical" else "evidence_b"
    issues = extra.get("issues") if isinstance(extra.get("issues"), list) else []
    values = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        v = issue.get(issue_key)
        if isinstance(v, list):
            values.extend(str(x).strip() for x in v if str(x or "").strip())
        elif str(v or "").strip():
            values.append(str(v).strip())
    if values:
        return values
    legacy = extra.get(f"{side}_evidence_legacy")
    if isinstance(legacy, list):
        return [str(x).strip() for x in legacy if str(x or "").strip()]
    return [str(legacy).strip()] if str(legacy or "").strip() else []


def _evidence_list(evidence_json, content, extra, side):
    arr = _loads(evidence_json, [])
    if isinstance(arr, list) and any(str(x or "").strip() for x in arr):
        return [str(x) for x in arr if str(x or "").strip()]
    text = str(content or "").strip()
    return [text] if text else _evidence_from_extra(extra, side)


def _dim_dict_from_orm(row):
    extra = _loads(getattr(row, "extra_json", None), {})
    if not isinstance(extra, dict):
        extra = {}
    return {
        "dimension_code": getattr(row, "dimension_code", "") or "",
        "dimension": getattr(row, "dimension", "") or "",
        "status": getattr(row, "status", "") or "",
        "severity": (getattr(row, "severity", "") or "").lower(),
        "alert_level": (getattr(row, "alert_level", "") or "").lower(),
        "confidence": float(getattr(row, "confidence", 0) or 0),
        "medical_evidence": _evidence_list(
            getattr(row, "medical_evidence_json", None),
            getattr(row, "medical_content", None), extra, "medical"),
        "nursing_evidence": _evidence_list(
            getattr(row, "nursing_evidence_json", None),
            getattr(row, "nursing_content", None), extra, "nursing"),
        "medical_content": getattr(row, "medical_content", "") or "",
        "nursing_content": getattr(row, "nursing_content", "") or "",
        "extra": extra,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 2: 本地二次裁决")
    parser.add_argument("--apply", action="store_true", help="始终拒绝")
    parser.add_argument("--shadow", default="/tmp/stage1_review/stage1_5_full.json")
    parser.add_argument("--mapping", default="/tmp/stage1_review/stage1_internal_mapping.json")
    parser.add_argument("--output", default="/tmp/stage1_review/stage2_adjudication.json")
    args = parser.parse_args()
    if args.apply:
        parser.error("Stage 2 禁止 --apply")

    # 加载影子结果 + 映射
    with open(args.shadow, encoding="utf-8") as f:
        shadow = json.load(f)
    with open(args.mapping, encoding="utf-8") as f:
        mapping = json.load(f).get("mappings", {})
    token_to_ids = {t: (m["push_log_id"], m["dimension_id"], m["audit_type_code"])
                    for t, m in mapping.items()}
    print(f"影子结果: {len(shadow['results'])} 条, 映射: {len(token_to_ids)} 条")

    db = SessionLocal()
    try:
        # 预载全部 high/red 维度行(按 id 索引)
        dim_filter = or_(
            func.lower(AuditDimensionResult.severity) == "high",
            func.lower(AuditDimensionResult.alert_level) == "red",
        )
        dim_rows = db.query(AuditDimensionResult).filter(dim_filter).all()
        dim_by_id = {int(r.id): r for r in dim_rows}
        print(f"库内 high/red 维度行: {len(dim_by_id)}")

        # 语义 shadow 可用则加载
        try:
            from app.services.high_risk_semantic_shadow import evaluate_semantic_high_risk_dim
            shadow_semantic_available = True
        except ImportError:
            shadow_semantic_available = False
        print(f"语义 shadow 可用: {shadow_semantic_available}")

        lists = {
            "approved_keep_high": [],
            "approved_downgrade": [],
            "manual_review": [],
            "rejected": [],
        }
        stats = Counter()

        for rec in shadow["results"]:
            token = rec["review_token"]
            ai_decision = rec.get("shadow_decision", "")
            ids = token_to_ids.get(token)
            if not ids:
                lists["rejected"].append({
                    "review_token": token, "reason_code": "token_not_in_mapping"})
                stats["rejected__token_not_in_mapping"] += 1
                continue
            pl_id, dim_id, audit_code = ids

            row = dim_by_id.get(dim_id)
            if row is None:
                lists["rejected"].append({
                    "review_token": token, "reason_code": "dim_row_not_found"})
                stats["rejected__dim_row_not_found"] += 1
                continue

            # ── 规则 1: 后端复合门槛重算 ──
            dim_dict = _dim_dict_from_orm(row)
            qualified = _qualified_high_risk_issue(dim_dict, audit_code)

            # ── 规则 2: 语义 shadow ──
            semantic_demote = False
            semantic_reasons = []
            if shadow_semantic_available and qualified is not None:
                try:
                    result = evaluate_semantic_high_risk_dim(dim_dict, audit_code)
                    semantic_demote = bool(result.get("should_demote"))
                    semantic_reasons = list(result.get("reasons") or [])
                except Exception as exc:  # noqa: BLE001
                    semantic_reasons = [f"shadow_error__{type(exc).__name__}"]

            # ── 规则 3: 类型特别限制 ──
            type_note = ""
            if audit_code == "jyjc_vs_bcnursing":
                type_note = "jyjc: omission 最高 medium/manual_review"

            # ── 裁决逻辑 ──
            base = {
                "review_token": token,
                "audit_type_code": audit_code,
                "dimension_code": rec.get("dimension_code", ""),
                "historical_severity": rec.get("historical_severity", "high"),
                "ai_decision": ai_decision,
                "ai_shadow_severity": rec.get("shadow_severity", ""),
            }

            if qualified is not None:
                # 本集合不应出现（Stage 1 已筛 unqualified），出现即数据漂移
                lists["manual_review"].append({**base,
                    "reason_code": "gate_recheck_conflict",
                    "note": "Stage1 unqualified 但本次重算通过,数据可能已变化"})
                stats["manual__gate_recheck_conflict"] += 1
                continue

            # 门槛不通过（本集合的预期状态）
            gate_block = True

            if ai_decision in ("downgrade_low", "downgrade_medium"):
                # AI 建议降级 + 门槛不通过 → 一致降级
                target = ("pass_low_blue" if ai_decision == "downgrade_low"
                          else "warn_medium_yellow")
                lists["approved_downgrade"].append({**base,
                    "reason_code": f"gate_unqualified_ai_{ai_decision}",
                    "target_mapping": target,
                    "type_note": type_note})
                stats[f"downgrade__{ai_decision}"] += 1

            elif ai_decision == "keep_high":
                # AI 说维持，但门槛不通过 → skill 强制：不得 keep_high
                # 默认进人工（更保守），语义 shadow 支持 demote 时可作降级候选
                entry = {**base,
                    "reason_code": "gate_unqualified_ai_keep_high_conflict",
                    "semantic_demote": semantic_demote,
                    "semantic_reasons": semantic_reasons[:3],
                    "type_note": type_note}
                lists["manual_review"].append(entry)
                stats["manual__keep_high_blocked_by_gate"] += 1

            else:
                # manual_review_parse_issue 等
                lists["manual_review"].append({**base,
                    "reason_code": f"ai_{ai_decision or 'unknown'}",
                    "type_note": type_note})
                stats[f"manual__{ai_decision or 'unknown'}"] += 1

        # 输出
        output = {
            "stage": "Stage 2 — 本地二次裁决",
            "generated_at": datetime.now().isoformat(),
            "input_shadow_results": len(shadow["results"]),
            "gate_rule": "全部候选为 Stage1 formally_unqualified; skill 规则:门槛不通过不得 keep_high",
            "semantic_shadow_available": shadow_semantic_available,
            "list_sizes": {k: len(v) for k, v in lists.items()},
            "stats": dict(sorted(stats.items())),
            "lists": lists,
            "next_step": "临床质控负责人批准精确 token/目标等级/理由码 → Stage 3 dry-run",
            "stop_point": "临床质控负责人批准",
        }
        out_path = Path(args.output)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        sha = hashlib.sha256()
        with open(out_path, "rb") as f:
            sha.update(f.read())

        print(f"\n=== Stage 2 完成 ===")
        print(f"输出: {out_path}")
        print(f"SHA-256: {sha.hexdigest().upper()}")
        print(f"四张清单: {output['list_sizes']}")
        print(f"统计: {output['stats']}")
        return 0
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
