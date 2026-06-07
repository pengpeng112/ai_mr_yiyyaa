"""
Frontend static tests for runtime-summary — Phase 3.1.5 hardening.

Verifies that the frontend runtime-summary section does NOT leak
sensitive field names or SQL, and that loadRuntimeSummary() is read-only.

These tests read static files directly; no server, no DB, no network.
"""

from __future__ import annotations

import re
from pathlib import Path

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_CONFIG_HTML = _STATIC_DIR / "templates" / "pages" / "config.html"
_CONFIG_JS = _STATIC_DIR / "scripts" / "modules" / "config.js"

_FORBIDDEN_KEYS = (
    "query_sql",
    "field_mapping",
    "api_key",
    "api_key_enc",
    "password",
    "password_enc",
    "secret_key",
    "secret_key_enc",
)

_ALLOWED_BOOL_KEYS = ("has_api_key", "has_query_sql")


# ---- helpers ----------------------------------------------------------------


def _extract_runtime_section(html: str) -> str:
    """Extract the runtime-summary DISPLAY section from config.html (not the tab pane)."""
    # The display section contains cfg-runtime, which is unique to the display area
    marker = "cfg-runtime"
    start = html.find(marker)
    if start == -1:
        return ""
    # find the <section tag that contains this marker
    section_start = html.rfind("<section", 0, start)
    if section_start == -1:
        return ""
    # find matching </section> — count nested sections
    depth = 0
    pos = section_start
    while True:
        next_open = html.find("<section", pos + 1)
        next_close = html.find("</section>", pos + 1)
        if next_close == -1:
            return ""
        if next_open != -1 and next_open < next_close:
            depth += 1
            pos = next_open
        else:
            if depth == 0:
                return html[section_start:next_close + len("</section>")]
            depth -= 1
            pos = next_close


def _has_forbidden_key(text: str, forbidden: str) -> bool:
    """Check if a forbidden key appears as a Vue binding/prop (not in has_* context)."""
    # Skip false positives from has_xxx booleans
    for allowed in _ALLOWED_BOOL_KEYS:
        text = text.replace(allowed, "__ALLOWED__")
    return forbidden in text


# ---- tests ------------------------------------------------------------------


class TestConfigHtmlStructure:
    def test_contains_runtime_summary_tab(self):
        html = _CONFIG_HTML.read_text(encoding="utf-8")
        assert 'name="runtime-summary"' in html
        assert "运行总览" in html

    def test_contains_runtime_summary_section(self):
        html = _CONFIG_HTML.read_text(encoding="utf-8")
        section = _extract_runtime_section(html)
        assert section, "runtime-summary section not found in config.html"

    def test_runtime_section_has_loader_ref(self):
        html = _CONFIG_HTML.read_text(encoding="utf-8")
        section = _extract_runtime_section(html)
        assert "loadRuntimeSummary" in section or "runtimeSummaryLoading" in section

    def test_runtime_section_no_save_button(self):
        html = _CONFIG_HTML.read_text(encoding="utf-8")
        section = _extract_runtime_section(html)
        assert "保存配置" not in section
        assert "保存" not in section

    def test_runtime_section_no_forbidden_sql_keys(self):
        html = _CONFIG_HTML.read_text(encoding="utf-8")
        section = _extract_runtime_section(html)
        assert not _has_forbidden_key(section, "query_sql"), "query_sql found in runtime-summary section"
        assert not _has_forbidden_key(section, "field_mapping"), "field_mapping found in runtime-summary section"

    def test_runtime_section_no_forbidden_secret_keys(self):
        html = _CONFIG_HTML.read_text(encoding="utf-8")
        section = _extract_runtime_section(html)
        for fk in ("api_key", "api_key_enc", "password", "password_enc", "secret_key", "secret_key_enc"):
            assert not _has_forbidden_key(section, fk), f"{fk} found in runtime-summary section"

    def test_runtime_section_allows_has_bool_keys(self):
        html = _CONFIG_HTML.read_text(encoding="utf-8")
        section = _extract_runtime_section(html)
        # has_api_key is allowed: displayed as dify_target?.has_api_key
        assert "has_api_key" in section, "has_api_key should appear (allowed bool)"
        # has_query_sql is in sources[] which may not be directly displayed in table;
        # it is permitted. The key check is that the section does NOT contain bare
        # query_sql, which is verified by test_runtime_section_no_forbidden_sql_keys.

    def test_runtime_section_no_loading_icon_dependency(self):
        html = _CONFIG_HTML.read_text(encoding="utf-8")
        section = _extract_runtime_section(html)
        assert "<Loading />" not in section
        assert "rt-loading-spinner" in section


class TestConfigJsReadOnly:
    def test_load_runtime_summary_exists(self):
        js = _CONFIG_JS.read_text(encoding="utf-8")
        assert "loadRuntimeSummary" in js

    def test_load_runtime_summary_only_uses_api_get(self):
        js = _CONFIG_JS.read_text(encoding="utf-8")
        # Find the loadRuntimeSummary function body
        start = js.find("async loadRuntimeSummary()")
        assert start != -1, "loadRuntimeSummary method not found"
        # Find the end of the method (next }, or next method)
        body_start = js.find("{", start)
        # Simple depth-based extraction of function body
        depth = 0
        pos = body_start
        while pos < len(js):
            ch = js[pos]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    break
            pos += 1
        body = js[body_start:pos + 1]
        # Must use apiGet
        assert "apiGet" in body, "loadRuntimeSummary must call apiGet"
        # Must NOT call save APIs
        assert "apiPost" not in body, "loadRuntimeSummary should not call apiPost"
        assert "apiPut" not in body, "loadRuntimeSummary should not call apiPut"
        assert "apiDelete" not in body, "loadRuntimeSummary should not call apiDelete"

    def test_load_runtime_summary_url_matches(self):
        js = _CONFIG_JS.read_text(encoding="utf-8")
        assert "/api/config/runtime-summary" in js


class TestConfigCssSpinner:
    def test_rt_loading_spinner_css_exists(self):
        css_file = _STATIC_DIR / "styles" / "pages" / "config.css"
        css = css_file.read_text(encoding="utf-8")
        assert "rt-loading-spinner" in css
        assert "rt-spin" in css
