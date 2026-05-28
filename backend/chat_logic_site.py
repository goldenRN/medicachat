from __future__ import annotations

import re
from typing import Any

from .chat_logic_shared import extract_person_query, normalize_question_for_intent
from .store import list_documents as load_documents_from_store
from .text_utils import normalize_whitespace


SITE_BRAND_HINTS = (
    "сос медика",
    "sos medica",
    "sosmedica",
    "coc medika",
    "coc medica",
    "сос медика эмнэлэг",
)

GENERIC_SITE_HINTS = (
    "манай эмнэлэг",
    "эмнэлгийн",
    "эмнэлэг",
    "clinic",
    "hospital",
)

SITE_INFO_KEYWORDS = (
    "хаана",
    "хаяг",
    "утас",
    "байрш",
    "салбар",
    "холбоо",
    "website",
    "веб",
    "site",
    "address",
    "phone",
    "contact",
    "location",
    "located",
    "gazar",
    "bairsh",
    "gazar zui",
)

SITE_BRANCH_HINTS = (
    "зайсан",
    "үндсэн",
    "main branch",
    "zaisan",
    "salbar",
    "салбар",
)


def is_site_information_question(
    question: str,
    history_messages: list[dict[str, Any]] | None = None,
) -> bool:
    normalized = normalize_question_for_intent(question)
    history_messages = history_messages or []

    has_site_keyword = any(keyword in normalized for keyword in SITE_INFO_KEYWORDS)
    has_brand_hint = any(hint in normalized for hint in SITE_BRAND_HINTS)
    has_generic_hint = any(hint in normalized for hint in GENERIC_SITE_HINTS)
    has_branch_hint = any(hint in normalized for hint in SITE_BRANCH_HINTS)
    if has_site_keyword and has_brand_hint:
        return True
    if has_site_keyword and has_generic_hint and not extract_person_query(question):
        return True
    if has_site_keyword and has_branch_hint:
        return True

    if not has_site_keyword:
        return False

    recent_user_messages = [
        normalize_question_for_intent(message.get("text", ""))
        for message in history_messages
        if message.get("role") == "user"
    ][-4:]
    return any(any(hint in text for hint in SITE_BRAND_HINTS) for text in recent_user_messages)


def find_site_information_document() -> dict[str, Any] | None:
    documents = load_documents_from_store()
    preferred_titles = ("hayag", "contact", "address")
    for document in documents:
        title = str(document.get("title", "") or "").lower()
        if any(title.startswith(prefix) for prefix in preferred_titles):
            return document

    for document in documents:
        text = f"{document.get('title', '')}\n{document.get('summary', '')}\n{document.get('content', '')}".lower()
        if "сос медика эмнэлэг хоёр салбартай" in text or "sos medica mongolia" in text:
            return document
    return None


def parse_site_information_sections(content: str) -> dict[str, dict[str, str]]:
    normalized_content = normalize_whitespace(str(content or ""))
    sections: dict[str, dict[str, str]] = {}

    main_match = re.search(
        r"Үндсэн эмнэлэг\s*Хаяг:\s*(.*?)\s*Утас:\s*(.*?)\s*Яаралтай тусламж:\s*(.*?)\s*Цагийн хуваарь:\s*(.*?)\s*(?:📍\s*)?Зайсан салбар",
        normalized_content,
        re.S,
    )
    if main_match:
        sections["main"] = {
            "label": "Үндсэн эмнэлэг",
            "address": normalize_whitespace(main_match.group(1)),
            "phone": normalize_whitespace(main_match.group(2)),
            "emergency": normalize_whitespace(main_match.group(3)),
            "hours": normalize_whitespace(main_match.group(4)),
        }

    zaisan_match = re.search(
        r"Зайсан салбар\s*Хаяг:\s*(.*?)\s*Утас:\s*(.*?)\s*Цагийн хуваарь:\s*(.*?)(?:Хэрэв газрын зураг|$)",
        normalized_content,
        re.S,
    )
    if zaisan_match:
        sections["zaisan"] = {
            "label": "Зайсан салбар",
            "address": normalize_whitespace(zaisan_match.group(1)),
            "phone": normalize_whitespace(zaisan_match.group(2)),
            "hours": normalize_whitespace(zaisan_match.group(3)),
        }

    map_tip_match = re.search(r"(Хэрэв газрын зураг.*)$", normalized_content)
    if map_tip_match:
        sections["meta"] = {
            "mapTip": normalize_whitespace(map_tip_match.group(1)),
        }
    return sections


def build_site_information_answer(question: str, history_messages: list[dict[str, Any]] | None = None) -> str | None:
    if not is_site_information_question(question, history_messages):
        return None

    document = find_site_information_document()
    if not document:
        return "Эмнэлгийн хаяг, холбоо барих мэдээллийн эх сурвалж одоогоор олдсонгүй."

    sections = parse_site_information_sections(str(document.get("content", "") or ""))
    if not sections:
        return "Эмнэлгийн хаяг, холбоо барих мэдээллийг хадгалсан баримтыг олсон ч задлаж чадсангүй."

    normalized = normalize_question_for_intent(question)
    target_section = "zaisan" if "зайсан" in normalized else "main" if "үндсэн" in normalized else ""
    address_only = any(key in normalized for key in ("хаяг", "address", "байрш", "location"))
    phone_only = any(key in normalized for key in ("утас", "phone", "contact", "холбоо"))
    hours_only = any(key in normalized for key in ("цаг", "schedule", "working hour", "ажиллах цаг"))
    emergency_only = "яаралтай" in normalized

    if target_section and target_section in sections:
        section = sections[target_section]
        lines = [f"{section['label']}:"]
        if address_only or not (phone_only or hours_only or emergency_only):
            lines.append(f"- Хаяг: {section.get('address', '-')}")
        if phone_only or not (address_only or hours_only or emergency_only):
            lines.append(f"- Утас: {section.get('phone', '-')}")
        if emergency_only and section.get("emergency"):
            lines.append(f"- Яаралтай тусламж: {section.get('emergency', '-')}")
        if hours_only or not (address_only or phone_only or emergency_only):
            if section.get("hours"):
                lines.append(f"- Цагийн хуваарь: {section.get('hours', '-')}")
        return "\n".join(lines)

    if emergency_only and sections.get("main", {}).get("emergency"):
        return f"Яаралтай тусламжийн утас: {sections['main']['emergency']}"

    if phone_only and not address_only and not hours_only:
        lines = ["СОС Медикагийн холбоо барих утас:"]
        if "main" in sections:
            lines.append(f"- Үндсэн эмнэлэг: {sections['main'].get('phone', '-')}")
            if sections["main"].get("emergency"):
                lines.append(f"- Яаралтай тусламж: {sections['main'].get('emergency', '-')}")
        if "zaisan" in sections:
            lines.append(f"- Зайсан салбар: {sections['zaisan'].get('phone', '-')}")
        return "\n".join(lines)

    lines = ["СОС Медика эмнэлгийн салбарууд:"]
    if "main" in sections:
        lines.append(f"- Үндсэн эмнэлэг: {sections['main'].get('address', '-')}")
        lines.append(f"  Утас: {sections['main'].get('phone', '-')}")
        if sections["main"].get("emergency"):
            lines.append(f"  Яаралтай тусламж: {sections['main'].get('emergency', '-')}")
        if sections["main"].get("hours"):
            lines.append(f"  Цагийн хуваарь: {sections['main'].get('hours', '-')}")
    if "zaisan" in sections:
        lines.append(f"- Зайсан салбар: {sections['zaisan'].get('address', '-')}")
        lines.append(f"  Утас: {sections['zaisan'].get('phone', '-')}")
        if sections["zaisan"].get("hours"):
            lines.append(f"  Цагийн хуваарь: {sections['zaisan'].get('hours', '-')}")
    map_tip = sections.get("meta", {}).get("mapTip")
    if map_tip:
        lines.append(f"- {map_tip}")
    return "\n".join(lines)
