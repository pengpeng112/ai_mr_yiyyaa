from pathlib import Path


_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_DASHBOARD_JS = _STATIC_DIR / "scripts" / "modules" / "dashboard.js"


def _extract_method_body(js: str, method_name: str) -> str:
    marker = f"{method_name}("
    start = js.find(marker)
    assert start != -1, f"{method_name} method not found"
    body_start = js.find("{", start)
    assert body_start != -1, f"{method_name} body not found"
    depth = 0
    for pos in range(body_start, len(js)):
        ch = js[pos]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return js[body_start : pos + 1]
    raise AssertionError(f"{method_name} body is not balanced")


def test_dashboard_dimension_label_does_not_read_underscore_proxy_state():
    js = _DASHBOARD_JS.read_text(encoding="utf-8")
    body = _extract_method_body(js, "_dimName")

    assert "this._dimZhMap" not in body
    assert "dimZhMap[name]" in body
