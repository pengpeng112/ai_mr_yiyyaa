"""Stage 1.5 — Dify workflow 影子回放复核。

对 Stage 1 脱敏包中的 461 条候选（排除6条空证据），
逐条将脱敏证据格式化为病历格式，发送给 Dify workflow 重新判定。
对比历史 high 分类，输出 AI 复核决定。

安全边界：
- 只发送脱敏证据（已移除患者标识/数字/日期/科室）
- 数据在内网 Dify → Qwen3-30B 闭环，不出院
- 不写生产数据库
- 输出 token + 决定，不含原始证据
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

try:
    REPO_ROOT = Path(__file__).resolve().parents[4]
except IndexError:
    REPO_ROOT = Path("/app")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import requests
from app.config import load_config
from app.services.config_parser import ConfigParser


# 按审计类型格式化证据为病历文本
def format_evidence(audit_code: str, evidence_a: str, evidence_b: str, dim_name: str) -> str:
    """把脱敏证据格式化成对应类型的病历格式。"""
    # 通用格式：两侧证据 + 维度上下文
    if audit_code == "admission_vs_first_progress":
        return f"【入院记录】\n{evidence_a}\n\n【首次病程记录】\n{evidence_b}"
    elif audit_code == "discharge_vs_frontpage":
        return f"【首次病程记录】\n{evidence_a}\n\n【出院记录】\n{evidence_b}"
    elif audit_code == "surgery_chain":
        return f"【术前记录】\n{evidence_a}\n\n【术后首次病程记录】\n{evidence_b}"
    elif audit_code == "progress_vs_nursing":
        return f"【病程记录】\n{evidence_a}\n\n【护理记录】\n{evidence_b}"
    elif audit_code == "jyjc_vs_bcnursing":
        return f"【检验检查结果】\n{evidence_a}\n\n【病程与护理记录】\n{evidence_b}"
    else:
        return f"【文书A】\n{evidence_a}\n\n【文书B】\n{evidence_b}"


MR_TYPE_MAP = {
    "admission_vs_first_progress": "入院与首次病程核查",
    "discharge_vs_frontpage": "出院与首次病程核查",
    "surgery_chain": "围手术期核查",
    "progress_vs_nursing": "病程与护理核查",
    "jyjc_vs_bcnursing": "检验检查与病程护理核查",
    "syssvsscbc": "首页手术与首次病程",
}


def call_dify_workflow(base_url: str, api_key: str, mr_txt: str, audit_code: str, timeout: int = 90) -> dict:
    """调用 Dify workflow API。"""
    url = f"{base_url.rstrip('/')}/workflows/run"
    mr_type = MR_TYPE_MAP.get(audit_code, "")
    inputs = {"mr_txt": mr_txt}
    if mr_type:
        inputs["mr_type"] = mr_type
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "inputs": inputs,
            "response_mode": "blocking",
            "user": "remediation-shadow-review",
        },
        timeout=timeout,
    )
    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}", "detail": resp.text[:200]}
    return resp.json()


def parse_workflow_result(data: dict, output_key: str) -> dict:
    """从 Dify 返回中提取质控结果。"""
    outputs = data.get("data", {}).get("outputs", {})
    raw = outputs.get(output_key, "")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {"raw_text": raw[:500]}
    elif isinstance(raw, dict):
        return raw
    return {"raw": str(raw)[:500]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 1.5: Dify 影子回放复核")
    parser.add_argument("--apply", action="store_true", help="始终拒绝")
    parser.add_argument("--input", default="/tmp/stage1_review/stage1_review_package.json")
    parser.add_argument("--output", default="/tmp/stage1_review/stage1_5_shadow_results.json")
    parser.add_argument("--max-records", type=int, default=500)
    parser.add_argument("--delay-seconds", type=float, default=0.5, help="每次调用间隔")
    args = parser.parse_args()
    if args.apply:
        parser.error("禁止 --apply")

    # 加载配置
    config = load_config()
    dify = ConfigParser.parse_dify_config(config)
    base_url = dify.get("base_url", "")
    api_key = dify.get("api_key", "")
    output_key = dify.get("workflow_output_key", "aa")
    print(f"Dify: {base_url}, output_key={output_key}")

    # 加载脱敏包
    with open(args.input, "r", encoding="utf-8") as f:
        package = json.load(f)
    records = package.get("records", [])

    # 过滤空证据
    valid = [r for r in records if r.get("evidence_a_present") or r.get("evidence_b_present")]
    skipped_empty = len(records) - len(valid)
    print(f"总记录: {len(records)}, 排除空证据: {skipped_empty}, 有效: {len(valid)}")

    if args.max_records > 0:
        valid = valid[:args.max_records]
        print(f"限制处理: {len(valid)} 条")

    # 逐条回放
    results = []
    stats = Counter()
    errors = Counter()

    for i, rec in enumerate(valid):
        token = rec["review_token"]
        audit_code = rec["audit_type_code"]
        ev_a = rec.get("evidence_side_a_desensitized", "")
        ev_b = rec.get("evidence_side_b_desensitized", "")

        # 格式化为病历文本
        mr_txt = format_evidence(audit_code, ev_a, ev_b, rec.get("dimension_name", ""))

        # 调用 Dify
        try:
            wf_result = call_dify_workflow(base_url, api_key, mr_txt, audit_code)
            if "error" in wf_result:
                errors["dify_api_error"] += 1
                results.append({
                    "review_token": token,
                    "audit_type_code": audit_code,
                    "dimension_code": rec.get("dimension_code", ""),
                    "shadow_status": "api_error",
                    "error": wf_result.get("detail", "")[:200],
                })
                continue

            parsed = parse_workflow_result(wf_result, output_key)

            # 从结果中提取严重度/状态
            shadow_severity = ""
            shadow_alert = ""
            shadow_dims = []

            # 尝试从 audit_summary 提取
            summary = parsed.get("audit_summary", {}) if isinstance(parsed, dict) else {}
            shadow_severity = str(summary.get("severity", "")).lower()
            shadow_alert = str(summary.get("alert_level", "")).lower()

            # 尝试从 dimensions 提取对应维度
            dims = parsed.get("dimensions", []) if isinstance(parsed, dict) else []
            target_code = rec.get("dimension_code", "")
            for dim in dims:
                if isinstance(dim, dict):
                    dc = str(dim.get("dimension_code", ""))
                    if dc == target_code or not target_code:
                        shadow_dims.append({
                            "dimension_code": dc,
                            "status": str(dim.get("status", "")),
                            "severity": str(dim.get("severity", "")).lower(),
                            "alert_level": str(dim.get("alert_level", "")).lower(),
                        })

            # 决定
            is_high = shadow_severity == "high" or shadow_alert == "red"
            any_dim_high = any(d.get("severity") == "high" or d.get("alert_level") == "red" for d in shadow_dims)

            if is_high or any_dim_high:
                decision = "keep_high"
                stats["keep_high"] += 1
            elif shadow_severity == "medium" or shadow_alert == "yellow":
                decision = "downgrade_medium"
                stats["downgrade_medium"] += 1
            elif parsed.get("raw_text") or parsed.get("raw"):
                decision = "manual_review"
                stats["manual_review_parse_issue"] += 1
            else:
                decision = "downgrade_low"
                stats["downgrade_low"] += 1

            results.append({
                "review_token": token,
                "audit_type_code": audit_code,
                "dimension_code": target_code,
                "historical_severity": rec.get("current_severity", ""),
                "shadow_severity": shadow_severity,
                "shadow_alert_level": shadow_alert,
                "shadow_dimensions": shadow_dims[:3],
                "shadow_decision": decision,
            })

        except Exception as exc:
            errors[type(exc).__name__] += 1
            results.append({
                "review_token": token,
                "audit_type_code": audit_code,
                "dimension_code": rec.get("dimension_code", ""),
                "shadow_status": "exception",
                "error": str(exc)[:200],
            })

        # 进度
        if (i + 1) % 50 == 0:
            print(f"  进度: {i+1}/{len(valid)}, keep_high={stats['keep_high']}, downgrade={stats['downgrade_medium']+stats['downgrade_low']}, manual={stats['manual_review_parse_issue']}")

        if args.delay_seconds > 0:
            time.sleep(args.delay_seconds)

    # 输出
    output = {
        "stage": "Stage 1.5 — Dify 影子回放复核",
        "generated_at": datetime.now().isoformat(),
        "total_input": len(records),
        "skipped_empty_evidence": skipped_empty,
        "total_reviewed": len(valid),
        "decisions": dict(sorted(stats.items())),
        "errors": dict(sorted(errors.items())),
        "results": results,
        "note": "此结果仍需 Stage 2 本地二次裁决（后端门槛+语义shadow+提示词规则）+ 临床批准",
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    sha = hashlib.sha256()
    with open(args.output, "rb") as f:
        sha.update(f.read())

    print(f"\n=== Stage 1.5 完成 ===")
    print(f"输出: {args.output}")
    print(f"SHA-256: {sha.hexdigest().upper()}")
    print(f"总计: {len(valid)} 条")
    print(f"决定分布: {dict(sorted(stats.items()))}")
    if errors:
        print(f"错误: {dict(sorted(errors.items()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
