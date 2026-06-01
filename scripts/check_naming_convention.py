"""检查 mr_text / mr_txt 命名约定。

规则：
- builder 输出字典不得出现 ``mr_txt`` key。
- 禁止出现 ``payload["mr_txt"]``、``bundle.mr_txt`` 这类误用。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("app", "tests", "scripts")
SKIP_DIR_NAMES = {"__pycache__", ".pytest_cache", ".git", ".venv", "venv"}
SELF_PATH = Path(__file__).resolve()

CHECK_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "禁止 payload[\"mr_txt\"] 访问",
        re.compile(r"payload\s*\[\s*['\"]mr_txt['\"]\s*\]"),
    ),
    (
        "禁止 bundle.mr_txt 访问",
        re.compile(r"bundle\.mr_txt\b"),
    ),
    (
        "禁止返回含 mr_txt key 的字典",
        re.compile(r"return\s+.*['\"]mr_txt['\"]\s*:\s*"),
    ),
]


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for base in SCAN_DIRS:
        base_path = ROOT / base
        if not base_path.exists():
            continue
        for path in base_path.rglob("*.py"):
            if path.resolve() == SELF_PATH:
                continue
            if any(part in SKIP_DIR_NAMES for part in path.parts):
                continue
            files.append(path)
    files.sort()
    return files


def _check_file(path: Path) -> list[str]:
    issues: list[str] = []
    text = path.read_text(encoding="utf-8", errors="ignore")
    for line_no, line in enumerate(text.splitlines(), start=1):
        for rule_name, pattern in CHECK_PATTERNS:
            if pattern.search(line):
                rel_path = path.relative_to(ROOT)
                issues.append(f"{rel_path}:{line_no} {rule_name} -> {line.strip()}")
    return issues


def main() -> int:
    all_issues: list[str] = []
    for file_path in _iter_python_files():
        all_issues.extend(_check_file(file_path))

    if all_issues:
        print("[FAIL] 命名约定检查失败：发现 mr_txt 误用")
        for issue in all_issues:
            print(f"- {issue}")
        return 1

    print("[PASS] 命名约定检查通过：未发现 mr_txt 误用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
