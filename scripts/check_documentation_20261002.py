"""只读校验文档索引、现役登记、启动导航与原文归档完整性。"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
NAV_FILES = (
    "AGENTS.md", "CLAUDE.md", "README_CN.md", "docs/README.md", "docs/INDEX.md",
    "docs/archive/README.md", "开发起步包/README.md", "开发起步包/00_AI协作规则.md",
    "开发起步包/02_协作任务板.md", "docs/reference/119_MULTI_AI_COLLABORATION_GUIDE.md",
)
DOC_ID = re.compile(r"\d{3}[A-Z]?")
LINK = re.compile(r"\[[^\]\n]*\]\((<[^>\n]+>|[^)\n]+)\)")


def unfenced_lines(text: str):
    """代码示例中的路径不是可点击导航。"""
    fence = None
    for number, line in enumerate(text.splitlines(), 1):
        match = re.match(r"^\s*(`{3,}|~{3,})", line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            continue
        if fence is None:
            yield number, line


def local_path(root: Path, base: Path, value: str) -> Path:
    path = (base / value).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"路径越出仓库: {value}")
    return path


def index_paths(root: Path, text: str) -> tuple[set[Path], list[str]]:
    paths = set()
    errors = []
    section = ""
    ids = set()
    for number, line in unfenced_lines(text):
        if line.startswith("## "):
            section = line
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        doc_id = DOC_ID.fullmatch(cells[0])
        # 编号表记录文件；归档清单记录目录包。文字性历史提及不当作路径。
        if not doc_id and not cells[1].startswith("`archive/"):
            continue
        match = re.fullmatch(r"`([^`]+)`", cells[1])
        if not match:
            errors.append(f"INDEX:{number} 路径列必须是一个完整反引号路径")
            continue
        if doc_id:
            key = (section, cells[0])
            if key in ids:
                errors.append(f"INDEX:{number} 同一分区编号重复: {cells[0]}")
            ids.add(key)
        try:
            path = local_path(root, root / "docs", match.group(1))
            paths.add(path)
            if not path.exists():
                errors.append(f"INDEX:{number} 路径不存在: {match.group(1)}")
            elif doc_id and not path.is_file():
                errors.append(f"INDEX:{number} 编号路径不是文件: {match.group(1)}")
        except ValueError as exc:
            errors.append(f"INDEX:{number} {exc}")
    return paths, errors


def check_links(root: Path, source: Path) -> list[str]:
    errors = []
    for number, line in unfenced_lines(source.read_text(encoding="utf-8")):
        for match in LINK.finditer(line):
            target = match.group(1).strip()
            if target.startswith("<"):
                target = target[1:-1]
            else:
                target = re.split(r'\s+["\']', target, maxsplit=1)[0]
            parts = urlsplit(target)
            if parts.scheme or parts.netloc or not parts.path:
                continue
            try:
                path = local_path(root, source.parent, unquote(parts.path))
                if not path.exists():
                    errors.append(f"{source.relative_to(root)}:{number} 本地链接不存在: {target}")
            except ValueError as exc:
                errors.append(f"{source.relative_to(root)}:{number} {exc}")
    return errors


def check_archive(root: Path, manifest_path: Path, indexed: set[Path]) -> tuple[int, list[str]]:
    errors = []
    count = 0
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("version") != 1:
            raise ValueError("不支持的映射版本")
        entries = manifest.get("entries")
        if not isinstance(entries, list) or not entries:
            raise ValueError("entries必须为非空列表")
        old_seen, new_seen = set(), set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("归档条目必须是对象")
            values = [entry.get(key) for key in ("old_path", "new_path", "successor", "sha256", "id")]
            if any(not isinstance(value, str) or not value for value in values):
                raise ValueError("归档条目字段缺失或类型错误")
            old, new, successor = [local_path(root, root, value) for value in values[:3]]
            sha256, doc_id = values[3:]
            if old.parent != root / "docs/ACTIVE" or new.parent != manifest_path.parent:
                raise ValueError("归档源/目标目录与映射边界不符")
            if old.name != new.name or new.suffix != ".md":
                raise ValueError("归档必须保留Markdown原文件名")
            if not DOC_ID.fullmatch(doc_id) or not new.name.startswith(doc_id + "_"):
                raise ValueError("归档编号与文件名不符")
            if old in old_seen or new in new_seen:
                raise ValueError("归档映射源/目标重复")
            old_seen.add(old)
            new_seen.add(new)
            count += 1
            if old.exists():
                errors.append(f"归档旧路径仍存在: {entry['old_path']}")
            if not new.is_file():
                errors.append(f"归档文件不存在: {entry['new_path']}")
            elif not re.fullmatch(r"[0-9a-f]{64}", sha256) or hashlib.sha256(new.read_bytes()).hexdigest() != sha256:
                errors.append(f"归档原文SHA-256不一致: {entry['new_path']}")
            if new not in indexed:
                errors.append(f"归档新路径未登记INDEX: {entry['new_path']}")
            if successor not in indexed or not successor.is_file():
                errors.append(f"归档承接文档不存在或未登记INDEX: {entry['successor']}")
        for path in manifest_path.parent.glob("*.md"):
            if path.name != "README.md" and path.resolve() not in new_seen:
                errors.append(f"归档Markdown未登记映射: {path.relative_to(root)}")
    except (OSError, UnicodeError, ValueError) as exc:
        errors.append(f"{manifest_path.relative_to(root)}: {exc}")
    return count, errors


def audit_repository(root: Path) -> dict:
    root = root.resolve()
    errors = []
    indexed, managed, archived = set(), set(), 0
    try:
        text = (root / "docs/INDEX.md").read_text(encoding="utf-8")
        indexed, index_errors = index_paths(root, text)
        errors.extend(index_errors)
        if not indexed:
            errors.append("INDEX没有登记路径")
        for directory in ("docs/ACTIVE", "docs/reference", "docs/skills"):
            managed.update((root / directory).rglob("*.md"))
        for path in sorted(managed):
            if path.resolve() not in indexed:
                errors.append(f"现役Markdown未登记INDEX: {path.relative_to(root)}")
        navigation = [root / name for name in NAV_FILES]
        navigation.extend((root / "docs/archive").glob("*/README.md"))
        for path in navigation:
            if not path.is_file():
                errors.append(f"启动/导航文件不存在: {path.relative_to(root)}")
                continue
            errors.extend(check_links(root, path))
        for folder in (root / "docs/archive").glob("completed-plans-*"):
            if folder.is_dir() and not (folder / "archive-manifest.json").is_file():
                errors.append(f"专项归档映射缺失: {folder.relative_to(root)}")
        for manifest_path in sorted((root / "docs/archive").glob("*/archive-manifest.json")):
            count, archive_errors = check_archive(root, manifest_path, indexed)
            archived += count
            errors.extend(archive_errors)
    except (OSError, UnicodeError, ValueError) as exc:
        errors.append(f"文档读取失败: {exc}")
    return {"status": "FAIL" if errors else "PASS", "errors": errors,
            "indexed_paths": len(indexed), "managed_markdown": len(managed),
            "archived_files": archived}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="仓库根目录（默认由脚本位置确定）")
    parser.add_argument("--json", action="store_true", help="只向标准输出打印JSON，不写文件")
    args = parser.parse_args()
    result = audit_repository(args.root)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"文档检查 {result['status']}: INDEX路径={result['indexed_paths']}，"
              f"现役Markdown={result['managed_markdown']}，原文归档={result['archived_files']}")
        for error in result["errors"]:
            print(f"- {error}")
    return int(bool(result["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
