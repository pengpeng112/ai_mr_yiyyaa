"""文档治理故障场景：断链、漏登记、越界、篡改与归档映射漂移。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.check_documentation_20261002 import (
    NAV_FILES, audit_repository, check_links, index_paths,
)


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    for name in NAV_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# 入口\n", encoding="utf-8")
    (tmp_path / "docs/ACTIVE").mkdir()
    (tmp_path / "docs/ACTIVE/001_current.md").write_text("# 当前\n", encoding="utf-8")
    (tmp_path / "docs/INDEX.md").write_text(
        "## 现役\n| 编号 | 路径 | 状态 |\n"
        "| --- | --- | --- |\n| 001 | `ACTIVE/001_current.md` | 现役 |\n"
        "| 119 | `reference/119_MULTI_AI_COLLABORATION_GUIDE.md` | 现役 |\n",
        encoding="utf-8",
    )
    return tmp_path


def append_index(root: Path, row: str):
    with (root / "docs/INDEX.md").open("a", encoding="utf-8") as stream:
        stream.write(row + "\n")


def archive(root: Path) -> tuple[Path, Path]:
    folder = root / "docs/archive/completed-plans-test-20261002"
    folder.mkdir()
    target = folder / "002_old.md"
    # CRLF与非ASCII字节须完整保留。
    content = "# 已完成\r\n原文\r\n".encode("utf-8")
    target.write_bytes(content)
    manifest = folder / "archive-manifest.json"
    manifest.write_text(json.dumps({"version": 1, "entries": [{
        "id": "002", "old_path": "docs/ACTIVE/002_old.md",
        "new_path": "docs/archive/completed-plans-test-20261002/002_old.md",
        "successor": "docs/ACTIVE/001_current.md",
        "sha256": hashlib.sha256(content).hexdigest(),
    }]}), encoding="utf-8")
    append_index(root, "| 002 | `archive/completed-plans-test-20261002/002_old.md` | 已归档 |")
    return target, manifest


def test_valid_repository_and_archive_are_read_only(repository):
    archive(repository)
    before = {p: p.read_bytes() for p in repository.rglob("*") if p.is_file()}
    result = audit_repository(repository)
    assert result["status"] == "PASS", result
    assert result["archived_files"] == 1
    assert before == {p: p.read_bytes() for p in repository.rglob("*") if p.is_file()}


@pytest.mark.parametrize("failure,expected", [
    ("missing_indexed", "路径不存在"),
    ("unregistered", "未登记INDEX"),
    ("broken_link", "本地链接不存在"),
    ("outside", "路径越出仓库"),
    ("duplicate_id", "编号重复"),
])
def test_navigation_failures(repository, failure, expected):
    if failure == "missing_indexed":
        (repository / "docs/ACTIVE/001_current.md").unlink()
    elif failure == "unregistered":
        (repository / "docs/ACTIVE/003_new.md").write_text("# 未登记", encoding="utf-8")
    elif failure == "broken_link":
        (repository / "AGENTS.md").write_text("[断链](missing.md)", encoding="utf-8")
    elif failure == "outside":
        append_index(repository, "| 003 | `../../outside.md` | 参考 |")
    else:
        append_index(repository, "| 001 | `ACTIVE/001_current.md` | 重复 |")
    result = audit_repository(repository)
    assert result["status"] == "FAIL"
    assert any(expected in message for message in result["errors"])


@pytest.mark.parametrize("failure,expected", [
    ("tamper", "SHA-256不一致"),
    ("revived", "旧路径仍存在"),
    ("successor", "承接文档不存在"),
    ("duplicate", "映射源/目标重复"),
    ("malformed", "entries必须"),
    ("outside", "路径越出仓库"),
    ("unmapped", "未登记映射"),
    ("missing_manifest", "映射缺失"),
    ("missing_target", "归档文件不存在"),
    ("unindexed", "新路径未登记INDEX"),
])
def test_archive_failures(repository, failure, expected):
    target, manifest_path = archive(repository)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if failure == "tamper":
        target.write_text("改写历史", encoding="utf-8")
    elif failure == "revived":
        (repository / "docs/ACTIVE/002_old.md").write_text("旧源复活", encoding="utf-8")
    elif failure == "successor":
        data["entries"][0]["successor"] = "docs/ACTIVE/999_missing.md"
    elif failure == "duplicate":
        data["entries"].append(data["entries"][0].copy())
    elif failure == "malformed":
        data["entries"] = "不是列表"
    elif failure == "outside":
        data["entries"][0]["new_path"] = "../outside.md"
    elif failure == "unmapped":
        (target.parent / "003_unmapped.md").write_text("没有映射", encoding="utf-8")
    elif failure == "missing_target":
        target.unlink()
    elif failure == "unindexed":
        index = repository / "docs/INDEX.md"
        text = index.read_text(encoding="utf-8")
        index.write_text("\n".join(line for line in text.splitlines() if not line.startswith("| 002 |")), encoding="utf-8")
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    if failure == "missing_manifest":
        manifest_path.unlink()
    result = audit_repository(repository)
    assert result["status"] == "FAIL"
    assert any(expected in message for message in result["errors"])


def test_links_support_chinese_spaces_fragments_and_code_examples(repository):
    (repository / "开发起步包/含 空格.md").write_text("# 节", encoding="utf-8")
    source = repository / "AGENTS.md"
    source.write_text(
        "[中文](<开发起步包/含 空格.md#节>)\n[编码](开发起步包/%E5%90%AB%20%E7%A9%BA%E6%A0%BC.md)\n"
        "[外部](https://example.invalid/missing)\n[锚](#节)\n"
        "```text\n[示例](does-not-exist.md)\n```\n", encoding="utf-8",
    )
    assert check_links(repository.resolve(), source) == []


def test_duplicate_legacy_ids_are_scoped_by_index_section(repository):
    append_index(repository, "## 历史补充\n| 001 | `ACTIVE/001_current.md` | 历史编号 |")
    _, errors = index_paths(repository.resolve(), (repository / "docs/INDEX.md").read_text(encoding="utf-8"))
    assert errors == []
