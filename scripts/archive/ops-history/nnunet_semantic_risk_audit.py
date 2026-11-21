#!/usr/bin/env python3
"""
nnUNet 语义级安全审查脚本
- 聚焦核心模块与训练脚本
- 重点识别反序列化、动态执行、命令注入等高风险模式
- 输出 JSON + Markdown 报告
"""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple


@dataclass
class RiskRule:
    rule_id: str
    title: str
    severity: str
    cwe: str
    description: str
    remediation: str


@dataclass
class Finding:
    rule_id: str
    title: str
    severity: str
    cwe: str
    file: str
    line: int
    code: str
    confidence: str
    description: str
    remediation: str


RULES: Dict[str, RiskRule] = {
    "R001": RiskRule(
        "R001",
        "不安全反序列化：pickle/joblib/dill",
        "critical",
        "CWE-502",
        "检测到 pickle/joblib/dill 反序列化接口，可能触发任意代码执行。",
        "禁止加载不可信输入；优先改为 safetensors/JSON；在边界层做签名校验。",
    ),
    "R002": RiskRule(
        "R002",
        "torch.load 可能触发隐式反序列化",
        "high",
        "CWE-502",
        "torch.load 默认依赖 pickle 语义，加载不可信 checkpoint 存在 RCE 风险。",
        "仅加载可信 checkpoint；优先使用 weights_only=True；配合哈希/签名校验。",
    ),
    "R003": RiskRule(
        "R003",
        "不安全 YAML 反序列化",
        "high",
        "CWE-502",
        "yaml.load 在非安全 Loader 下可能反序列化任意对象。",
        "使用 yaml.safe_load 或显式 SafeLoader。",
    ),
    "R004": RiskRule(
        "R004",
        "动态代码执行 eval/exec",
        "critical",
        "CWE-95",
        "eval/exec 可执行任意字符串代码，若输入可控将导致代码执行。",
        "移除动态执行；改为映射表/受限解析器。",
    ),
    "R005": RiskRule(
        "R005",
        "subprocess shell=True 命令注入风险",
        "high",
        "CWE-78",
        "shell=True 会通过 shell 解释字符串，参数拼接易被注入。",
        "使用参数列表并禁用 shell=True；严格转义/白名单化输入。",
    ),
    "R006": RiskRule(
        "R006",
        "系统命令执行接口",
        "medium",
        "CWE-78",
        "检测到 os.system/os.popen，存在命令注入面。",
        "统一改为 subprocess.run(list, shell=False) 并最小化输入源。",
    ),
    "R007": RiskRule(
        "R007",
        "numpy 允许 pickle 载入",
        "high",
        "CWE-502",
        "np.load(..., allow_pickle=True) 允许反序列化对象。",
        "禁用 allow_pickle 或仅对可信工件启用并做完整性校验。",
    ),
}


def get_call_name(node: ast.Call) -> str:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        chain: List[str] = []
        cur: Any = f
        while isinstance(cur, ast.Attribute):
            chain.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            chain.append(cur.id)
        return ".".join(reversed(chain))
    return "<unknown>"


def get_source_line(lines: List[str], lineno: int) -> str:
    if 1 <= lineno <= len(lines):
        return lines[lineno - 1].strip()
    return ""


def looks_untrusted_arg(call: ast.Call) -> bool:
    suspicious = {
        "input",
        "path",
        "file",
        "filename",
        "checkpoint",
        "ckpt",
        "model",
        "url",
        "argv",
        "cmd",
        "command",
        "payload",
    }

    for arg in call.args:
        if isinstance(arg, ast.Name) and any(k in arg.id.lower() for k in suspicious):
            return True
        if isinstance(arg, ast.Subscript) and isinstance(arg.value, ast.Name):
            n = arg.value.id.lower()
            if n in {"request", "requests", "args", "kwargs", "data"}:
                return True

    for kw in call.keywords:
        if kw.arg and any(k in kw.arg.lower() for k in suspicious):
            return True
        if isinstance(kw.value, ast.Name) and any(k in kw.value.id.lower() for k in suspicious):
            return True

    return False


def classify_file(path: Path) -> str:
    p = str(path).replace("\\", "/").lower()
    if "nnunet" in p and any(x in p for x in ["training", "trainer", "run_training", "train"]):
        return "nnUNet训练脚本"
    if "nnunet" in p:
        return "nnUNet核心模块"
    if any(x in p for x in ["train", "trainer", "run_training"]):
        return "训练相关脚本"
    return "普通模块"


def scan_file(path: Path, root: Path) -> Tuple[List[Finding], str]:
    source = path.read_text(encoding="utf-8", errors="replace")
    lines = source.splitlines()
    findings: List[Finding] = []

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return findings, classify_file(path)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        call_name = get_call_name(node)
        rel = str(path.relative_to(root)).replace("\\", "/")
        line = getattr(node, "lineno", 1)
        code = get_source_line(lines, line)
        untrusted = looks_untrusted_arg(node)
        confidence = "high" if untrusted else "medium"

        def push(rule_key: str, confidence_override: str | None = None):
            rule = RULES[rule_key]
            findings.append(
                Finding(
                    rule_id=rule.rule_id,
                    title=rule.title,
                    severity=rule.severity,
                    cwe=rule.cwe,
                    file=rel,
                    line=line,
                    code=code,
                    confidence=confidence_override or confidence,
                    description=rule.description,
                    remediation=rule.remediation,
                )
            )

        if call_name in {"pickle.load", "pickle.loads", "joblib.load", "dill.load", "dill.loads"}:
            push("R001", "high")

        if call_name == "torch.load":
            has_weights_only = any(kw.arg == "weights_only" and isinstance(kw.value, ast.Constant) and kw.value.value is True for kw in node.keywords)
            if not has_weights_only:
                push("R002", "high" if untrusted else "medium")

        if call_name == "yaml.load":
            safe_loader = False
            for kw in node.keywords:
                if kw.arg == "Loader":
                    text = ast.unparse(kw.value) if hasattr(ast, "unparse") else ""
                    if "SafeLoader" in text:
                        safe_loader = True
            if not safe_loader:
                push("R003", "high")

        if call_name in {"eval", "exec"}:
            push("R004", "high")

        if call_name.startswith("subprocess."):
            for kw in node.keywords:
                if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    push("R005", "high")

        if call_name in {"os.system", "os.popen"}:
            push("R006", "medium")

        if call_name in {"np.load", "numpy.load"}:
            for kw in node.keywords:
                if kw.arg == "allow_pickle" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    push("R007", "high")

    return findings, classify_file(path)


def collect_py_files(target: Path) -> List[Path]:
    return [p for p in target.rglob("*.py") if p.is_file() and "__pycache__" not in str(p)]


def build_markdown_report(
    target: Path,
    scanned_files: int,
    type_stats: Dict[str, int],
    findings: List[Finding],
    started_at: str,
) -> str:
    sev_order = ["critical", "high", "medium", "low"]
    sev_count = {k: 0 for k in sev_order}
    for f in findings:
        sev_count[f.severity] = sev_count.get(f.severity, 0) + 1

    lines: List[str] = []
    lines.append("# nnUNet 语义级安全审查报告")
    lines.append("")
    lines.append(f"- 审查时间: {started_at}")
    lines.append(f"- 审查目标: `{target}`")
    lines.append(f"- 扫描文件数: **{scanned_files}**")
    lines.append(f"- 风险总数: **{len(findings)}**")
    lines.append("")
    lines.append("## 1. 范围识别（核心模块 / 训练脚本）")
    lines.append("")
    for k, v in sorted(type_stats.items(), key=lambda x: x[0]):
        lines.append(f"- {k}: {v}")

    lines.append("")
    lines.append("## 2. 风险统计")
    lines.append("")
    for s in sev_order:
        lines.append(f"- {s.upper()}: {sev_count.get(s, 0)}")

    lines.append("")
    lines.append("## 3. 重点结论")
    lines.append("")
    if not findings:
        lines.append("- 未发现命中规则的高危调用模式。")
        lines.append("- 说明：本扫描基于语义规则与 AST 模式匹配，建议结合运行时链路进一步验证。")
    else:
        top = sorted(findings, key=lambda x: (x.severity, x.confidence), reverse=True)[:8]
        for i, f in enumerate(top, 1):
            lines.append(
                f"{i}. [{f.severity.upper()}] {f.title} | `{f.file}:{f.line}` | 置信度 `{f.confidence}`"
            )

    lines.append("")
    lines.append("## 4. 详细发现")
    lines.append("")

    if not findings:
        lines.append("无。")
    else:
        for idx, f in enumerate(findings, 1):
            lines.append(f"### 4.{idx} {f.title}")
            lines.append(f"- 规则ID: {f.rule_id}")
            lines.append(f"- 严重级别: {f.severity}")
            lines.append(f"- CWE: {f.cwe}")
            lines.append(f"- 位置: `{f.file}:{f.line}`")
            lines.append(f"- 风险描述: {f.description}")
            lines.append(f"- 修复建议: {f.remediation}")
            lines.append("- 代码片段:")
            lines.append("```python")
            lines.append(f.code or "# 无法提取源码行")
            lines.append("```")
            lines.append("")

    lines.append("## 5. 处置优先级建议")
    lines.append("")
    lines.append("1. 优先处理所有反序列化链路（pickle/torch.load/yaml.load）。")
    lines.append("2. 清理动态执行与 shell=True 调用，阻断代码执行入口。")
    lines.append("3. 对模型与配置文件引入完整性校验（哈希/签名）及可信源白名单。")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="nnUNet 语义级安全审查（反序列化重点）")
    parser.add_argument("--target", required=True, help="待审查目录（nnUNet 项目根目录）")
    parser.add_argument("--out", default="audit_reports", help="报告输出目录")
    args = parser.parse_args()

    target = Path(args.target).resolve()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not target.exists() or not target.is_dir():
        raise SystemExit(f"[ERROR] target 不存在或不是目录: {target}")

    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    files = collect_py_files(target)
    all_findings: List[Finding] = []
    type_stats: Dict[str, int] = {}

    for f in files:
        findings, file_type = scan_file(f, target)
        type_stats[file_type] = type_stats.get(file_type, 0) + 1
        all_findings.extend(findings)

    all_findings.sort(key=lambda x: (x.severity, x.confidence, x.file, x.line), reverse=True)

    payload = {
        "meta": {
            "tool": "nnunet_semantic_risk_audit",
            "generated_at": started_at,
            "target": str(target),
            "scanned_files": len(files),
            "risk_count": len(all_findings),
        },
        "scope": type_stats,
        "findings": [asdict(x) for x in all_findings],
    }

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"nnunet_risk_report_{ts}.json"
    md_path = out_dir / f"nnunet_risk_report_{ts}.md"

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_report = build_markdown_report(target, len(files), type_stats, all_findings, started_at)
    md_path.write_text(md_report, encoding="utf-8")

    print("[DONE] 审查完成")
    print(f"- 扫描文件: {len(files)}")
    print(f"- 风险数量: {len(all_findings)}")
    print(f"- JSON报告: {json_path}")
    print(f"- Markdown报告: {md_path}")


if __name__ == "__main__":
    main()
