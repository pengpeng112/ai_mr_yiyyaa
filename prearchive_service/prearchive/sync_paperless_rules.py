# -*- coding: utf-8 -*-
"""规则库同步巡检工具（031 T2-7）：只报告差异，绝不自动写规则/映射表。

对比当前快照（或网关实拉，等 W9）与上次同步基线，检测五类差异：
新增 FID / 停用（FISENABLE 翻转，仅实拉版可测）/ 名称变更 / 分值变更 / 类别变更。

用法::

    python -m prearchive.sync_paperless_rules --snapshot rules/paperless_items_snapshot_20260828.json
    python -m prearchive.sync_paperless_rules --snapshot <当前.json> --baseline <基线.json>

退出码：零差异 0；有差异 1（供巡检挂载）；参数/文件错误 2。
签字硬序（028 §3.3）：差异只提示"需更新 030 映射表对应行"，不修改任何规则文件。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .paperless import load_snapshot_items


def diff_items(current: list, baseline: list) -> dict:
    """五类差异检测：返回 {added, disabled, renamed, rescored, retyped}。

    快照（FISENABLE 恒 1）只能测四类；停用仅实拉版（行含 fisenable=0）可测。
    """
    cur = {int(r["fid"]): r for r in current or []}
    base = {int(r["fid"]): r for r in baseline or []}

    added = sorted(fid for fid in cur if fid not in base)
    disabled = sorted(
        fid for fid, r in cur.items()
        if fid in base and int(base[fid].get("fisenable", 1)) == 1
        and int(r.get("fisenable", 1)) == 0
    )
    renamed = sorted(
        fid for fid in cur if fid in base
        and str(cur[fid].get("fname") or "") != str(base[fid].get("fname") or "")
    )
    rescored = sorted(
        fid for fid in cur if fid in base
        and str(cur[fid].get("fscore") or "") != str(base[fid].get("fscore") or "")
    )
    retyped = sorted(
        fid for fid in cur if fid in base
        and str(cur[fid].get("ftypeid") or "") != str(base[fid].get("ftypeid") or "")
    )
    return {"added": added, "disabled": disabled, "renamed": renamed,
            "rescored": rescored, "retyped": retyped}


def render_markdown(diff: dict, current_count: int, baseline_count: int) -> str:
    lines = [
        "# 无纸化规则库同步差异报告（sync_paperless_rules）",
        "",
        f"- 当前条目数：{current_count}",
        f"- 基线条目数：{baseline_count}",
        "",
    ]
    sections = [
        ("added", "新增 FID", "新评分项——需在 030 映射表补行并走质控科签字流程"),
        ("disabled", "停用（FISENABLE 翻转）", "已停用——对应 030 映射表行需标注停用"),
        ("renamed", "名称变更", "规则名变化——030 映射表对应行需更新"),
        ("rescored", "分值变更", "扣分分值变化——030 严重度分档（FSCORE）需复核"),
        ("retyped", "类别变更", "FTYPEID 变化——A/B/C 分类需复核"),
    ]
    has_diff = any(diff[key] for key, _title, _note in sections)
    if not has_diff:
        lines.append("零差异：当前快照与基线一致。")
        return "\n".join(lines) + "\n"
    for key, title, note in sections:
        fids = diff.get(key) or []
        lines.append(f"## {title}（{len(fids)}）")
        if not fids:
            lines.append("- 无")
        else:
            lines.append(f"- FID：{', '.join(str(f) for f in fids)}")
            lines.append(f"- 影响：{note}（涉及 FID 需更新 030 映射表对应行）")
        lines.append("")
    lines.append("> 签字硬序：本工具只报告不写规则；正式规则仍待质控科签字版回填。")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="无纸化规则库五差异巡检（只报告）")
    parser.add_argument("--snapshot", required=True,
                        help="当前快照/实拉 JSON（items 数组或带 _meta 的对象）")
    parser.add_argument("--baseline",
                        help="上次同步基线 JSON；缺省=与自身对比（自洽冒烟）")
    parser.add_argument("--output", help="差异报告输出路径（缺省打印 stdout）")
    args = parser.parse_args(argv)

    try:
        current = load_snapshot_items(args.snapshot)
        baseline = (load_snapshot_items(args.baseline) if args.baseline
                    else [dict(r) for r in current])
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"[sync] input error: {exc}", file=sys.stderr)
        return 2

    diff = diff_items(current, baseline)
    report = render_markdown(diff, len(current), len(baseline))
    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"[sync] report written: {args.output}")
    else:
        print(report)

    has_diff = any(diff.values())
    return 1 if has_diff else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
