from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def parse_json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return fallback


def build_history_title(text: str) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return f"{compact[:42]}..." if len(compact) > 42 else (compact or "Шинэ чат")


def summarize_content(text: str) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return f"{compact[:110]}..." if len(compact) > 110 else (compact or "No preview available.")


def sanitize_filename(name: str) -> str:
    safe = re.sub(r"[^a-zа-яөүё0-9._ -]", "_", str(name), flags=re.IGNORECASE)
    return re.sub(r"\s+", "-", safe).strip()[:120]


def sanitize_folder_name(name: str) -> str:
    compact = normalize_whitespace(str(name or ""))
    safe = re.sub(r"[^a-zа-яөүё0-9 _-]", "", compact, flags=re.IGNORECASE)
    return normalize_whitespace(safe)[:80] or "Ерөнхий"


def tokenize(text: str) -> list[str]:
    return [part for part in re.split(r"[^a-zа-яөүё0-9]+", str(text).lower()) if len(part) > 2]


def derive_tags(text: str) -> list[str]:
    seen: list[str] = []
    for token in tokenize(text):
        if token not in seen:
            seen.append(token)
        if len(seen) == 5:
            break
    return seen


def extract_name_from_title(title: str) -> str:
    no_ext = re.sub(r"\.pdf$", "", title, flags=re.I)
    no_date = re.sub(r"[-_ ]?(20\d{6}|\d{1,2}-\d{1,2})$", "", no_ext, flags=re.I)
    return normalize_whitespace(re.sub(r"[-_]+", " ", no_date))


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()
