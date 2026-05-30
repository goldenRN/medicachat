from __future__ import annotations

from typing import Any

from .chat_logic_shared import (
    extract_person_query,
    extract_query_tokens,
    is_count_question,
    is_list_question,
    normalize_person_phrase,
    normalize_question_for_intent,
    strip_name_suffix,
    tokens_match,
    transliterate_cyrillic_to_latin,
)
from .documents import count_spreadsheet_data_rows
from .store import list_employees
from .text_utils import normalize_whitespace, tokenize


EMPLOYEE_QUERY_STOPWORDS = {
    "ажилчид",
    "ажилтан",
    "ajilchid",
    "ajiltan",
    "employee",
    "staff",
    "personnel",
    "мэдээлэл",
    "medeelel",
    "жагсаалт",
    "jagsaalt",
    "хүснэгт",
    "table",
    "бүгд",
    "bugd",
    "хэн",
    "нэр",
    "албан",
    "тушаал",
    "холбоо",
    "барих",
    "утас",
    "phone",
    "email",
    "mail",
    "имэйл",
    "и",
    "мэйл",
    "байна",
    "baina",
    "байнуу",
    "bainuu",
    "nar",
    "нар",
    "iin",
    "in",
    "nii",
    "ni",
    "хэдэн",
    "heden",
    "kheden",
    "niit",
    "нийт",
    "khun",
    "hun",
    "хүн",
    "ajilladag",
    "ажилладаг",
    "ajillakh",
    "ажиллах",
    "emneleg",
    "эмнэлэг",
    "emnelegt",
    "эмнэлэгт",
    "clinic",
    "манай",
    "manai",
    "ve",
    "вэ",
    "эмнэлгийн",
    "emnelgiin",
    "sos",
    "medica",
    "medika",
    "coc",
    "mongolia",
}

EMPLOYEE_CATEGORY_HINTS = {
    "clinic_management_admin": (
        "захиргаа",
        "захиргааны",
        "удирдлага",
        "administration",
        "management",
        "admin",
    ),
    "clinic_medical": (
        "эмнэлгийн чиг",
        "medical function",
        "medical staff",
        "clinical staff",
    ),
    "ot_staff": (
        "ot staff",
        "oyu tolgoi",
        "оюу толгой",
    ),
    "clinic_other": (
        "бусад чиг",
        "other function",
        "other staff",
    ),
}

EMPLOYEE_DIRECTORY_INTENT_TOKENS = {
    "мэдээлэл",
    "medeelel",
    "жагсаалт",
    "jagsaalt",
    "нэр",
    "нэрс",
    "list",
    "хэн",
    "хэдэн",
    "heden",
    "утас",
    "phone",
    "contact",
    "холбоо",
    "email",
    "mail",
    "байна",
    "baina",
    "байнуу",
    "bainuu",
    "хаяг",
    "address",
    "дүүрэг",
    "district",
    "амьдардаг",
    "amdardag",
    "байдаг",
    "baidag",
    "гэрийн",
    "horoo",
    "хороо",
}

EMPLOYEE_FOLLOWUP_STOPWORDS = {
    "ner",
    "neriig",
    "ners",
    "neriig",
    "nersiig",
    "list",
    "jagsaalt",
    "garga",
    "gargaad",
    "haruul",
    "haruulaad",
    "gargaj",
    "gargah",
    "gargaya",
    "gargii",
    "og",
    "uguu",
    "uug",
    "ug",
    "hunii",
    "khunii",
    "name",
    "names",
    "gar",
}


def is_followup_only_employee_token(token: str) -> bool:
    cleaned = str(token or "").strip().lower()
    if not cleaned or cleaned.isdigit():
        return True
    if cleaned in EMPLOYEE_FOLLOWUP_STOPWORDS:
        return True
    return cleaned.startswith(("garga", "haruul", "jagsaa"))

EMPLOYEE_ADDRESS_HINT_TOKENS = (
    "хаяг",
    "address",
    "гэрийн",
    "дүүрэг",
    "district",
    "хороо",
    "horoo",
    "амьдардаг",
    "amdardag",
    "байдаг",
    "baidag",
    "оршин",
    "residence",
    "living",
)

EMPLOYEE_DISTRICT_HINTS = (
    "схд",
    "бзд",
    "сбд",
    "худ",
    "чд",
    "бгд",
    "нхд",
    "сонгинохайрхан",
    "сонгино хайрхан",
    "баянзүрх",
    "сүхбаатар",
    "сухбаатар",
    "хан-уул",
    "хан уул",
    "чингэлтэй",
    "баянгол",
    "налайх",
    "багануур",
    "багахангай",
    "skhd",
    "bzd",
    "sbd",
    "hud",
    "chd",
    "bgd",
    "nkhd",
)

PATIENT_QUERY_HINT_TOKENS = (
    "өвчтөн",
    "patient",
    "шинжилгээ",
    "shinjilgee",
    "хариу",
    "hariu",
    "онош",
    "onosh",
    "үзлэг",
    "uzeleg",
    "эмчилгээ",
    "emchilgee",
    "зөвлөгөө",
    "zuvluguu",
)


def strip_employee_suffix(token: str) -> str:
    current = str(token or "").strip().lower()
    suffixes = (
        "nuudiin",
        "nuudyn",
        "uudiin",
        "uudyn",
        "nuudin",
        "uudin",
        "nuud",
        "uud",
        "nariin",
        "naryn",
        "nar",
        "үүдийн",
        "уудын",
        "нуудын",
        "үүд",
        "ууд",
        "нууд",
        "нарын",
        "нар",
    )
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if len(current) > len(suffix) + 2 and current.endswith(suffix):
                current = current[: -len(suffix)]
                changed = True
                break
    return strip_name_suffix(current)


def normalize_employee_lookup_token(token: str) -> str:
    lowered = str(token or "").strip().lower()
    if not lowered:
        return ""
    cyrillic_trimmed = strip_employee_suffix(lowered)
    transliterated = transliterate_cyrillic_to_latin(cyrillic_trimmed)
    return strip_employee_suffix(transliterated)


def is_employee_question(normalized: str) -> bool:
    return any(
        key in normalized
        for key in ("ажилч", "ажилтан", "employee", "staff", "personnel")
    )


def is_employee_contact_question(normalized: str) -> bool:
    return any(
        key in normalized
        for key in ("утас", "phone", "email", "mail", "имэйл", "и мэйл", "холбоо", "contact")
    )


def is_employee_address_question(normalized: str) -> bool:
    return any(token in normalized for token in EMPLOYEE_ADDRESS_HINT_TOKENS)


def recent_employee_context(history_messages: list[dict[str, Any]] | None = None) -> bool:
    history_messages = history_messages or []
    recent_messages = history_messages[-6:]
    for message in reversed(recent_messages):
        text = normalize_question_for_intent(str(message.get("text", "") or ""))
        if is_employee_question(text) or detect_employee_category_keys(text):
            return True
        if is_employee_address_question(text):
            return True
        if any(token in text for token in EMPLOYEE_DIRECTORY_INTENT_TOKENS) and any(
            token in text for token in collect_employee_role_tokens()
        ):
            return True
    return False


def is_employee_directory_question(
    question: str,
    normalized: str,
    history_messages: list[dict[str, Any]] | None = None,
) -> bool:
    if any(token in normalized for token in PATIENT_QUERY_HINT_TOKENS):
        return False
    if is_employee_question(normalized) or bool(detect_employee_category_keys(normalized)):
        return True
    if is_employee_count_phrase(normalized):
        return True
    if has_employee_address_intent(normalized):
        return True
    if has_employee_role_intent(normalized):
        return True
    if recent_employee_context(history_messages) and any(token in normalized for token in EMPLOYEE_DIRECTORY_INTENT_TOKENS):
        return True
    return False


def is_employee_count_phrase(normalized: str) -> bool:
    has_count_shape = "хэдэн" in normalized and "хүн" in normalized
    has_employment_hint = any(
        token in normalized
        for token in ("ажилладаг", "ажиллах", "ажилла", "work", "working", "employee")
    )
    has_org_hint = any(
        token in normalized
        for token in ("эмнэлэг", "clinic", "sos medica", "sosmedica", "сос медика")
    )
    return has_count_shape and has_employment_hint and has_org_hint


def has_employee_address_intent(normalized: str) -> bool:
    if not is_employee_address_question(normalized):
        return False
    if is_employee_question(normalized):
        return True
    if any(hint in normalized for hint in EMPLOYEE_DISTRICT_HINTS):
        return True
    return False


def detect_employee_category_keys(normalized: str) -> list[str]:
    matches: list[str] = []
    for category_key, hints in EMPLOYEE_CATEGORY_HINTS.items():
        if any(hint in normalized for hint in hints):
            matches.append(category_key)
    return matches


def build_employee_full_name(employee: dict[str, Any], language: str = "mn") -> str:
    if language == "en":
        first = normalize_whitespace(str(employee.get("firstNameEn", "") or ""))
        last = normalize_whitespace(str(employee.get("lastNameEn", "") or ""))
    else:
        first = normalize_whitespace(str(employee.get("firstNameMn", "") or ""))
        last = normalize_whitespace(str(employee.get("lastNameMn", "") or ""))

    full = " ".join(part for part in (last, first) if part).strip()
    if full:
        return full

    fallback_language = "en" if language == "mn" else "mn"
    if fallback_language != language:
        return build_employee_full_name(employee, fallback_language)
    return ""


def build_employee_name_candidates(employee: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    for language in ("mn", "en"):
        first = normalize_whitespace(str(employee.get(f"firstName{language.upper()}", "") or ""))
        last = normalize_whitespace(str(employee.get(f"lastName{language.upper()}", "") or ""))
        if first and last:
            candidates.extend([f"{last} {first}", f"{first} {last}"])
        full = build_employee_full_name(employee, language)
        if full:
            candidates.append(full)
    return list(dict.fromkeys(candidate for candidate in candidates if candidate))


def build_employee_search_blob(employee: dict[str, Any]) -> tuple[str, set[str]]:
    fields = [
        *build_employee_name_candidates(employee),
        str(employee.get("categoryNameMn", "") or ""),
        str(employee.get("categoryNameEn", "") or ""),
        str(employee.get("positionMn", "") or ""),
        str(employee.get("positionEn", "") or ""),
        str(employee.get("emailPrimary", "") or ""),
        str(employee.get("emailSecondary", "") or ""),
        str(employee.get("phonePrimary", "") or ""),
        str(employee.get("phoneSecondary", "") or ""),
        str(employee.get("dutyPhone", "") or ""),
        str(employee.get("registerNumber", "") or ""),
        str(employee.get("homeAddress", "") or ""),
        str(employee.get("notes", "") or ""),
        str(employee.get("extraInfo", "") or ""),
        str(employee.get("sourceSheet", "") or ""),
    ]
    raw_text = " ".join(field for field in fields if field).strip().lower()
    normalized_text = normalize_question_for_intent(raw_text)
    transliterated_text = transliterate_cyrillic_to_latin(raw_text)
    tokens = {
        normalized_token
        for token in tokenize(f"{raw_text} {normalized_text} {transliterated_text}")
        if (normalized_token := normalize_employee_lookup_token(token))
    }
    return raw_text, tokens


def collect_employee_role_tokens() -> set[str]:
    tokens: set[str] = set()
    for employee in list_employees():
        raw_fields = [
            str(employee.get("positionMn", "") or ""),
            str(employee.get("positionEn", "") or ""),
        ]
        for raw_field in raw_fields:
            lowered = raw_field.lower()
            normalized_field = normalize_question_for_intent(lowered)
            transliterated_field = transliterate_cyrillic_to_latin(lowered)
            for token in tokenize(f"{lowered} {normalized_field} {transliterated_field}"):
                cleaned = normalize_employee_lookup_token(token)
                if len(cleaned) >= 4 and cleaned not in EMPLOYEE_QUERY_STOPWORDS:
                    tokens.add(cleaned)
    return tokens


def has_employee_role_intent(normalized: str) -> bool:
    role_tokens = collect_employee_role_tokens()
    if not role_tokens:
        return False
    normalized_tokens = {strip_name_suffix(token) for token in tokenize(normalized)}
    if not normalized_tokens.intersection(role_tokens):
        return False
    return any(token in normalized for token in EMPLOYEE_DIRECTORY_INTENT_TOKENS)


def extract_employee_query_tokens(question: str) -> list[str]:
    tokens = [
        normalize_employee_lookup_token(token)
        for token in extract_query_tokens(question)
    ]
    filtered = [
        token
        for token in tokens
        if token
        and token not in EMPLOYEE_QUERY_STOPWORDS
        and not token.startswith(("ajilch", "ajilt", "medeelel", "jagsaalt", "bugd", "heden", "niit", "khun", "ajillad", "emneleg", "manai", "baid", "amdard", "medik", "medic", "mongol"))
    ]
    return list(dict.fromkeys(filtered))


def has_explicit_employee_filters(question: str, normalized: str) -> bool:
    if extract_person_query(question):
        return True
    if detect_employee_category_keys(normalized):
        return True
    if has_employee_address_intent(normalized):
        return True
    if has_employee_role_intent(normalized):
        return True
    query_tokens = [
        token
        for token in extract_employee_query_tokens(question)
        if token
        and not is_followup_only_employee_token(token)
    ]
    return bool(query_tokens)


def build_effective_employee_query(
    question: str,
    normalized: str,
    history_messages: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    if has_explicit_employee_filters(question, normalized):
        return question, normalized

    history_messages = history_messages or []
    prior_messages = list(history_messages)
    if prior_messages and prior_messages[-1].get("role") == "user":
        last_text = normalize_whitespace(str(prior_messages[-1].get("text", "") or ""))
        if last_text == normalize_whitespace(question):
            prior_messages = prior_messages[:-1]

    for message in reversed(prior_messages[-8:]):
        if message.get("role") != "user":
            continue
        prior_question = normalize_whitespace(str(message.get("text", "") or ""))
        if not prior_question:
            continue
        prior_normalized = normalize_question_for_intent(prior_question)
        if not has_explicit_employee_filters(prior_question, prior_normalized):
            continue
        if not (
            is_employee_question(prior_normalized)
            or is_employee_count_phrase(prior_normalized)
            or has_employee_address_intent(prior_normalized)
            or has_employee_role_intent(prior_normalized)
            or detect_employee_category_keys(prior_normalized)
        ):
            continue
        combined_question = f"{prior_question}\n{question}"
        return combined_question, normalize_question_for_intent(combined_question)

    return question, normalized


def score_employee_match(employee: dict[str, Any], person_query: dict[str, Any] | None) -> int:
    if not person_query:
        return 0

    required_matches = len(person_query["tokens"])
    if required_matches < 1:
        return 0

    best_score = 0
    for candidate_text in build_employee_name_candidates(employee):
        candidate = normalize_person_phrase(candidate_text)
        if not candidate["tokens"]:
            continue
        if person_query["key"] and person_query["key"] in candidate["key"]:
            best_score = max(best_score, 120)
            continue

        matched_tokens = {
            query_token
            for query_token in person_query["tokens"]
            if any(tokens_match(query_token, candidate_token) for candidate_token in candidate["tokens"])
        }
        if len(matched_tokens) >= required_matches:
            best_score = max(best_score, 95 + len(matched_tokens))
        elif matched_tokens:
            best_score = max(best_score, 50 + len(matched_tokens) * 12)
    return best_score


def find_employee_matches(
    question: str,
    normalized: str,
    history_messages: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    employees = list_employees()
    if not employees:
        return []

    effective_question, effective_normalized = build_effective_employee_query(
        question,
        normalized,
        history_messages,
    )

    category_keys = detect_employee_category_keys(effective_normalized)
    if category_keys:
        employees = [employee for employee in employees if employee.get("categoryKey") in category_keys]

    person_query = extract_person_query(effective_question)
    query_tokens = extract_employee_query_tokens(effective_question)
    wants_directory = is_employee_directory_question(question, normalized, history_messages)

    ranked: list[dict[str, Any]] = []
    for employee in employees:
        _, token_set = build_employee_search_blob(employee)
        person_score = score_employee_match(employee, person_query) if person_query else 0
        if person_query and person_score <= 0:
            continue

        matched_tokens: list[str] = []
        score = person_score
        for token in query_tokens:
            if token in token_set:
                score += 4
                matched_tokens.append(token)
                continue
            if any(tokens_match(token, candidate_token) for candidate_token in token_set):
                score += 2
                matched_tokens.append(token)

        if query_tokens and not matched_tokens and person_score <= 0:
            continue
        if not query_tokens and not person_query:
            score = max(score, 1 if wants_directory or category_keys else 0)
        if score <= 0:
            continue

        ranked.append(
            {
                **employee,
                "employeeScore": score,
                "employeeMatchedTokens": list(dict.fromkeys(matched_tokens)),
                "employeePersonMatchScore": person_score,
            }
        )

    ranked.sort(
        key=lambda employee: (
            -int(employee.get("employeeScore", 0) or 0),
            str(employee.get("categoryNameMn", "") or ""),
            int(employee.get("sortOrder", 0) or 0),
        )
    )
    return ranked


def build_employee_heading(matches: list[dict[str, Any]], normalized: str, fallback: str) -> str:
    category_keys = detect_employee_category_keys(normalized)
    if len(category_keys) == 1:
        category_name = str(matches[0].get("categoryNameMn", "") or "")
        if category_name:
            return category_name
    if matches:
        categories = {str(employee.get("categoryNameMn", "") or "") for employee in matches if employee.get("categoryNameMn")}
        if len(categories) == 1:
            return next(iter(categories))
    return fallback


def build_employee_contact_text(employee: dict[str, Any]) -> str:
    contacts = [
        str(employee.get("emailPrimary", "") or "").strip(),
        str(employee.get("emailSecondary", "") or "").strip(),
        str(employee.get("phonePrimary", "") or "").strip(),
        str(employee.get("phoneSecondary", "") or "").strip(),
        str(employee.get("dutyPhone", "") or "").strip(),
    ]
    contacts = [contact for contact in contacts if contact]
    return " · ".join(dict.fromkeys(contacts)) if contacts else "-"


def build_employee_address_text(employee: dict[str, Any]) -> str:
    return str(employee.get("homeAddress", "") or "").strip() or "-"


def format_employee_list_line(
    employee: dict[str, Any],
    contact_requested: bool = False,
    address_requested: bool = False,
) -> str:
    name = build_employee_full_name(employee, "mn") or build_employee_full_name(employee, "en") or "Нэргүй ажилтан"
    if contact_requested:
        return f"{name} - {build_employee_contact_text(employee)}"
    if address_requested:
        return f"{name} - {build_employee_address_text(employee)}"

    position = str(employee.get("positionMn") or employee.get("positionEn") or employee.get("categoryNameMn") or "-")
    return f"{name} - {position}"


def build_employee_match_summary(matches: list[dict[str, Any]], normalized: str) -> str:
    heading = build_employee_heading(matches, normalized, fallback="Ажилтны хүснэгтээс олдсон бүртгэлүүд")
    visible = matches[:8]
    address_requested = is_employee_address_question(normalized)
    lines = [
        f"{index + 1}. {format_employee_list_line(employee, address_requested=address_requested)}"
        for index, employee in enumerate(visible)
    ]
    tail = (
        f"\n\nНийт {len(matches)} бүртгэл олдлоо. Дээр эхний 8-г үзүүлэв."
        if len(matches) > 8
        else f"\n\nНийт {len(matches)} бүртгэл олдлоо."
    )
    return f"{heading}:\n\n" + "\n".join(lines) + tail


def build_employee_contact_list_answer(matches: list[dict[str, Any]], normalized: str) -> str:
    heading = build_employee_heading(matches, normalized, fallback="Ажилтнуудын холбоо барих мэдээлэл")
    visible = matches[:12]
    lines = [
        f"{index + 1}. {build_employee_full_name(employee, 'mn') or build_employee_full_name(employee, 'en') or 'Нэргүй ажилтан'} - {build_employee_contact_text(employee)}"
        for index, employee in enumerate(visible)
    ]
    tail = (
        f"\n\nНийт {len(matches)} бүртгэл олдлоо. Дээр эхний 12-г үзүүлэв."
        if len(matches) > 12
        else f"\n\nНийт {len(matches)} бүртгэл олдлоо."
    )
    return f"{heading}:\n\n" + "\n".join(lines) + tail


def build_single_employee_answer(employee: dict[str, Any]) -> str:
    full_name_mn = build_employee_full_name(employee, "mn")
    full_name_en = build_employee_full_name(employee, "en")
    display_name = full_name_mn or full_name_en or "Ажилтан"

    details: list[str] = []
    if full_name_en and full_name_en != display_name:
        details.append(f"- Англи нэр: {full_name_en}")
    if employee.get("categoryNameMn"):
        details.append(f"- Ангилал: {employee['categoryNameMn']}")
    if employee.get("positionMn") or employee.get("positionEn"):
        details.append(f"- Албан тушаал: {employee.get('positionMn') or employee.get('positionEn')}")
    if employee.get("positionEn") and employee.get("positionEn") != employee.get("positionMn"):
        details.append(f"- Position (EN): {employee['positionEn']}")
    if employee.get("registerNumber"):
        details.append(f"- Регистр: {employee['registerNumber']}")
    if employee.get("emailPrimary") or employee.get("emailSecondary"):
        details.append(f"- И-мэйл: {' · '.join(value for value in [employee.get('emailPrimary'), employee.get('emailSecondary')] if value)}")
    if employee.get("phonePrimary") or employee.get("phoneSecondary") or employee.get("dutyPhone"):
        details.append(
            "- Утас: "
            + " · ".join(
                value
                for value in [employee.get("phonePrimary"), employee.get("phoneSecondary"), employee.get("dutyPhone")]
                if value
            )
        )
    if employee.get("dateOfBirth"):
        details.append(f"- Төрсөн огноо: {employee['dateOfBirth']}")
    if employee.get("hireDate"):
        details.append(f"- Ажилд орсон огноо: {employee['hireDate']}")
    if employee.get("homeAddress"):
        details.append(f"- Гэрийн хаяг: {employee['homeAddress']}")
    if employee.get("notes"):
        details.append(f"- Тэмдэглэл: {employee['notes']}")
    if employee.get("extraInfo"):
        details.append(f"- Нэмэлт мэдээлэл: {employee['extraInfo']}")

    body = "\n".join(details) if details else "- Нэмэлт хадгалсан талбар одоогоор алга."
    return f"{display_name}-ийн мэдээллийг ажилтны хүснэгтээс оллоо.\n\n{body}"


def build_employee_answer(
    question: str,
    normalized: str,
    history_messages: list[dict[str, Any]] | None = None,
) -> str | None:
    if not is_employee_directory_question(question, normalized, history_messages):
        return None
    if is_count_question(normalized) or is_list_question(normalized):
        return None

    matches = find_employee_matches(question, normalized, history_messages)
    if not matches:
        return None

    person_query = extract_person_query(question)
    if person_query:
        top_match = matches[0]
        runner_up_score = int(matches[1].get("employeeScore", 0) or 0) if len(matches) > 1 else 0
        top_score = int(top_match.get("employeeScore", 0) or 0)
        if top_score >= 95 and top_score >= runner_up_score + 8:
            return build_single_employee_answer(top_match)
        return build_employee_match_summary(matches[:5], normalized)

    top_match = matches[0]
    runner_up_score = int(matches[1].get("employeeScore", 0) or 0) if len(matches) > 1 else 0
    top_score = int(top_match.get("employeeScore", 0) or 0)
    query_tokens = extract_employee_query_tokens(question)
    if len(query_tokens) >= 2 and top_score >= 6 and top_score >= runner_up_score + 3:
        return build_single_employee_answer(top_match)

    if len(matches) == 1:
        return build_single_employee_answer(matches[0])
    if is_employee_contact_question(normalized):
        return build_employee_contact_list_answer(matches, normalized)
    return build_employee_match_summary(matches, normalized)


def document_matches_employee_intent(document: dict[str, Any]) -> bool:
    title = str(document.get("title", "")).lower()
    folder = str(document.get("folder", "")).lower()
    summary = str(document.get("summary", "")).lower()
    return (
        any(key in folder for key in ("ажилч", "ажилтан", "employee", "staff", "personnel"))
        or any(key in title for key in ("ажилч", "ажилтан", "employee", "staff", "personnel", "emp.info", "emp_"))
        or title.endswith((".xlsx", ".xls", ".csv")) and any(key in summary for key in ("ажилч", "ажилтан", "employee", "staff", "personnel"))
    )


def count_employee_rows(document: dict[str, Any]) -> int:
    spreadsheet_rows = count_spreadsheet_data_rows(str(document.get("storagePath", "") or ""))
    if spreadsheet_rows > 0:
        return spreadsheet_rows

    lines = [
        line.strip()
        for line in str(document.get("content", "")).splitlines()
        if line.strip()
    ]
    if len(lines) <= 1:
        return 0
    return max(0, len(lines) - 1)
