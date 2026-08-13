"""WP6 本地只读：route-manifest × 四角色菜单矩阵与关键契约检查。

不连接生产；不需要 CANARY 凭证。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.routers.menu import (  # noqa: E402
    MENU_CATALOG,
    MENU_CONFIG,
    ROLE_DEFAULT_HOME,
    build_menu_response,
)


def load_manifest_ids() -> list[str]:
    text = (ROOT / "frontend/src/router/route-manifest.ts").read_text(encoding="utf-8")
    return re.findall(r"menuId:\s*'([^']+)'", text)


def load_manifest_meta() -> dict[str, dict]:
    text = (ROOT / "frontend/src/router/route-manifest.ts").read_text(encoding="utf-8")
    # crude block parse per entry
    blocks = re.split(r"\{\s*menuId:", text)[1:]
    out: dict[str, dict] = {}
    for block in blocks:
        menu_id = re.match(r"\s*'([^']+)'", block)
        if not menu_id:
            continue
        mid = menu_id.group(1)
        name = re.search(r"name:\s*'([^']+)'", block)
        path = re.search(r"path:\s*'([^']+)'", block)
        risk = re.search(r"risk:\s*'([^']+)'", block)
        mut = re.search(r"mutationsEnabled:\s*(true|false)", block)
        keep = re.search(r"keepAlive:\s*(true|false)", block)
        out[mid] = {
            "name": name.group(1) if name else "",
            "path": path.group(1) if path else "",
            "risk": risk.group(1) if risk else "",
            "mutationsEnabled": (mut.group(1) == "true") if mut else None,
            "keepAlive": (keep.group(1) == "true") if keep else False,
        }
    return out


def patient_qc_auth_summary() -> dict:
    src = (ROOT / "app/routers/patient_qc.py").read_text(encoding="utf-8")
    return {
        "require_role_admin": len(re.findall(r"require_role\([\"']admin[\"']\)", src)),
        "view_reports": len(re.findall(r"require_permission\([\"']view_reports[\"']\)", src)),
        "export_reports": len(re.findall(r"require_permission\([\"']export_reports[\"']\)", src)),
        "has_dept_visibility": "visible_dept_names" in src and "apply_push_log_visibility" in src,
    }


def main() -> int:
    manifest_ids = load_manifest_ids()
    meta = load_manifest_meta()
    catalog_ids = [i["id"] for i in MENU_CATALOG]
    hidden = [i["id"] for i in MENU_CATALOG if i.get("hidden")]
    dev_only = [i["id"] for i in MENU_CATALOG if i.get("dev_only")]

    print("=== ROUTE MANIFEST ===")
    print(f"count={len(manifest_ids)}")
    for mid in manifest_ids:
        m = meta.get(mid, {})
        print(
            f"  {mid:20} path=/{m.get('path','')} risk={m.get('risk','')} "
            f"keepAlive={m.get('keepAlive')} mutations={m.get('mutationsEnabled')}"
        )

    print("\n=== CATALOG vs MANIFEST ===")
    print(f"catalog={len(catalog_ids)} hidden={hidden} dev_only={dev_only}")
    only_m = set(manifest_ids) - set(catalog_ids)
    nav_not_m = {i["id"] for i in MENU_CATALOG if not i.get("hidden")} - set(manifest_ids)
    print(f"only_manifest={sorted(only_m)}")
    print(f"nav_catalog_not_in_manifest={sorted(nav_not_m)}")

    print("\n=== ROLE x MENU (production filter, intersect manifest) ===")
    roles = ["admin", "dept_manager", "auditor", "clinician"]
    matrix: dict[str, dict[str, str]] = {mid: {} for mid in manifest_ids}

    for role in roles:
        mids = MENU_CONFIG.get(role, [])
        resp = build_menu_response(mids, role, production=True)
        nav_ids = [m["id"] for m in resp["menu"]]
        allowed = [i for i in nav_ids if i in manifest_ids]
        unknown = [i for i in nav_ids if i not in manifest_ids]
        print(
            f"ROLE {role:14} default_home={resp.get('default_home')} "
            f"nav_count={len(allowed)} unknown={unknown}"
        )
        print(f"  menus={allowed}")
        for mid in manifest_ids:
            if mid in allowed:
                matrix[mid][role] = "MENU_OK"
            else:
                matrix[mid][role] = "NO_MENU"

    print("\n=== MATRIX CSV (menu_id,path,risk,admin,dept_manager,auditor,clinician) ===")
    print("menu_id,path,risk,admin,dept_manager,auditor,clinician,notes")
    for mid in manifest_ids:
        m = meta.get(mid, {})
        row = [mid, "/" + m.get("path", ""), m.get("risk", "")]
        for role in roles:
            row.append(matrix[mid].get(role, "NO_MENU"))
        notes = []
        if mid == "debug":
            notes.append("production filters dev_only")
        if mid == "patient-qc":
            notes.append("list/detail=view_reports+dept_scope; export=export_reports")
        print(",".join(str(x) for x in row) + "," + ";".join(notes))

    print("\n=== STATIC DEFECT SIGNALS ===")
    auth = patient_qc_auth_summary()
    print(f"patient_qc auth={auth}")
    print("ROLE_DEFAULT_HOME", ROLE_DEFAULT_HOME)

    # Auditor write expectation: menu risk flags
    print("\n=== AUDITOR WRITE SURFACE (menu only) ===")
    for mid in manifest_ids:
        if matrix[mid].get("auditor") == "MENU_OK":
            print(f"  auditor can open {mid} risk={meta.get(mid,{}).get('risk')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
