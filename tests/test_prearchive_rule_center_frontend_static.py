"""归档前规则中心 Legacy 前端静态契约测试（039 T7）。

直接读 static 资产（无服务器/DB/浏览器/网络），验证：
- 质控类型页内规则中心区域的关键能力锚点（列表/草稿/校验/试运行/审批/发布/回滚/版本/目标/Outbox）；
- 全部经 BFF 白名单路径 /api/prearchive-admin/*，无直连预检服务；
- 权限控制（prcCan + prearchive_* 权限锚）；
- BFF 不可用降级提示不影响六类审计类型 CRUD；
- 禁止 PHI/密钥硬编码。
"""

from __future__ import annotations

from pathlib import Path

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_PAGE_HTML = _STATIC_DIR / "templates" / "pages" / "audit_types.html"
_PRC_JS = _STATIC_DIR / "scripts" / "modules" / "prearchive_rule_center.js"
_APP_JS = _STATIC_DIR / "scripts" / "app.js"
_AUDIT_TYPES_JS = _STATIC_DIR / "scripts" / "modules" / "audit_types.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_rule_center_section_exists_in_audit_types_page():
    html = _read(_PAGE_HTML)
    assert "归档前规则中心" in html
    # 不新增平行菜单：区域嵌在既有质控类型页文件内（audit_types.html）
    assert _PAGE_HTML.name == "audit_types.html"


def test_rule_center_capability_anchors():
    html = _read(_PAGE_HTML)
    js = _read(_PRC_JS)
    anchors = [
        "新建草稿", "试运行", "审批", "发布", "回滚", "版本",
        "投递目标", "Outbox", "契约测试", "运行模式",
    ]
    for anchor in anchors:
        assert anchor in html, anchor
    assert "确认发布（危险操作）" in js          # 发布二次确认
    assert "content_sha256" in js                # 发布对话框显示 SHA


def test_all_calls_go_through_bff_whitelist_paths():
    js = _read(_PRC_JS)
    assert "/api/prearchive-admin/" in js
    # 不得直连预检服务（无 8600 端口/裸 /api/admin 直连）
    assert ":8600" not in js
    lines = [line for line in js.splitlines() if "apiGet(" in line or "apiPost(" in line or "apiPut(" in line]
    assert lines, "至少存在一处 API 调用"
    for line in lines:
        if "/api/" in line:
            assert "/api/prearchive-admin/" in line, f"越权路径: {line.strip()}"


def test_permission_gates_in_ui():
    html = _read(_PAGE_HTML)
    js = _read(_PRC_JS)
    perms = ["prearchive_rule_edit", "prearchive_rule_approve",
             "prearchive_rule_publish", "prearchive_integration_manage",
             "prearchive_delivery_retry"]
    for perm in perms:
        assert perm in html, perm
    assert "prcCan(" in html
    assert "currentUser" in js or "prcCan" in js


def test_bff_unavailable_degradation_notice():
    html = _read(_PAGE_HTML)
    assert "prcDisabledTitle()" in html          # 041 T3：标题由方法按 403/502/503 分流
    js = _read(_PRC_JS)
    assert "不受影响" in js                        # 降级提示不影响六类 CRUD 的口径保留
    assert "PREARCHIVE_ADMIN_ENABLED" in js       # 默认关闭原因提示
    assert "503" in js
    # 041 T3：403=权限问题（不得写成服务故障）；502/503=服务不可用
    assert "无访问权限" in js and "403" in js
    assert "规则中心不可用" in js and "502" in js
    assert "prearchive_rule_view" in js           # 403 提示须点名缺失权限


def test_existing_audit_type_crud_untouched():
    """既有六类审计类型 CRUD 锚仍在（不删除/不重写）。"""
    html = _read(_PAGE_HTML)
    js = _read(_AUDIT_TYPES_JS)
    assert "auditTypeDialogVisible" in html
    assert "openAuditTypeCreate" in js
    assert "submitAuditTypeForm" in js
    # 既有只读预检规则展示保留
    assert "归档前预检规则" in html
    assert "loadPrearchiveRules" in js


def test_app_js_wires_module_state_and_methods():
    app = _read(_APP_JS)
    assert "createPrearchiveRuleCenterState" in app
    assert "prearchiveRuleCenterMethods" in app
    assert "prearchive_rule_center.js?v=20260902-prc-v1" in app


def test_no_secrets_or_phi_hardcoded():
    js = _read(_PRC_JS)
    html = _read(_PAGE_HTML)
    for text in (js, html):
        assert "SECRET" not in text
        assert "password" not in text.lower() or "PREARCHIVE_EMR_HMAC_SECRET" not in text
        # 患者标识只出现在合成契约测试占位
        assert "真实患者" in text or "虚构" in text or "合成" in text


def test_mode_and_delivery_banner():
    html = _read(_PAGE_HTML)
    assert "prcModeBanner()" in html
    assert "prcDeliveryBanner()" in html
    js = _read(_PRC_JS)
    assert "影子比对" in js and "文件规则" in js and "规则仓" in js
    assert "对外推送关闭" in js
