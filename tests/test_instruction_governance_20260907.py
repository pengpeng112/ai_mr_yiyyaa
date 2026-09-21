"""R3 静态断言：指令治理 C1-C5 + 023 §0.6 追加行（043 §4 R3 验收）。

只锁目标子串，不锁全文（防文档正常演进把测试弄脆）。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _index_row(topic: str) -> str:
    for line in _read("docs/INDEX.md").splitlines():
        if line.startswith(f"| {topic} |"):
            return line
    raise AssertionError(f"INDEX 功能状态表缺主题行「{topic}」")


def test_c1_dual_mode_row_dropped_stale_claim():
    row = _index_row("双模式与终末覆盖")
    assert "3 个无转换" not in row, "C1：旧口径「3 个无转换」必须移除"
    assert "EMR 专用出院路径" in row, "C1：新口径必须含「EMR 专用」"
    # 保留后半未完成句（改写稿要求）
    assert "syssvsscbc" in row and "连续观察未完成" in row


def test_c2_claude_commands_section_pointer_only():
    text = _read("CLAUDE.md")
    assert "命令唯一来源" in text and "AGENTS.md" in text, "C2：缺指针句"
    # 围栏内不再完整重复 AGENTS 命令（uvicorn/pytest 全量/docker-compose up 由 AGENTS 承担）
    assert "uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload" not in text
    assert "pytest tests/ -v" not in text
    assert "docker-compose up -d --build" not in text
    # 保留 CLAUDE 独有项
    assert "init_rbac" in text and "docker logs" in text


def test_c3_101_pointer_and_index_row_json_path():
    baseline = _read("docs/reference/101_FEATURE_BASELINE.md")
    assert "docs/reference/gate_anchors.json" in baseline, "C3：101 缺锚指针段"
    assert "禁止手改本节" in baseline
    row_101 = next(
        line for line in _read("docs/INDEX.md").splitlines()
        if line.startswith("| 101 |")
    )
    assert "gate_anchors.json" in row_101, "C3：INDEX 101 行缺 json 路径"


def test_c4_agents_gate_aggregation_line():
    text = _read("AGENTS.md")
    assert "run_gates_20260906.py" in text, "C4：Commands 节缺聚合脚本行"
    # 原有 compileall 行保持原样（不含 prearchive_service，043 §3 裁定 6 明确不改）
    assert "compileall app tests scripts" in text


def test_c5_mutual_pointer_between_00_and_agents():
    rules = _read("开发起步包/00_AI协作规则.md")
    agents = _read("AGENTS.md")
    assert "AGENTS.md" in rules and "语义一致" in rules, "C5：00 §1 缺互指行"
    assert "开发起步包/00_AI协作规则.md" in agents, "C5：AGENTS 会话启动节缺指向 00 的行"


def test_023_section_06_appends_043_row():
    text = _read("docs/ACTIVE/023_SYSTEM_COMPLETION_AND_ONE_SHOT_EXECUTION_PLAN_20260813.md")
    assert "043 跨会话效率治理（2026-09-07 追加）" in text, "023 §0.6 缺 043 追加行"
    # 041 既有行未被重写（append-only）
    assert "041 隔离可用性（2026-09-04 追加）" in text


def test_gate_anchor_json_is_single_machine_source():
    import json

    data = json.loads((ROOT / "docs" / "reference" / "gate_anchors.json").read_text(encoding="utf-8"))
    anchors = data["anchors"]
    assert {"main_pytest", "prearchive_pytest", "frontend_unit", "frontend_e2e", "sidecar_check"} <= set(anchors)
