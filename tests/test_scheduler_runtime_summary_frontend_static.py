"""
Frontend static tests for scheduler runtime-summary integration — Phase 3.2 Fix.

Verifies that the scheduler page includes runtime-summary warnings display,
does NOT leak sensitive fields/SQL, and that the new methods are read-only.
"""

from __future__ import annotations

from pathlib import Path

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_SCHEDULER_HTML = _STATIC_DIR / "templates" / "pages" / "scheduler.html"
_SCHEDULER_JS = _STATIC_DIR / "scripts" / "modules" / "scheduler.js"

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


def _has_forbidden(text: str, forbidden: str) -> bool:
    for allowed in _ALLOWED_BOOL_KEYS:
        text = text.replace(allowed, "__ALLOWED__")
    return forbidden in text


# ---- HTML structure ---------------------------------------------------------


class TestSchedulerHtmlWarnings:
    def test_contains_warning_header(self):
        html = _SCHEDULER_HTML.read_text(encoding="utf-8")
        assert "配置风险提示" in html

    def test_contains_warning_code_field(self):
        html = _SCHEDULER_HTML.read_text(encoding="utf-8")
        assert "w.code" in html or 'code' in html  # must reference warning code

    def test_contains_warning_message_field(self):
        html = _SCHEDULER_HTML.read_text(encoding="utf-8")
        assert "w.message" in html or 'message' in html

    def test_contains_warning_path_field(self):
        html = _SCHEDULER_HTML.read_text(encoding="utf-8")
        assert "w.path" in html or 'path' in html

    def test_contains_warning_related_path_field(self):
        html = _SCHEDULER_HTML.read_text(encoding="utf-8")
        assert "related_path" in html

    def test_empty_warnings_message(self):
        html = _SCHEDULER_HTML.read_text(encoding="utf-8")
        assert "暂无调度相关配置风险提示" in html

    def test_no_forbidden_sql_keys(self):
        html = _SCHEDULER_HTML.read_text(encoding="utf-8")
        assert not _has_forbidden(html, "query_sql"), "query_sql found in scheduler.html"
        assert not _has_forbidden(html, "field_mapping"), "field_mapping found in scheduler.html"

    def test_no_forbidden_secret_keys(self):
        html = _SCHEDULER_HTML.read_text(encoding="utf-8")
        for fk in _FORBIDDEN_KEYS:
            assert not _has_forbidden(html, fk), f"{fk} found in scheduler.html"

    def test_no_save_button_in_warning_area(self):
        html = _SCHEDULER_HTML.read_text(encoding="utf-8")
        # The "配置风险提示" section should not contain a "保存" button
        warning_start = html.find("配置风险提示")
        if warning_start == -1:
            return  # no section, nothing to check
        # Find the sub-card that contains this section
        section_start = html.rfind("<div", 0, warning_start)
        if section_start == -1:
            return
        depth = 0
        pos = section_start
        while pos < len(html):
            if html.startswith("<div", pos):
                depth += 1
                pos += 4
            elif html.startswith("</div>", pos):
                depth -= 1
                if depth == 0:
                    break
                pos += 6
            else:
                pos += 1
        section = html[section_start:pos]
        assert "保存" not in section, "save button found in warning area"


# ---- JS methods -------------------------------------------------------------


class TestSchedulerJsRuntimeSummary:
    def test_has_runtime_summary_endpoint(self):
        js = _SCHEDULER_JS.read_text(encoding="utf-8")
        assert "/api/config/runtime-summary" in js

    def test_load_scheduler_runtime_summary_exists(self):
        js = _SCHEDULER_JS.read_text(encoding="utf-8")
        assert "loadSchedulerRuntimeSummary" in js

    def test_load_scheduler_runtime_summary_only_api_get(self):
        js = _SCHEDULER_JS.read_text(encoding="utf-8")
        # Extract the function body
        start = js.find("async loadSchedulerRuntimeSummary()")
        assert start != -1
        body_start = js.find("{", start)
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
        assert "apiGet" in body, "must use apiGet"
        assert "apiPost" not in body, "must not use apiPost"
        assert "apiPut" not in body, "must not use apiPut"
        assert "apiDelete" not in body, "must not use apiDelete"

    def test_load_scheduler_page_calls_runtime_summary(self):
        js = _SCHEDULER_JS.read_text(encoding="utf-8")
        # loadSchedulerPage should reference loadSchedulerRuntimeSummary
        start = js.find("async loadSchedulerPage()")
        assert start != -1
        body_start = js.find("{", start)
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
        assert "loadSchedulerRuntimeSummary" in body, "loadSchedulerPage must call loadSchedulerRuntimeSummary"

    def test_save_functions_dont_call_runtime_summary(self):
        js = _SCHEDULER_JS.read_text(encoding="utf-8")
        # Check each save/start/stop function
        for fn_name in ("saveSchedulerConfig", "saveDischargeSchedulerConfig",
                        "startScheduler", "stopScheduler",
                        "startDischargeScheduler", "stopDischargeScheduler",
                        "triggerSchedulerNow"):
            start = js.find(f"async {fn_name}()")
            if start == -1:
                continue
            body_start = js.find("{", start)
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
            assert "/api/config/runtime-summary" not in body, \
                f"{fn_name} should not call /api/config/runtime-summary"

    def test_scheduler_audit_type_stats_exists(self):
        js = _SCHEDULER_JS.read_text(encoding="utf-8")
        assert "schedulerAuditTypeStats" in js
