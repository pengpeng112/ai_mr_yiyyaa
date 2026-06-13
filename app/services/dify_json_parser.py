"""
Dify JSON 解析模块 —— 从 dify_pusher.py 拆分，纯函数处理 JSON 容错解析。
"""
import json
import re
from typing import Any


def _load_json_with_tolerance(raw_text: str) -> Any:
    text = str(raw_text or "").strip()
    if not text:
        raise json.JSONDecodeError("empty text", text, 0)

    candidates = []
    for candidate in [
        text,
        _strip_code_fence(text),
        _extract_json_substring(text),
        _extract_json_substring(_strip_code_fence(text)),
    ]:
        original = str(candidate or "").strip()
        if original and original not in candidates:
            candidates.append(original)
        normalized = _normalize_json_text(original)
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    last_error = None
    for candidate in candidates:
        try:
            return json.loads(candidate, strict=False)
        except json.JSONDecodeError as exc:
            last_error = exc

    if last_error:
        raise last_error
    raise json.JSONDecodeError("unable to extract json", text, 0)


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _extract_json_substring(text: str) -> str:
    if not text:
        return ""
    starts = [idx for idx in [text.find("{"), text.find("[")] if idx >= 0]
    if not starts:
        return ""
    start = min(starts)
    opening = text[start]
    closing = "}" if opening == "{" else "]"
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == opening:
            depth += 1
        elif ch == closing:
            depth -= 1
            if depth == 0:
                return text[start:idx + 1]
    return text[start:].strip()


def _normalize_json_text(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    replacements = {
        "\u201c": '"',
        "\u201d": '"',
        "\u2018": "'",
        "\u2019": "'",
        "\uff0c": ",",
        "\uff1a": ":",
    }
    for old, new in replacements.items():
        normalized = normalized.replace(old, new)
    normalized = normalized.strip("` \n\r\t")
    return normalized
