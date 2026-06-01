"""Payload builder registry（Task 15a/15b）。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from app.schemas import AuditTypeConfig

if TYPE_CHECKING:
    from app.services.data_source_loader import PatientBundle
else:
    PatientBundle = Any


PayloadBuilder = Callable[[AuditTypeConfig, PatientBundle, str], tuple[dict[str, Any], str]]

_BUILDERS: dict[str, PayloadBuilder] = {}


def register_builder(name: str, builder: PayloadBuilder) -> None:
    key = str(name or "").strip()
    if not key:
        raise ValueError("builder name required")
    _BUILDERS[key] = builder


def unregister_builder(name: str) -> None:
    key = str(name or "").strip()
    if key:
        _BUILDERS.pop(key, None)


def get_builder(name: str) -> PayloadBuilder:
    key = str(name or "").strip()
    builder = _BUILDERS.get(key)
    if builder is None:
        raise ValueError(f"unknown payload builder: {key}")
    return builder


def has_builder(name: str) -> bool:
    key = str(name or "").strip()
    return key in _BUILDERS


def list_builders() -> list[str]:
    return sorted(_BUILDERS.keys())
