"""重建不含凭据且默认禁用的正式六类 config.json.template。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))
from app.services.audit_type_contracts import build_safe_template_audit_types


def rebuild(path: Path) -> None:
    config = json.loads(path.read_text(encoding="utf-8"))
    config["audit_types"] = build_safe_template_audit_types()
    for section in ("scheduler", "scheduler_daily", "scheduler_discharge"):
        scheduler = dict(config.get(section) or {})
        scheduler["enabled"] = False
        scheduler["audit_type_codes"] = []
        config[section] = scheduler
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default="config/config.json.template")
    args = parser.parse_args()
    rebuild(Path(args.path).resolve())


if __name__ == "__main__":
    main()
