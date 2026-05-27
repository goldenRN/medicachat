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

    money_token = match.group(1).strip()
    decimal_match = re.search(r"([.,])(\d{2})$", money_token)
    if decimal_match:
        decimal_value = decimal_match.group(2)
        integer_part = money_token[: decimal_match.start()].strip()
        integer_digits = re.sub(r"[^\d]", "", integer_part)
        if not integer_digits:
            return compact[:80]
        formatted = f"{int(integer_digits):,}.{decimal_value}"
        if "₮" in compact or "төг" in compact.lower():
            return f"{formatted}₮"
        return formatted

    digits = re.sub(r"[^\d]", "", money_token)
    if not digits:
        return compact[:80]

    formatted = f"{int(digits):,}"
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


def extract_receipt_item_lines(text: str) -> str:
    lines = [line.strip() for line in normalize_multiline_text(text).split("\n") if line.strip()]
    selected: list[str] = []
    seen: set[str] = set()
    in_items = False

    for line in lines:
        lowered = line.lower()
        if "бараа" in lowered:
            in_items = True
            continue

        if not in_items:
            continue

        if any(
            keyword in lowered
            for keyword in [
                "огноо",
                "ттд",
                "ддтд",
                "нийт",
                "төлөх",
                "дүн",
                "total",
                "amount",
                "grand total",
                "cashier",
                "register",
                "merchant",
                "seller",
                "thank you",
                "thankyou",
                "www.",
                "http",
            ]
        ):
            continue
        if any(ch.isdigit() for ch in line) and not re.search(r"[A-Za-zА-Яа-яӨөҮүЁё]{2,}", line):
            continue
        if len(line) < 5:
            continue
        compact = normalize_whitespace(line)
        if len(re.findall(r"[A-Za-zА-Яа-яӨөҮүЁё]", compact)) < 3:
            continue
        alpha_count = len(re.findall(r"[A-Za-zА-Яа-яӨөҮүЁё]", compact))
        weird_count = len(re.findall(r"[^A-Za-zА-Яа-яӨөҮүЁё0-9\s.,:/()%₮\\-]", compact))
        if weird_count > max(2, alpha_count // 2):
            continue
        if compact in seen:
            continue
        seen.add(compact)
        selected.append(compact)
        if len(selected) == 5:
            break

    return "\n".join(selected)


def extract_receipt_items(text: str) -> list[dict[str, str]]:
    lines = [line.strip() for line in normalize_multiline_text(text).split("\n") if line.strip()]
    items: list[dict[str, str]] = []
    in_items = False

    for line in lines:
        lowered = line.lower()
        compact = normalize_whitespace(line)

        if not in_items and "бараа" in lowered and "үнэ" in lowered:
            in_items = True
            continue

        if not in_items:
            continue

        if any(keyword in lowered for keyword in ["нийт дүн", "төлөх дүн", "хөнгөлөлт", "нөат", "төлсөн дүн", "бэлнээр"]):
            break

        if set(compact) <= {"-", ".", "_"}:
            continue

        normalized = re.sub(r"\s+", " ", compact)
        match = re.match(
            r"^(?P<name>.*?\D)\s+(?P<price>\d[\d,.' ]*)\s+(?P<qty>\d{1,3})\s+(?P<line_total>\d[\d,.' ]*)$",
            normalized,
        )
        if not match:
            continue

        name = normalize_whitespace(match.group("name"))
        if len(name) < 2 or len(name) > 80:
            continue

        items.append(
            {
                "name": name,
                "price": normalize_money_text(match.group("price")),
                "qty": normalize_whitespace(match.group("qty")),
                "lineTotal": normalize_money_text(match.group("line_total")),
            }
        )

        if len(items) == 20:
            break

    return items


def looks_like_receipt_text(text: str) -> bool:
    compact = normalize_multiline_text(text).lower()
    if not compact:
        return False

    keyword_hits = sum(
        1
        for keyword in [
            "огноо",
            "бараа",
            "үнэ",
            "тоо",
            "нийт",
            "төлөх",
            "нөат",
            "сугалааны дугаар",
            "ebarimt",
            "total",
            "amount",
            "receipt",
        ]
        if keyword in compact
    )
    return keyword_hits >= 3


def format_receipt_ocr_text(title: str, text: str) -> str:
    if not looks_like_receipt_text(text):
        return normalize_multiline_text(text)

    fields = extract_patient_fields(title, text)
    items = extract_receipt_items(text)
    lines: list[str] = []

    organization = fields.get("organizationName")
    receipt_date = fields.get("receiptDate")
    total_amount = fields.get("totalAmount")

    if organization:
        lines.append(f"Байгууллага: {organization}")
    if receipt_date:
        lines.append(f"Огноо: {receipt_date}")
    if lines:
        lines.append("")

    if items:
        lines.append("Бараанууд:")
        for item in items:
            price = item.get("price")
            qty = item.get("qty")
            line_total = item.get("lineTotal")
            parts = [item["name"]]
            if price:
                parts.append(f"Үнэ: {price}")
            if qty:
                parts.append(f"Тоо: {qty}")
            if line_total:
                parts.append(f"Нийт: {line_total}")
            lines.append(f"- {' | '.join(parts)}")
    else:
        item_info = fields.get("itemInfo")
        if item_info:
            lines.append("Бараанууд:")
            for line in item_info.split("\n"):
                compact = normalize_whitespace(line)
                if compact:
                    lines.append(f"- {compact}")

    if total_amount:
        if lines:
            lines.append("")
        lines.append(f"Нийт дүн: {total_amount}")

    if not lines:
        return normalize_multiline_text(text)

    return "\n".join(lines).strip()


def extract_organization_name(title: str, text: str) -> str:
    normalized = normalize_multiline_text(text)
    patterns = [
        r"Байгууллагын нэр:\s*([^\n\r]+)",
        r"Merchant(?: name)?:\s*([^\n\r]+)",
        r"Seller(?: name)?:\s*([^\n\r]+)",
        r"Company(?: name)?:\s*([^\n\r]+)",
        r"Hospital(?: name)?:\s*([^\n\r]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized, re.I)
        if match:
            return normalize_whitespace(match.group(1))

    lines = normalized.split("\n")

    for index, line in enumerate(lines):
        compact = normalize_whitespace(line)
        if "огноо" not in compact.lower():
            continue
        nearby_candidates: list[tuple[int, str]] = []
        for candidate in lines[max(0, index - 8):index]:
            candidate_compact = normalize_whitespace(candidate)
            letters_only = re.sub(r"[^A-Za-zА-Яа-яӨөҮүЁё]", "", candidate_compact)
            if 3 <= len(letters_only) <= 24 and letters_only == letters_only.upper():
                nearby_candidates.append((len(letters_only), candidate_compact))
        if nearby_candidates:
            nearby_candidates.sort(key=lambda item: item[0], reverse=True)
            return nearby_candidates[0][1]

    for line in lines[:15]:
        compact = normalize_whitespace(line)
        letters_only = re.sub(r"[^A-Za-zА-Яа-яӨөҮүЁё]", "", compact)
        if 3 <= len(letters_only) <= 24 and letters_only == letters_only.upper():
            if not any(keyword in compact.lower() for keyword in ["огноо", "ттд", "ддтд", "бараа", "нийт", "төлөх"]):
                return compact

    title_name = extract_name_from_title(title)
    for line in normalized.split("\n")[:8]:
        compact = normalize_whitespace(line)
        if not compact or compact == title_name:
            continue
        if len(compact) < 4:
            continue
        if compact.lower().startswith("img_"):
            continue
        if re.fullmatch(r"[\d\s,./:-]+", compact):
            continue
        if any(keyword in compact.lower() for keyword in ["огноо", "ттд", "ддтд", "бараа", "нийт", "төлөх"]):
            continue
        letters = re.findall(r"[A-Za-zА-Яа-яӨөҮүЁё]", compact)
        if len(letters) < 3:
            continue
        if len(re.findall(r"[^A-Za-zА-Яа-яӨөҮүЁё\s]", compact)) > 2:
            continue
        if re.search(r"[A-Za-zА-Яа-яӨөҮүЁё]", compact):
            return compact[:120]
    return ""


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
        "receiptDate": [
            r"Огноо:\s*([^\n\r]+)",
            r"Баримтын огноо:\s*([^\n\r]+)",
            r"Date:\s*([^\n\r]+)",
            r"Datetime:\s*([^\n\r]+)",
            r"Date Time:\s*([^\n\r]+)",
            r"(\d{4}[./-]\d{1,2}[./-]\d{1,2}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?)",
            r"(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?)",
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

    if "organizationName" not in extracted:
        organization_name = extract_organization_name(title, text)
        if organization_name:
            extracted["organizationName"] = organization_name

    if "patientName" not in extracted and normalized_title:
        extracted["patientName"] = normalized_title

    if "itemInfo" not in extracted:
        item_lines = extract_receipt_item_lines(text)
        if item_lines:
            extracted["itemInfo"] = item_lines

    if "receiptDate" in extracted:
        extracted["receiptDate"] = normalize_whitespace(extracted["receiptDate"])

    return {key: value for key, value in extracted.items() if value}


def is_suspicious_receipt_field(field_name: str, value: str, title: str = "") -> bool:
    compact = normalize_whitespace(value)
    if not compact:
        return True

    lowered = compact.lower()
    title_lowered = normalize_whitespace(title).lower()

    if lowered.startswith("aaaa") or lowered.endswith("aaaa"):
        return True

    if title_lowered and lowered == title_lowered:
        return field_name in {"organizationName", "itemInfo"}

    if field_name == "organizationName":
        if re.match(r"^[^A-Za-zА-Яа-яӨөҮүЁё0-9]+", compact):
            return True
        if re.search(r"\.(?:png|jpe?g|heic|heif|pdf|docx?|xlsx?)$", lowered):
            return True
        if not re.search(r"[A-Za-zА-Яа-яӨөҮүЁё]{2,}", compact):
            return True
        short_chunks = re.findall(r"\b[A-Za-zА-Яа-яӨөҮүЁё]{1,2}\b", compact)
        if len(short_chunks) >= 3:
            return True

    if field_name == "itemInfo":
        if re.search(r"\.(?:png|jpe?g|heic|heif|pdf|docx?|xlsx?)$", lowered):
            return True
        if len(compact) < 4:
            return True
        long_word_count = len(re.findall(r"[A-Za-zА-Яа-яӨөҮүЁё]{3,}", compact))
        if long_word_count == 0:
            return True

    if field_name == "totalAmount":
        if not re.search(r"\d", compact):
            return True

    allowed_chars = re.findall(r"[A-Za-zА-Яа-яӨөҮүЁё0-9\s.,:/#()\-₮]", compact)
    allowed_ratio = len("".join(allowed_chars)) / max(len(compact), 1)
    if allowed_ratio < 0.68:
        return True

    weird_chunks = re.findall(r"[^A-Za-zА-Яа-яӨөҮүЁё0-9\s.,:/#()\-₮]{2,}", compact)
    if weird_chunks:
        return True

    return False


def has_suspicious_receipt_fields(fields: dict[str, str] | None, title: str = "") -> bool:
    if not isinstance(fields, dict) or not fields:
        return True

    keys_to_check = ("organizationName", "itemInfo", "totalAmount", "receiptDate")
    for key in keys_to_check:
        value = str(fields.get(key) or "")
        if is_suspicious_receipt_field(key, value, title):
            return True

    return False
