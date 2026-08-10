#!/usr/bin/env python3
"""本地 /ui-next/ 与菜单契约冒烟（不连生产、不触发推送）。

用法（服务已在 8000 监听时）:
  python scripts/smoke_ui_next_local.py
  python scripts/smoke_ui_next_local.py --base http://127.0.0.1:8000 --user admin --password ...
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def _req(url: str, method: str = "GET", data: dict | None = None, token: str | None = None):
    body = None
    headers = {"Accept": "application/json"}
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as resp:
            raw = resp.read()
            ctype = resp.headers.get("Content-Type", "")
            if "application/json" in ctype:
                return resp.status, json.loads(raw.decode("utf-8") or "null")
            return resp.status, raw.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw.decode("utf-8") or "null")
        except Exception:
            payload = raw.decode("utf-8", errors="replace")
        return exc.code, payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--user", default="admin")
    parser.add_argument("--password", default="")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    failures: list[str] = []

    code, live = _req(f"{base}/api/health/live")
    print(f"health/live: {code} {live}")
    if code != 200:
        failures.append("health/live")

    code, html = _req(f"{base}/ui-next/")
    print(f"ui-next/: {code} bytes={len(html) if isinstance(html, str) else 'n/a'}")
    if code != 200 or not isinstance(html, str) or "Med-Audit" not in html:
        failures.append("ui-next index")
    if isinstance(html, str) and "/ui-next/assets/" not in html:
        failures.append("ui-next asset base")

    code, legacy = _req(f"{base}/")
    print(f"legacy /: {code}")
    if code != 200:
        failures.append("legacy /")

    code, _ = _req(f"{base}/api/menu")
    print(f"menu unauth: {code}")
    if code not in (401, 403):
        failures.append("menu should require auth")

    if args.password:
        code, login = _req(
            f"{base}/api/users/login",
            method="POST",
            data={"username": args.user, "password": args.password},
        )
        print(f"login: {code}")
        if code != 200 or not isinstance(login, dict) or not login.get("access_token"):
            failures.append("login")
        else:
            token = str(login["access_token"])
            code, menu = _req(f"{base}/api/menu", token=token)
            print(f"menu auth: {code}")
            if code != 200 or not isinstance(menu, dict):
                failures.append("menu auth")
            else:
                print(
                    "menu meta:",
                    {
                        "schema_version": menu.get("schema_version"),
                        "role": menu.get("role"),
                        "count": len(menu.get("menu") or []),
                        "groups": len(menu.get("groups") or []),
                    },
                )
                ids = {item.get("id") for item in (menu.get("menu") or [])}
                if "oracle-status" in ids or "system-logs" in ids:
                    failures.append("placeholders visible")
                if len(menu.get("groups") or []) > 6:
                    failures.append("too many groups")
                if menu.get("schema_version") != 2:
                    failures.append("schema_version != 2")

    if failures:
        print("FAIL:", ", ".join(failures))
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
