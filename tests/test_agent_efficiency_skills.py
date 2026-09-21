"""R1 静态契约测试：043 沉淀的 3 个 Skill 的存在性、frontmatter、触发词与红线指针。

只做静态断言（043 §4 R1：仅静态测试，不 subprocess 调脚本）。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / ".agents" / "skills"

# name -> (description 必须包含的触发词, 正文必须引用的红线节名)
SKILL_CONTRACTS = {
    "med-audit-gates": (
        ["门禁", "回归", "交付前", "全绿"],
        ["Commands", "Regression-Sensitive Behavior"],
    ),
    "med-audit-oneshot-delivery": (
        ["一次性执行", "PROMPT-", "作业书", "交付报告"],
        ["会话启动与统一修改记录", "git 提交规范"],
    ),
    "med-audit-demo-stack": (
        ["demo", "隔离", "规则中心", "sidecar"],
        ["Prearchive Service", "隐私红线"],
    ),
}

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> dict[str, str]:
    match = FRONTMATTER_RE.match(text)
    assert match, "缺少 YAML frontmatter（--- ... ---）"
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields


def _read_skill(name: str) -> tuple[dict[str, str], str]:
    path = SKILLS_DIR / name / "SKILL.md"
    assert path.is_file(), f"{path} 不存在"
    text = path.read_text(encoding="utf-8")
    return _parse_frontmatter(text), text


def test_three_skill_files_exist_with_frontmatter():
    for name in SKILL_CONTRACTS:
        fields, _ = _read_skill(name)
        assert fields.get("name") == name, f"{name}: frontmatter name 不匹配"
        assert fields.get("description"), f"{name}: description 为空"


def test_descriptions_contain_trigger_words():
    for name, (triggers, _) in SKILL_CONTRACTS.items():
        fields, _ = _read_skill(name)
        desc = fields["description"]
        for word in triggers:
            assert word in desc, f"{name}: description 缺触发词「{word}」"


def test_skill_bodies_reference_redline_sections():
    for name, (_, redline_refs) in SKILL_CONTRACTS.items():
        _, body = _read_skill(name)
        assert "红线引用" in body, f"{name}: 缺红线引用节"
        for ref in redline_refs:
            assert ref in body, f"{name}: 红线引用缺「{ref}」"


def test_gates_skill_points_to_run_gates_entry_and_anchor():
    _, body = _read_skill("med-audit-gates")
    assert "scripts/run_gates_20260906.py" in body
    assert "--quick" in body and "--full" in body
    assert "gate_anchors.json" in body
    # 失败处置要点：禁止跳过单项 + 以脚本表为准
    assert "禁止跳过单项" in body
    assert "Markdown 门禁表" in body


def test_oneshot_skill_covers_delivery_flow():
    _, body = _read_skill("med-audit-oneshot-delivery")
    assert "review/exec-log.md" in body
    assert "042" in body  # 交付报告结构模板指针
    assert "01_统一修改记录.md" in body
    assert "升级出口" in body


def test_demo_stack_skill_covers_ports_and_known_exemptions():
    _, body = _read_skill("med-audit-demo-stack")
    assert "clean_demo_ports_20260906.py" in body
    assert "4173" in body and "REPORT-ONLY" in body
    assert "RULE_CENTER_SIDECAR=0" in body
    assert "/api/users/me" in body
    assert "18080" in body and "18600" in body
