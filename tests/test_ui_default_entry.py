"""UI_DEFAULT_ENTRY 默认入口开关：默认 ui-next，显式 legacy 回退。"""
import os

from app.main import resolve_ui_default_entry


def test_default_entry_when_env_unset(monkeypatch):
    monkeypatch.delenv("UI_DEFAULT_ENTRY", raising=False)
    assert resolve_ui_default_entry() == "ui-next"


def test_default_entry_when_env_invalid(monkeypatch):
    # 2026-11-15 起默认 ui-next：非法/未知/空取值一律按默认 ui-next（仅显式 legacy 回退）。
    monkeypatch.setenv("UI_DEFAULT_ENTRY", "unknown")
    assert resolve_ui_default_entry() == "ui-next"
    monkeypatch.setenv("UI_DEFAULT_ENTRY", "")
    assert resolve_ui_default_entry() == "ui-next"
    monkeypatch.setenv("UI_DEFAULT_ENTRY", "UI-NEXT")
    assert resolve_ui_default_entry() == "ui-next"


def test_default_entry_legacy_when_env_explicit(monkeypatch):
    monkeypatch.setenv("UI_DEFAULT_ENTRY", "legacy")
    assert resolve_ui_default_entry() == "legacy"
    monkeypatch.setenv("UI_DEFAULT_ENTRY", "LEGACY")
    assert resolve_ui_default_entry() == "legacy"


def test_main_root_handler_redirects_to_ui_next_by_default():
    source = open(
        os.path.join(os.path.dirname(__file__), "..", "app", "main.py"),
        encoding="utf-8",
    ).read()
    assert "resolve_ui_default_entry" in source
    assert "UI_DEFAULT_ENTRY" in source
    # 默认分支：/ → 302 跳转 /ui-next/；显式 legacy 分支保留旧版 FileResponse（200）。
    assert 'RedirectResponse(url="/ui-next/"' in source
    assert "status_code=302" in source
    assert "FileResponse(index_path)" in source
