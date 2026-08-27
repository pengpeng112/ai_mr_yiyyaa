# -*- coding: utf-8 -*-
"""隔离红线自动检查（028 §2 隔离边界 / PROMPT §2 验收项）。

检查内容：
1. prearchive_service/ 内所有 .py 不得出现任何 ``import app.*`` / ``from app.*``
   （比提示词给出的 grep 管道更严：任何形式的 app 包导入都算违规）；
2. reminder_agent/ 内不得出现 AppDomainManager / IL 注入相关关键字
   （那是 4.2/4.3，不在一期骨架范围）。

用法：python prearchive_service/check_isolation.py（从仓库根或本目录均可）
退出码 0=通过，1=违规（CI/验收直接依赖）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

IMPORT_APP_RE = re.compile(r"^\s*(?:import\s+app(?:\.|\s|,|$)|from\s+app(?:\.|\s|$))",
                           re.MULTILINE)
FORBIDDEN_CS_KEYWORDS = ("AppDomainManager", "System.Reflection.Emit", "MethodRental",
                         "DefineDynamicAssembly", "SetIL", "ildasm")


def check_python_isolation() -> list:
    violations = []
    for py in sorted(BASE_DIR.rglob("*.py")):
        try:
            text = py.read_text(encoding="utf-8")
        except Exception as exc:
            violations.append(f"{py}: read error {exc}")
            continue
        match = IMPORT_APP_RE.search(text)
        if match:
            line_no = text[:match.start()].count("\n") + 1
            violations.append(f"{py.relative_to(BASE_DIR.parent)}:{line_no}: "
                              f"import app detected: {match.group(0).strip()!r}")
    return violations


def check_agent_keywords() -> list:
    violations = []
    agent_dir = BASE_DIR / "reminder_agent"
    if not agent_dir.exists():
        return violations
    for source in sorted(agent_dir.rglob("*")):
        if source.suffix.lower() not in (".cs", ".config", ".json", ".bat", ".txt"):
            continue
        try:
            text = source.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for keyword in FORBIDDEN_CS_KEYWORDS:
            if keyword.lower() in text.lower():
                violations.append(f"{source.relative_to(BASE_DIR.parent)}: "
                                  f"forbidden keyword {keyword!r} (4.2/4.3 不在一期范围)")
    return violations


def main() -> int:
    violations = check_python_isolation() + check_agent_keywords()
    py_count = len(list(BASE_DIR.rglob("*.py")))
    if violations:
        print("ISOLATION CHECK FAILED:")
        for item in violations:
            print(f"  - {item}")
        return 1
    print(f"ISOLATION CHECK PASSED: scanned {py_count} python files under "
          f"prearchive_service/ — zero `import app.*`; reminder_agent/ clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
