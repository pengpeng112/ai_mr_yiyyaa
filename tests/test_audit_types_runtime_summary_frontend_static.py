"""
Frontend static tests for audit-types runtime-summary integration — Phase 3.3.

Verifies that the audit-types page includes runtime-summary warnings display,
does NOT leak sensitive fields/SQL, and that the new methods are read-only.
"""

from __future__ import annotations

from pathlib import Path

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_AUDIT_TYPES_HTML = _STATIC_DIR / "templates" / "pages" / "audit_types.html"
_AUDIT_TYPES_JS = _STATIC_DIR / "scripts" / "modules" / "audit_types.js"

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


class TestAuditTypesHtmlWarnings:
    def test_contains_warning_header(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        assert "审计类型风险提示" in html

    def test_contains_warning_code_field(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        assert "w.code" in html  # must reference warning code

    def test_contains_warning_message_field(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        assert "w.message" in html

    def test_contains_warning_path_field(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        assert "w.path" in html

    def test_contains_warning_related_path_field(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        assert "related_path" in html

    def test_empty_warnings_message(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        assert "暂无审计类型相关配置风险提示" in html

    def test_no_forbidden_sql_keys(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        # check that the runtime-summary warning area does NOT contain forbidden keys
        rt_start = html.find("审计类型风险提示")
        if rt_start == -1:
            return
        div_start = html.rfind("<div", 0, rt_start)
        if div_start == -1:
            return
        depth = 0
        pos = div_start
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
        section = html[div_start:pos]
        assert not _has_forbidden(section, "query_sql"), "query_sql found in audit-types warning area"
        assert not _has_forbidden(section, "field_mapping"), "field_mapping found in audit-types warning area"

    def test_no_forbidden_secret_keys_in_warning_area(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        rt_start = html.find("审计类型风险提示")
        if rt_start == -1:
            return
        div_start = html.rfind("<div", 0, rt_start)
        if div_start == -1:
            return
        depth = 0
        pos = div_start
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
        section = html[div_start:pos]
        for fk in _FORBIDDEN_KEYS:
            assert not _has_forbidden(section, fk), f"{fk} found in audit-types warning area"

    def test_no_save_button_in_warning_area(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        warning_start = html.find("审计类型风险提示")
        if warning_start == -1:
            return
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


# ---- HTML summary table -----------------------------------------------------


class TestAuditTypesHtmlSummary:
    def test_contains_summary_header(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        assert "运行解析摘要" in html

    def test_uses_audit_type_runtime_summaries(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        assert "auditTypeRuntimeSummaries" in html

    def test_displays_code_field(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        summary_start = html.find("运行解析摘要")
        if summary_start == -1:
            return
        # Find the sub-card containing this section
        subcard_start = html.rfind('<div class="sub-card"', 0, summary_start)
        pos = summary_start
        while pos < len(html):
            if html.find("</div>", pos) == -1:
                break
            pos += 1
        assert 'prop="code"' in html, "must display code column"

    def test_displays_name_field(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        assert 'prop="name"' in html, "must display name column"

    def test_displays_enabled_field(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        assert "scope.row.enabled" in html

    def test_displays_default_for_schedule(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        assert "scope.row.default_for_schedule" in html

    def test_displays_builder_field(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        assert "scope.row.builder" in html

    def test_displays_flags_uses_sql(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        assert "flags?.uses_sql" in html or "flags.uses_sql" in html

    def test_displays_flags_has_display_config(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        assert "flags?.has_display_config" in html or "flags.has_display_config" in html

    def test_displays_sources_has_query_sql(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        assert "src.hasQuerySql" in html

    def test_displays_sources_key(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        assert "src.key" in html

    def test_displays_sources_type(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        assert "src.type" in html

    def test_displays_sources_backend(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        assert "src.backend" in html

    def test_displays_sources_required(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        assert "src.required" in html

    def test_displays_required_text(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        assert "必需" in html, "must display required label text"

    def test_displays_optional_text(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        assert "可选" in html, "must display optional label text"

    def test_displays_has_query_sql_text(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        assert "SQL:" in html, "must display SQL label in source tags"

    def test_dify_column_label(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        assert 'Dify目标' in html or 'label="Dify' in html

    def test_displays_target_source(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        assert "target_source" in html or "auditTypeRuntimeTargetSource" in html

    def test_displays_workflow_input_variable(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        assert "workflow_input_variable" in html or "auditTypeRuntimeWorkflowInput" in html

    def test_displays_has_api_key_boolean(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        assert "has_api_key" in html or "auditTypeRuntimeHasApiKey" in html

    def test_displays_has_base_url_boolean(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        assert "auditTypeRuntimeHasBaseUrl" in html

    def test_base_url_not_directly_rendered(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        summary_start = html.find("运行解析摘要")
        if summary_start == -1:
            return
        subcard_start = html.rfind("<div", 0, summary_start)
        if subcard_start == -1:
            return
        depth = 0
        pos = subcard_start
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
        section = html[subcard_start:pos]
        assert "base_url" not in section, \
            "base_url must not be directly rendered in summary section"

    def test_no_forbidden_keys_in_summary_section(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        summary_start = html.find("运行解析摘要")
        if summary_start == -1:
            return
        # Extract the sub-card that contains the summary
        subcard_start = html.rfind("<div", 0, summary_start)
        if subcard_start == -1:
            return
        depth = 0
        pos = subcard_start
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
        section = html[subcard_start:pos]
        assert not _has_forbidden(section, "query_sql"), "query_sql found in summary section"
        assert not _has_forbidden(section, "field_mapping"), "field_mapping found in summary section"

    def test_no_secret_keys_in_summary_section(self):
        html = _AUDIT_TYPES_HTML.read_text(encoding="utf-8")
        summary_start = html.find("运行解析摘要")
        if summary_start == -1:
            return
        subcard_start = html.rfind("<div", 0, summary_start)
        if subcard_start == -1:
            return
        depth = 0
        pos = subcard_start
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
        section = html[subcard_start:pos]
        for fk in _FORBIDDEN_KEYS:
            assert not _has_forbidden(section, fk), f"{fk} found in summary section"


# ---- JS methods -------------------------------------------------------------


class TestAuditTypesJsRuntimeSummary:
    def test_has_runtime_summary_endpoint(self):
        js = _AUDIT_TYPES_JS.read_text(encoding="utf-8")
        assert "/api/config/runtime-summary" in js

    def test_load_audit_type_runtime_summary_exists(self):
        js = _AUDIT_TYPES_JS.read_text(encoding="utf-8")
        assert "loadAuditTypeRuntimeSummary" in js

    def test_load_audit_type_runtime_summary_only_api_get(self):
        js = _AUDIT_TYPES_JS.read_text(encoding="utf-8")
        start = js.find("async loadAuditTypeRuntimeSummary()")
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

    def test_load_audit_types_page_calls_runtime_summary(self):
        js = _AUDIT_TYPES_JS.read_text(encoding="utf-8")
        start = js.find("async loadAuditTypesPage()")
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
        assert "loadAuditTypeRuntimeSummary" in body, "loadAuditTypesPage must call loadAuditTypeRuntimeSummary"

    def test_save_functions_dont_call_runtime_summary(self):
        js = _AUDIT_TYPES_JS.read_text(encoding="utf-8")
        for fn_name in ("submitAuditTypeForm", "deleteAuditType",
                        "submitAuditTypeClone", "submitAuditTypeSourceTest",
                        "submitAuditTypeDifyTest"):
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

    def test_warning_filter_uses_audit_types_path(self):
        js = _AUDIT_TYPES_JS.read_text(encoding="utf-8")
        assert "audit_types." in js, "warning filter must reference audit_types. path prefix"

    def test_audit_type_warning_tag_type_exists(self):
        js = _AUDIT_TYPES_JS.read_text(encoding="utf-8")
        assert "auditTypeWarningTagType" in js

    def test_audit_type_warnings_by_level_exists(self):
        js = _AUDIT_TYPES_JS.read_text(encoding="utf-8")
        assert "auditTypeWarningsByLevel" in js

    def test_audit_type_runtime_summaries_exists(self):
        js = _AUDIT_TYPES_JS.read_text(encoding="utf-8")
        assert "auditTypeRuntimeSummaries" in js

    def test_audit_type_runtime_source_rows_exists(self):
        js = _AUDIT_TYPES_JS.read_text(encoding="utf-8")
        assert "auditTypeRuntimeSourceRows" in js

    def test_audit_type_runtime_target_source_exists(self):
        js = _AUDIT_TYPES_JS.read_text(encoding="utf-8")
        assert "auditTypeRuntimeTargetSource" in js

    def test_audit_type_runtime_workflow_input_exists(self):
        js = _AUDIT_TYPES_JS.read_text(encoding="utf-8")
        assert "auditTypeRuntimeWorkflowInput" in js

    def test_audit_type_runtime_has_api_key_exists(self):
        js = _AUDIT_TYPES_JS.read_text(encoding="utf-8")
        assert "auditTypeRuntimeHasApiKey" in js

    def test_audit_type_runtime_has_base_url_exists(self):
        js = _AUDIT_TYPES_JS.read_text(encoding="utf-8")
        assert "auditTypeRuntimeHasBaseUrl" in js

    def test_dify_target_helpers_use_dify_target(self):
        js = _AUDIT_TYPES_JS.read_text(encoding="utf-8")
        assert "dify_target" in js, "helpers must reference dify_target from runtime summary"

    def test_audit_type_runtime_flag_type_exists(self):
        js = _AUDIT_TYPES_JS.read_text(encoding="utf-8")
        assert "auditTypeRuntimeFlagType" in js
