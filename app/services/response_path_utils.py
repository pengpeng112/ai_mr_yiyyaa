"""Dify response path 提取工具（Task 3）。"""
from __future__ import annotations

from typing import Any

try:
    from jsonpath_ng.ext import parse as parse_jsonpath
except ImportError:  # pragma: no cover
    def parse_jsonpath(path: str):
        text = str(path or "").strip()
        if not text.startswith("$"):
            raise ValueError("JSONPath must start with '$'")
        if not text.startswith("$."):
            raise ValueError("fallback JSONPath only supports '$.' prefix")

        class _Match:
            def __init__(self, value: Any):
                self.value = value

        class _SimpleExpr:
            def __init__(self, expr: str):
                self._parts = [part for part in expr[2:].split(".") if part]

            def find(self, raw: Any):
                nodes = [raw]
                for part in self._parts:
                    key = part
                    index: int | None = None
                    if "[" in part and part.endswith("]"):
                        left = part.index("[")
                        key = part[:left]
                        try:
                            index = int(part[left + 1:-1])
                        except ValueError:
                            return []

                    next_nodes: list[Any] = []
                    for node in nodes:
                        if not isinstance(node, dict) or key not in node:
                            continue
                        value = node.get(key)
                        if index is None:
                            next_nodes.append(value)
                        elif isinstance(value, list) and 0 <= index < len(value):
                            next_nodes.append(value[index])
                    nodes = next_nodes
                    if not nodes:
                        return []
                return [_Match(item) for item in nodes]

        return _SimpleExpr(text)


def apply_response_paths(raw: Any, paths: dict | None) -> dict:
    """按 JSONPath 从原始返回中抽取字段。

    返回约定：
    - 匹配成功：返回解析字段
    - 配置了路径但全部无匹配：附加 parse_warning=response_path_no_match
    """
    if not isinstance(paths, dict) or raw is None:
        return {}

    mapping = {
        "dimension_path": "dimensions",
        "conclusion_path": "overall_conclusion",
        "severity_path": "severity",
        "risk_score_path": "risk_score",
        "inconsistency_path": "inconsistency",
    }

    extracted: dict[str, Any] = {}
    configured_count = 0
    matched_count = 0

    for source_key, target_key in mapping.items():
        path = str(paths.get(source_key) or "").strip()
        if not path:
            continue
        configured_count += 1

        try:
            matches = parse_jsonpath(path).find(raw)
        except Exception:
            continue

        if not matches:
            continue

        matched_count += 1
        values = [match.value for match in matches]
        if target_key == "dimensions":
            extracted[target_key] = values[0] if len(values) == 1 and isinstance(values[0], list) else values
        else:
            extracted[target_key] = values[0] if len(values) == 1 else values

    if configured_count > 0 and matched_count == 0:
        extracted["parse_warning"] = "response_path_no_match"

    return extracted
