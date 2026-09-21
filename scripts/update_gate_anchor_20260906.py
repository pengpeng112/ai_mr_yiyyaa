"""043 R2 锚更新脚本：读 run_gates 结果 JSON → 只更新 docs/reference/gate_anchors.json。

- 幂等：锚值无变化时不重写文件（跑两次 json 一致）；
- 带时间戳 updated_at；**不改 101/INDEX 等任何文档**（043 §3 裁定 5）。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ANCHOR_FILE = ROOT / "docs" / "reference" / "gate_anchors.json"

COUNT_GATES = ("main_pytest", "prearchive_pytest", "frontend_unit", "frontend_e2e")


def build_anchors_from_result(result: dict) -> dict:
    """从 run_gates result.json 的 results 节提取锚值（只收 PASS 门禁，FAIL/SKIPPED 不入锚）。"""
    gates = result.get("results", {})
    anchors: dict = {}
    for name in COUNT_GATES:
        gate = gates.get(name)
        if not gate or gate.get("status") != "PASS":
            continue
        counts = gate.get("counts", {})
        anchors[name] = {
            "passed": int(counts.get("passed", 0)),
            "skipped": int(counts.get("skipped", 0)),
        }
    if gates.get("sidecar_check", {}).get("status") == "PASS":
        anchors["sidecar_check"] = {"status": "PASS"}
    return anchors


def update_anchor_file(result_path: Path, anchor_path: Path) -> int:
    """返回 0=已更新/无需更新；2=输入错误。幂等：无变化不重写。"""
    if not result_path.exists():
        print(f"[update_gate_anchor] 结果文件不存在: {result_path}")
        return 2
    result = json.loads(result_path.read_text(encoding="utf-8"))
    new_anchors = build_anchors_from_result(result)
    if not new_anchors:
        print("[update_gate_anchor] 结果中没有可入锚的 PASS 门禁（main/prearchive/unit/e2e/sidecar）")
        return 2

    existing: dict = {}
    if anchor_path.exists():
        existing = json.loads(anchor_path.read_text(encoding="utf-8")).get("anchors", {})

    if existing == new_anchors:
        print(f"[update_gate_anchor] 锚值无变化，文件保持不动（幂等）: {anchor_path}")
        return 0

    payload = {
        "version": 1,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "source": f"run_gates result: {result_path.name}",
        "anchors": new_anchors,
    }
    anchor_path.parent.mkdir(parents=True, exist_ok=True)
    anchor_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[update_gate_anchor] 已更新 {anchor_path}（旧 {len(existing)} 项 → 新 {len(new_anchors)} 项）")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="043 更新门禁锚（只写 gate_anchors.json，不碰 101）")
    parser.add_argument("result_json", type=Path, help="run_gates 产物 result.json 路径")
    parser.add_argument("--anchor-file", type=Path, default=DEFAULT_ANCHOR_FILE)
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return update_anchor_file(args.result_json, args.anchor_file)


if __name__ == "__main__":
    sys.exit(main())
