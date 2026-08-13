"""UI_DEFAULT_ENTRY 默认入口开关：默认 legacy，可选 ui-next。"""
import os

from app.main import resolve_ui_default_entry


def test_resolve_ui_default_entry_defaults_to_legacy(monkeypatch):
    monkeypatch.delenv("UI_DEFAULT_ENTRY", raising=False)
    assert resolve_ui_default_entry() == "legacy"
    assert resolve_ui_default_entry("") == "legacy"
    assert resolve_ui_default_entry("LEGACY") == "legacy"
    assert resolve_ui_default_entry("unknown") == "legacy"


def test_resolve_ui_default_entry_accepts_ui_next_aliases(monkeypatch):
    monkeypatch.setenv("UI_DEFAULT_ENTRY", "ui-next")
    assert resolve_ui_default_entry() == "ui-next"
    assert resolve_ui_default_entry("ui-next") == "ui-next"
    assert resolve_ui_default_entry("UI-NEXT") == "ui-next"
    assert resolve_ui_default_entry("next") == "ui-next"
    assert resolve_ui_default_entry("ui_next") == "ui-next"


def test_main_registers_root_handler_and_default_is_legacy():
    source = open(
        os.path.join(os.path.dirname(__file__), "..", "app", "main.py"),
        encoding="utf-8",
    ).read()
    assert "resolve_ui_default_entry" in source
    assert 'UI_DEFAULT_ENTRY' in source
    assert 'RedirectResponse(url="/ui-next/"' in source
    assert "FileResponse(index_path)" in source
