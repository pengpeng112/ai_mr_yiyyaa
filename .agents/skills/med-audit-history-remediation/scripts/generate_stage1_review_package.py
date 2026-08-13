"""Stage 1 — 生成高危复核脱敏离线包。

严格遵循 med-audit-history-remediation skill §2 Stage 1：
- 只处理 formally_unqualified 的 high/red 维度
- 提取最小双方证据（extra.issues → content → evidence_json）
- 脱敏：移除所有患者标识，截断证据到可判断矛盾的最短片段
- 生成 review_token → ID 映射（仅院内保留）
- 附带对应类型提示词快照 SHA-256
- 计算所有文件 SHA-256

禁止：输出患者 ID/姓名/住院号/科室/绝对日期/完整病历/request_json/response_json。
禁止：任何生产写入。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

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

# ── 常量 ──
SIX_CODES = {
    "admission_vs_first_progress", "discharge_vs_frontpage", "surgery_chain",
    "progress_vs_nursing", "jyjc_vs_bcnursing", "syssvsscbc",
}
PROMPT_SHA256: dict[str, str] = {
    "admission_vs_first_progress": "36B0AA80EED38EF85E693F1F773DFA6CE264BEA4573CE9A87004639D0CDB63D2",
    "discharge_vs_frontpage": "3E7E357070894B20215201E5F01430013749DCC6D23F507B46AD6843AD3BD633",
    "surgery_chain": "88289A6AEC7A93448B155F9890D5E6B25C42E73DD62655C033D338C5DE900075",
    "progress_vs_nursing": "A6093CAC4109228EAFE9D6BA78F2511CBF52F631443AEC42FC7A9B7E889A05D1",
    "jyjc_vs_bcnursing": "812BCCB27D3F57F59EC388DA463416641367A420595996B72CAFB7B8B4596032",
    "syssvsscbc": "69D5ADB40B854F895243F3053DE649415C2168B6FA4635623A1C04F26C465023",
}
MAX_EVIDENCE_CHARS = 200  # 单侧证据最大字符数

# 脱敏正则：移除可能的 ID/号码模式
_PATTERNS_TO_REDACT = [
    (re.compile(r'\b\d{6,}\b'), '[NUMBER]'),  # 长数字串（可能是 ID/住院号）
    (re.compile(r'[\u4e00-\u9fff]{2,4}(?:科|室|中心|病区)'), '[DEPT]'),  # 科室名
    (re.compile(r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}'), '[DATE]'),  # 日期
    (re.compile(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}[\s T]\d{1,2}:\d{1,2}'), '[DATETIME]'),  # 日期时间
    (re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}'), '[EMAIL]'),  # 邮箱
    (re.compile(r'1[3-9]\d{9}'), '[PHONE]'),  # 手机号
]


def _empty(value) -> bool:
    return value is None or not str(value).strip()


def _loads(raw: Any, fallback: Any):
    if raw in (None, ""):
        return fallback
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return fallback


def _desensitize(text: str) -> str:
    """对证据文本做基本脱敏：移除数字、科室、日期、联系方式模式。"""
    result = str(text or '').strip()
    for pattern, replacement in _PATTERNS_TO_REDACT:
        result = pattern.sub(replacement, result)
    # 截断到最大长度
    if len(result) > MAX_EVIDENCE_CHARS:
        result = result[:MAX_EVIDENCE_CHARS] + '...'
    return result


def _evidence_from_extra(extra: dict[str, Any], side: str) -> str:
    """从 extra.issues 提取单侧证据文本。"""
    issue_key = "evidence_a" if side == "medical" else "evidence_b"
    issues = extra.get("issues") if isinstance(extra.get("issues"), list) else []
    values = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        value = issue.get(issue_key)
        if isinstance(value, list):
            values.extend(str(item).strip() for item in value if str(item or "").strip())
        elif str(value or "").strip():
            values.append(str(value).strip())
    if values:
        return " | ".join(values)
    legacy = extra.get(f"{side}_evidence_legacy")
    if isinstance(legacy, list):
        return " | ".join(str(item).strip() for item in legacy if str(item or "").strip())
    return str(legacy or "").strip()


def _extract_evidence(
    evidence_json: Any, content: Any, extra: dict[str, Any], side: str
) -> str:
    """按优先级提取单侧证据文本（未脱敏）。"""
    # 1. evidence 数组
    arr = _loads(evidence_json, [])
    if isinstance(arr, list) and any(str(x or "").strip() for x in arr):
        return " | ".join(str(x).strip() for x in arr if str(x or "").strip())
    # 2. content
    text = str(content or "").strip()
    if text:
        return text
    # 3. extra.issues
    return _evidence_from_extra(extra, side)


def _dim_dict_from_orm(row: AuditDimensionResult) -> dict[str, Any]:
    extra = _loads(getattr(row, "extra_json", None), {})
    if not isinstance(extra, dict):
        extra = {}
    med_ev = _extract_evidence(
        getattr(row, "medical_evidence_json", None),
        getattr(row, "medical_content", None),
        extra, "medical",
    )
    nur_ev = _extract_evidence(
        getattr(row, "nursing_evidence_json", None),
        getattr(row, "nursing_content", None),
        extra, "nursing",
    )
    return {
        "dimension_code": getattr(row, "dimension_code", "") or "",
        "dimension": getattr(row, "dimension", "") or "",
        "status": getattr(row, "status", "") or "",
        "severity": (getattr(row, "severity", "") or "").lower(),
        "alert_level": (getattr(row, "alert_level", "") or "").lower(),
        "confidence": float(getattr(row, "confidence", 0) or 0),
        "medical_evidence": [med_ev] if med_ev else [],
        "nursing_evidence": [nur_ev] if nur_ev else [],
        "medical_content": getattr(row, "medical_content", "") or "",
        "nursing_content": getattr(row, "nursing_content", "") or "",
        "extra": extra,
    }


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 1: 生成高危复核脱敏离线包")
    parser.add_argument("--apply", action="store_true", help="始终拒绝；本脚本无写入能力")
    parser.add_argument("--output-dir", default="/tmp/stage1_review", help="输出目录")
    parser.add_argument("--max-records", type=int, default=500, help="最大处理记录数")
    args = parser.parse_args()
    if args.apply:
        parser.error("Stage 1 脱敏脚本禁止 --apply")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    db = SessionLocal()
    try:
        # 1. 查找 high/red 维度
        dim_filter = or_(
            func.lower(AuditDimensionResult.severity) == "high",
            func.lower(AuditDimensionResult.alert_level) == "red",
        )
        high_dims = db.query(AuditDimensionResult).filter(dim_filter).all()
        print(f"找到 {len(high_dims)} 条 high/red 维度")

        # 2. 逐条跑形式门槛，只保留 formally_unqualified
        review_records = []
        mapping = {}
        stats = Counter()
        skipped = Counter()

        for dim_row in high_dims:
            pl_id = int(getattr(dim_row, "push_log_id", 0) or 0)
            dim_id = int(getattr(dim_row, "id", 0) or 0)

            # 查 PushLog 获取 audit_type_code
            log = db.query(PushLog).filter(PushLog.id == pl_id).first()
            if not log:
                skipped["no_pushlog"] += 1
                continue
            audit_code = str(log.audit_type_code or "")
            if audit_code not in SIX_CODES:
                skipped["non_six_type"] += 1
                continue

            # 还原 dim dict
            dim_dict = _dim_dict_from_orm(dim_row)

            # 跑形式门槛
            qualified = _qualified_high_risk_issue(dim_dict, audit_code)
            if qualified is not None:
                # formally_qualified — 排除（不在本次范围）
                skipped["formally_qualified"] += 1
                continue

            # formally_unqualified — 纳入候选
            stats["formally_unqualified"] += 1
            stats[f"by_type__{audit_code}"] += 1

            if len(review_records) >= args.max_records:
                stats["capped_at_max"] += 1
                continue

            # 生成 token
            token = secrets.token_hex(16)
            mapping[token] = {
                "push_log_id": pl_id,
                "dimension_id": dim_id,
                "audit_type_code": audit_code,
            }

            # 提取并脱敏证据
            med_raw = dim_dict.get("medical_evidence", [])
            nur_raw = dim_dict.get("nursing_evidence", [])
            med_text = med_raw[0] if med_raw else ""
            nur_text = nur_raw[0] if nur_raw else ""

            med_desensitized = _desensitize(med_text)
            nur_desensitized = _desensitize(nur_text)

            # 提取 issue 级信息
            extra = dim_dict.get("extra", {})
            issues = extra.get("issues", []) if isinstance(extra.get("issues"), list) else []
            issue_info = {}
            if issues:
                first_issue = issues[0] if isinstance(issues[0], dict) else {}
                issue_info = {
                    "has_high_eligible": bool(first_issue.get("high_eligible")),
                    "has_safety_category": str(first_issue.get("safety_category") or ""),
                    "has_evidence_a": bool(first_issue.get("evidence_a")),
                    "has_evidence_b": bool(first_issue.get("evidence_b")),
                    "issue_level": str(first_issue.get("level") or ""),
                }

            review_records.append({
                "review_token": token,
                "audit_type_code": audit_code,
                "dimension_code": dim_dict.get("dimension_code", ""),
                "dimension_name": dim_dict.get("dimension", ""),
                "current_severity": dim_dict.get("severity", ""),
                "current_alert_level": dim_dict.get("alert_level", ""),
                "current_status": dim_dict.get("status", ""),
                "confidence": dim_dict.get("confidence", 0),
                "formally_qualified": False,
                "evidence_side_a_desensitized": med_desensitized,
                "evidence_side_b_desensitized": nur_desensitized,
                "evidence_a_present": bool(med_text.strip()),
                "evidence_b_present": bool(nur_text.strip()),
                "evidence_a_truncated": len(med_text) > MAX_EVIDENCE_CHARS,
                "evidence_b_truncated": len(nur_text) > MAX_EVIDENCE_CHARS,
                "issue_info": issue_info,
                "prompt_sha256": PROMPT_SHA256.get(audit_code, ""),
            })

        # 3. 输出脱敏包
        package_path = output_dir / "stage1_review_package.json"
        mapping_path = output_dir / "stage1_internal_mapping.json"  # 仅院内
        report_path = output_dir / "stage1_report.json"

        package = {
            "version": "1.0",
            "generated_at": datetime.now().isoformat(),
            "total_records": len(review_records),
            "records": review_records,
            "notes": [
                "本包仅含脱敏数据，不含患者标识/完整病历/原始JSON",
                "evidence 已截断到最大200字符并移除数字/科室/日期模式",
                "每条记录附 prompt_sha256 指向对应类型的完整提示词快照",
                "外部AI返回 keep_high/downgrade_medium/downgrade_low/manual_review + reason_code",
                "所有决定仍需本地规则校验 + 临床质控负责人批准后才可写库",
            ],
        }
        with open(package_path, "w", encoding="utf-8") as f:
            json.dump(package, f, ensure_ascii=False, indent=2)

        # 映射文件（仅院内！）
        mapping_data = {
            "INTERNAL_ONLY": True,
            "warning": "此文件含真实数据库ID，不得离开内网/不得放入外部复核包",
            "generated_at": datetime.now().isoformat(),
            "total_mappings": len(mapping),
            "mappings": mapping,
        }
        with open(mapping_path, "w", encoding="utf-8") as f:
            json.dump(mapping_data, f, ensure_ascii=False, indent=2)

        # SHA-256
        pkg_sha = _sha256_file(package_path)
        map_sha = _sha256_file(mapping_path)

        # 报告
        report = {
            "stage": "Stage 1 — 脱敏离线包生成",
            "generated_at": datetime.now().isoformat(),
            "scope": "023 §11.4 formally_unqualified high/red 维度",
            "total_high_red_dims_found": len(high_dims),
            "formally_unqualified": stats["formally_unqualified"],
            "by_audit_type": {k.replace("by_type__", ""): v for k, v in stats.items() if k.startswith("by_type__")},
            "skipped": dict(sorted(skipped.items())),
            "capped_at_max": stats.get("capped_at_max", 0),
            "max_records_setting": args.max_records,
            "output_files": {
                "review_package": {
                    "path": str(package_path),
                    "sha256": pkg_sha,
                    "records": len(review_records),
                },
                "internal_mapping": {
                    "path": str(mapping_path),
                    "sha256": map_sha,
                    "warning": "仅院内保留，不得外发",
                },
            },
            "prompt_snapshots": PROMPT_SHA256,
            "next_step": "外部AI复核 → 本地二次裁决 → 临床质控负责人批准精确token/等级/理由",
            "stop_point": "用户批准该复核包可交给外部AI",
        }
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
