from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def normalize_money_text(value: str) -> str:
    compact = normalize_whitespace(value)
    if not compact:
        return ""

    match = re.search(r"([0-9][0-9\s,.'`]*[0-9])", compact)
    if not match:
        return compact[:80]

    digits = re.sub(r"[^\d]", "", match.group(1))
    if not digits:
        return compact[:80]

    formatted = f"{int(digits):,}".replace(",", ",")
    if "₮" in compact or "төг" in compact.lower():
        return f"{formatted}₮"
    return formatted


def normalize_multiline_text(value: str) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    compact_lines: list[str] = []
    previous_blank = False
    for line in lines:
        if not line:
            if not previous_blank:
                compact_lines.append("")
            previous_blank = True
            continue
        compact_lines.append(line)
        previous_blank = False
    return "\n".join(compact_lines).strip()


def build_text_chunks(
    value: str,
    max_chars: int = 900,
    overlap_chars: int = 140,
) -> list[str]:
    text = normalize_multiline_text(value)
    if not text:
        return []

    paragraphs = [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]
    if not paragraphs:
        paragraphs = [text]

    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
            continue

        if current:
            chunks.append(current)

        if len(paragraph) <= max_chars:
            current = paragraph
            continue

        start = 0
        while start < len(paragraph):
            end = min(start + max_chars, len(paragraph))
            window = paragraph[start:end].strip()
            if window:
                chunks.append(window)
            if end >= len(paragraph):
                break
            start = max(end - overlap_chars, start + 1)
        current = ""

    if current:
        chunks.append(current)

    deduped: list[str] = []
    previous = None
    for chunk in chunks:
        compact = normalize_whitespace(chunk)
        if not compact or compact == previous:
            continue
        deduped.append(chunk.strip())
        previous = compact
    return deduped


def extract_patient_fields(title: str, content: str) -> dict[str, str]:
    text = normalize_multiline_text(content)
    normalized_title = extract_name_from_title(title)

    patterns = {
        "patientName": [
            r"Нэр,?\s*Овог:\s*([^\n]+)",
            r"\bНэр:\s*([^\n\r]+?)(?:\s+Хүйс:|\s+Регистр|\s+Нас:|\s*$)",
            r"\bName:\s*([^\n\r]+?)(?:\s+Gender:|\s+Age:|\s+Register|\s*$)",
        ],
        "parentName": [
            r"Эцэг\/эхийн нэр:\s*([^\n\r]+?)(?:\s+Нас:|\s*$)",
            r"Parent(?: name)?:\s*([^\n\r]+)",
        ],
        "registerNumber": [
            r"Регистрийн дугаар:\s*([A-ZА-Я0-9]+)",
            r"Register(?: number)?:\s*([A-Z0-9-]+)",
            r"БҮРТГЭЛИЙН ДУГААР:\s*([A-ZА-Я0-9]+)",
        ],
        "age": [
            r"Нас:\s*([0-9]{1,3})",
            r"Age:\s*([0-9]{1,3})",
        ],
        "gender": [
            r"Хүйс:\s*([^\n\r:]{2,20})",
            r"Gender:\s*([^\n\r:]{2,20})",
        ],
        "visitDate": [
            r"ШИНЖИЛГЭЭНИЙ ОГНОО:\s*([^\n\r]+)",
            r"Test Date \/ Time:\s*([^\n\r]+)",
            r"Date \/ Time:\s*([^\n\r]+)",
        ],
        "doctorName": [
            r"Эмч:\s*([^\n\r]+)",
            r"Doctor:\s*([^\n\r]+)",
        ],
        "diagnosis": [
            r"Онош:\s*([^\n\r]+)",
            r"Diagnosis:\s*([^\n\r]+)",
        ],
        "recommendation": [
            r"Зөвлөгөө:\s*([^\n\r]+)",
            r"Recommendation:\s*([^\n\r]+)",
        ],
        "totalAmount": [
            r"Нийт дүн:\s*([^\n\r]+)",
            r"Төлөх дүн:\s*([^\n\r]+)",
            r"Нийт төлбөр:\s*([^\n\r]+)",
            r"Төлбөрийн дүн:\s*([^\n\r]+)",
            r"Төлөх\s*:\s*([^\n\r]+)",
            r"Дүн\s*:\s*([^\n\r]+)",
            r"\bTotal(?: amount)?:\s*([^\n\r]+)",
            r"\bAmount due:\s*([^\n\r]+)",
            r"\bGrand total:\s*([^\n\r]+)",
        ],
        "itemInfo": [
            r"Барааны мэдээлэл:\s*([^\n\r]+)",
            r"Бараа(?:нууд)?\s*:\s*([^\n\r]+)",
            r"Үйлчилгээ(?:ний)?\s*:\s*([^\n\r]+)",
            r"Items?:\s*([^\n\r]+)",
        ],
    }

    extracted: dict[str, str] = {}
    for field, field_patterns in patterns.items():
        for pattern in field_patterns:
            match = re.search(pattern, text, re.I)
            if match:
                extracted[field] = normalize_whitespace(match.group(1))
                break

    if "totalAmount" not in extracted:
        money_lines = []
        for line in text.split("\n"):
            normalized_line = normalize_whitespace(line)
            if not normalized_line:
                continue
            lowered = normalized_line.lower()
            if any(keyword in lowered for keyword in ["нийт", "төлөх", "төлбөр", "total", "amount", "grand total"]):
                if re.search(r"\d", normalized_line):
                    money_lines.append(normalized_line)
        for line in money_lines:
            amount_match = re.search(r"([0-9][0-9\s,.'`]{2,}[0-9]\s*(?:₮|төг)?)", line, re.I)
            if amount_match:
                extracted["totalAmount"] = normalize_money_text(amount_match.group(1))
                break

    if "totalAmount" in extracted:
        extracted["totalAmount"] = normalize_money_text(extracted["totalAmount"])

    if "patientName" not in extracted and normalized_title:
        extracted["patientName"] = normalized_title

    return {key: value for key, value in extracted.items() if value}
