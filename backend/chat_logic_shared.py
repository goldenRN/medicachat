from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from .text_utils import extract_name_from_title, normalize_whitespace, tokenize


QUESTION_STOPWORDS = {
    "baina",
    "bainuu",
    "bnu",
    "baigaa",
    "bgaa",
    "yu",
    "ve",
    "talaar",
    "tuhai",
    "gedeg",
    "medeelel",
    "medeelel",
    "bichig",
    "file",
    "files",
    "barimt",
    "barimtuud",
    "байна",
    "уу",
    "юу",
    "вэ",
    "талаар",
    "тухай",
    "гэдэг",
    "мэдээлэл",
    "баримт",
    "баримтууд",
}

GREETING_TOKENS = {
    "hi",
    "hello",
    "hey",
    "sain",
    "sn",
    "айн",
    "сайн",
    "мэнд",
}

TODAY_TOKENS = {
    "onoodor",
    "unuudur",
    "unuudur",
    "today",
    "өнөөдөр",
}

PERSON_QUERY_STOPWORDS = {
    "gedeg",
    "hun",
    "hunii",
    "ovchton",
    "ovchtonii",
    "uvchtun",
    "uvchtunii",
    "heden",
    "kheden",
    "hed",
    "khed",
    "nas",
    "nastai",
    "shinjilgee",
    "shinjilgee",
    "shinjilgeenii",
    "shinjilgeeny",
    "hariu",
    "ur",
    "dun",
    "result",
    "vaccination",
    "vaccine",
    "vaccines",
    "эмнэлэг",
    "эмнэлгийн",
    "шинжилгээ",
    "шинжилгээний",
    "хариу",
    "үр",
    "дүн",
    "үрдүн",
    "дүнг",
    "хэдэн",
    "хэд",
    "нас",
    "настай",
    "үзлэг",
    "үзүүлэлт",
    "баримт",
    "баримтаас",
    "баримтын",
    "barimt",
    "barimtaas",
    "barimtiin",
    "emchid",
    "anhaarah",
    "gol",
    "zuil",
    "zuiliig",
    "tovch",
    "garga",
    "gargaad",
    "og",
    "эмчид",
    "анхаарах",
    "гол",
    "зүйл",
    "зүйлийг",
    "товч",
    "гарга",
    "өг",
}

PERSON_QUERY_HINTS = {
    "gedeg",
    "ovchton",
    "ovchtonii",
    "uvchtun",
    "uvchtunii",
    "patient",
    "гэдэг",
    "өвчтөн",
    "өвчтөний",
}

NON_PERSON_QUERY_PHRASES = {
    "hun am",
    "hyn am",
    "population",
    "хүн ам",
}

PERSON_BOUNDARY_KEYWORDS = {
    "heden",
    "kheden",
    "hed",
    "khed",
    "nas",
    "nastai",
    "баримт",
    "баримтаас",
    "баримтын",
    "шинжилгээ",
    "шинжилгээний",
    "хариу",
    "үр",
    "дүн",
    "эмчид",
    "анхаарах",
    "дүгнэлт",
    "онош",
    "зөвлөгөө",
    "barimt",
    "barimtaas",
    "barimtiin",
    "shinjilgee",
    "shinjilgeenii",
    "hariu",
    "ur",
    "dun",
    "хэдэн",
    "хэд",
    "нас",
    "настай",
    "emchid",
    "anhaarah",
}

CYRILLIC_TO_LATIN_MAP = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "yo",
    "ж": "j",
    "з": "z",
    "и": "i",
    "й": "i",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "ө": "u",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ү": "u",
    "ф": "f",
    "х": "kh",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sh",
    "ъ": "",
    "ы": "i",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


def extract_query_tokens(question: str) -> list[str]:
    normalized = normalize_question_for_intent(question)
    tokens = tokenize(f"{question} {normalized}")
    filtered = [token for token in tokens if token not in QUESTION_STOPWORDS]
    return list(dict.fromkeys(filtered))


def collect_search_terms(question: str) -> list[str]:
    query_tokens = extract_query_tokens(question)
    person_query = extract_person_query(question)
    person_tokens = person_query["tokens"] if person_query else []
    terms = [*person_tokens, *query_tokens]
    return list(dict.fromkeys(term for term in terms if term))


def transliterate_cyrillic_to_latin(text: str) -> str:
    return "".join(CYRILLIC_TO_LATIN_MAP.get(char, char) for char in str(text).lower())


def strip_name_suffix(token: str) -> str:
    current = str(token or "").strip().lower()
    suffixes = (
        "iin",
        "iinh",
        "iinhii",
        "yn",
        "in",
        "nii",
        "ni",
        "ii",
        "ын",
        "ийн",
        "ний",
        "ны",
        "ынх",
        "ийнх",
    )
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if len(current) > len(suffix) + 2 and current.endswith(suffix):
                current = current[: -len(suffix)]
                changed = True
                break
    return current


def tokens_match(query_token: str, candidate_token: str) -> bool:
    left = strip_name_suffix(query_token)
    right = strip_name_suffix(candidate_token)
    if not left or not right:
        return False
    if left == right:
        return True

    shorter, longer = sorted((left, right), key=len)
    if len(shorter) < 5 or not longer.startswith(shorter):
        return False

    remainder = longer[len(shorter) :]
    return remainder in {"i", "ii", "in", "iin", "n", "ni", "nii", "d", "t", "g", "ig"}


def build_token_variants(tokens: list[str]) -> set[str]:
    variants = {token for token in tokens if token}
    for index in range(len(tokens) - 1):
        variants.add(tokens[index] + tokens[index + 1])
    if len(tokens) >= 3:
        variants.add("".join(tokens))
    return variants


def normalize_person_phrase(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    transliterated = transliterate_cyrillic_to_latin(raw)
    cleaned = re.sub(r"[\(\)\[\],.:/]+", " ", transliterated)
    base_tokens = [
        strip_name_suffix(token)
        for token in re.split(r"[^a-z0-9]+", cleaned)
        if len(token) > 1
    ]
    tokens = [token for token in base_tokens if token and token not in PERSON_QUERY_STOPWORDS]
    return {
        "raw": raw,
        "tokens": tokens,
        "variants": build_token_variants(tokens),
        "key": "".join(tokens),
        "text": " ".join(tokens),
    }


def extract_person_query(question: str) -> dict[str, Any] | None:
    question_text = str(question or "").strip()
    normalized_question = normalize_question_for_intent(question_text)
    if any(phrase in normalized_question for phrase in NON_PERSON_QUERY_PHRASES):
        return None
    has_person_hint = any(hint in normalized_question for hint in PERSON_QUERY_HINTS)
    patterns = [
        r"\b([A-Za-zА-Яа-яӨөҮүЁё0-9\-]+?)\s*(?:iin|iinh|yn|in|ийн|ын|ний|ны)\s+(?:мэдээлэл|medeelel|баримт|barimt|шинжилгээ|shinjilgee)",
        r"([A-Za-zА-Яа-яӨөҮүЁё0-9\- ]+?)\s+(?:шинжилгээ(?:ний)?|хариу|үр\s*дүн)",
        r"([A-Za-zА-Яа-яӨөҮүЁё0-9\- ]+?)\s+(?:shinjilgee(?:nii|ni)?|hariu|ur\s*dun|result)",
        r"([A-Za-zА-Яа-яӨөҮүЁё0-9\- ]+?)\s+(?:баримт(?:аас|ын)?|эмчид|анхаарах|дүгнэлт|онош|зөвлөгөө)",
        r"([A-Za-zА-Яа-яӨөҮүЁё0-9\- ]+?)\s+(?:barimt(?:aas|iin)?|emchid|anhaarah|dugnelt|onosh|zuvluguu)",
    ]
    for pattern in patterns:
        match = re.search(pattern, question_text, re.I)
        if match:
            normalized = normalize_person_phrase(match.group(1))
            if len(normalized["tokens"]) >= 2:
                return normalized

    question_tokens = [token for token in re.split(r"\s+", question_text) if token]
    collected: list[str] = []
    for token in question_tokens:
        normalized_token = strip_name_suffix(transliterate_cyrillic_to_latin(token))
        if normalized_token in PERSON_BOUNDARY_KEYWORDS:
            break
        collected.append(token)
        if len(collected) == 4:
            break

    if has_person_hint and len(collected) >= 2:
        normalized = normalize_person_phrase(" ".join(collected))
        if len(normalized["tokens"]) >= 2:
            return normalized

    normalized = normalize_person_phrase(question_text)
    if has_person_hint and len(normalized["tokens"]) == 1 and len(normalized["tokens"][0]) >= 4:
        return normalized
    return None


def normalize_question_for_intent(question: str) -> str:
    normalized = str(question or "").lower()
    replacements = [
        (r"\bemnel(?:egiin|giin|eg|gi)?\b", " эмнэлэг "),
        (r"\bajilch(?:id|diin|in|nii)?\b", " ажилчид "),
        (r"\bajilt(?:an|nii|nuud)?\b", " ажилтан "),
        (r"\bajilladag\b", " ажилладаг "),
        (r"\bajildag\b", " ажилладаг "),
        (r"\bners(?:iig|uud|ee|iin)?\b", " нэрс "),
        (r"\bner(?:siin)?\b", " нэр "),
        (r"\bbugdiig\b", " бүгдийг "),
        (r"\bbugd(?:iig|iin|)?\b", " бүгд "),
        (r"\bharuulaad\b", " харуулаад "),
        (r"\bharuul(?:ya|aad|ah)?\b", " харуул "),
        (r"\bog\b", " өг "),
        (r"\bheden\b", " хэдэн "),
        (r"\bhed\b", " хэд "),
        (r"\bhun\b", " хүн "),
        (r"\buvchtun\b", " өвчтөн "),
        (r"\bovchtun\b", " өвчтөн "),
        (r"\buzuulsen\b", " үзүүлсэн "),
        (r"\buzeulsen\b", " үзүүлсэн "),
        (r"\bhenhen\b", " хэн хэн "),
        (r"\bhen\b", " хэн "),
        (r"\bjagsaalt\b", " жагсаалт "),
        (r"\builchluulegch(?:diin|id|)?\b", " үйлчлүүлэгч "),
        (r"\bviziin\b", " визийн "),
        (r"\bamerikiin\b", " америкийн "),
        (r"\bamerika?n?\b", " америк "),
        (r"\busa\b", " usa "),
        (r"\bmedeelle?l?\b", " мэдээлэл "),
        (r"\bbainu+u?\b", " байна уу "),
        (r"\bbaigaa\s*yu\b", " байна уу "),
        (r"\bsariin\b", " сарын "),
        (r"\bsar(?:iin)?\b", " сар "),
        (r"\bnd\b", " нд "),
    ]
    for pattern, replacement in replacements:
        normalized = re.sub(pattern, replacement, normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def is_greeting_question(question: str, normalized: str) -> bool:
    raw = normalize_whitespace(str(question or "").lower())
    if raw in {"hi", "hello", "hey", "sain uu", "sain baina uu", "сайн уу", "мэнд"}:
        return True

    tokens = set(tokenize(f"{raw} {normalized}"))
    if not tokens:
        return raw in {"hi", "yo", "ok", "hey"}
    return bool(tokens & GREETING_TOKENS) and len(tokens) <= 4


def build_greeting_answer() -> str:
    return "Сайн байна уу? Танд юугаар туслах вэ?"


def is_today_question(question: str, normalized: str) -> bool:
    raw = normalize_whitespace(str(question or "").lower())
    merged = f"{raw} {normalized}"
    has_today_token = any(token in merged for token in TODAY_TOKENS)
    has_date_phrase = any(
        phrase in merged
        for phrase in (
            "heden sariin heden",
            "hednii odor",
            "what day",
            "what date",
            "хэдэн сарын хэдэн",
            "хэдний өдөр",
            "ямар өдөр",
            "ямар сар",
        )
    )
    return has_today_token and has_date_phrase


def build_today_answer() -> str:
    today = datetime.now()
    return f"Өнөөдөр {today.year} оны {today.month} сарын {today.day}."


def is_count_question(normalized: str) -> bool:
    return "хэдэн" in normalized and any(
        key in normalized
        for key in ("хүн", "өвчтөн", "үзүүлсэн", "ирсэн", "баримт", "ажилч", "ажилтан", "employee", "staff", "personnel")
    )


def is_list_question(normalized: str) -> bool:
    return any(
        key in normalized
        for key in ("жагсаалт", "нэрс", "хэн хэн", "хэн", "үйлчлүүлэгч", "бүгд", "bugd")
    )


def resolve_requested_date(normalized: str, history_messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    own = extract_question_date(normalized)
    if own:
        return own

    for message in reversed([message for message in history_messages if message["role"] == "user"]):
        inherited = extract_question_date(normalize_question_for_intent(message["text"]))
        if inherited:
            return inherited
    return None


def extract_question_date(normalized: str) -> dict[str, Any] | None:
    explicit = re.search(r"(20\d{2})[.\-/ ]*(\d{1,2})[.\-/ ]*(\d{1,2})", normalized)
    if explicit:
        return build_date_descriptor(int(explicit.group(1)), int(explicit.group(2)), int(explicit.group(3)))

    month_word = re.search(r"(\d{1,2})\s*(?:сарын|сар(?:ын)?)\s*(\d{1,2})", normalized)
    if month_word:
        return build_date_descriptor(None, int(month_word.group(1)), int(month_word.group(2)))

    month_slash = re.search(r"(\d{1,2})\s*[\/.-]\s*(\d{1,2})", normalized)
    if month_slash:
        return build_date_descriptor(None, int(month_slash.group(1)), int(month_slash.group(2)))

    return None


def build_date_descriptor(year: int | None, month: int, day: int) -> dict[str, Any] | None:
    if not month or not day:
        return None
    return {
        "year": year,
        "month": month,
        "day": day,
        "paddedMonth": f"{month:02d}",
        "paddedDay": f"{day:02d}",
        "label": f"{month} сарын {day}",
    }


def document_matches_date(document: dict[str, Any], descriptor: dict[str, Any] | None) -> bool:
    if not descriptor:
        return False
    haystack = f"{document['title']}\n{document['summary']}\n{document['content']}".lower()
    month = descriptor["month"]
    day = descriptor["day"]
    mm_slash_dd = f"{month}/{day}"
    mm_slash_dd_year = (
        f"{month}/{day}/{descriptor['year']}" if descriptor["year"] else None
    )
    yyyy_mm_dd = (
        f"{descriptor['year']}{descriptor['paddedMonth']}{descriptor['paddedDay']}"
        if descriptor["year"]
        else None
    )
    yyyy_dot = (
        f"{descriptor['year']}.{descriptor['paddedMonth']}.{descriptor['paddedDay']}"
        if descriptor["year"]
        else None
    )
    dash_patterns = [
        f"-{month}-{day}",
        f"-{descriptor['paddedMonth']}-{descriptor['paddedDay']}",
    ]
    if any(pattern in haystack for pattern in dash_patterns):
        return True
    if mm_slash_dd in haystack:
        return True
    if mm_slash_dd_year and mm_slash_dd_year in haystack:
        return True
    if yyyy_mm_dd and yyyy_mm_dd in haystack:
        return True
    if yyyy_dot and yyyy_dot in haystack:
        return True
    return False


def document_matches_usa_intent(document: dict[str, Any]) -> bool:
    haystack = f"{document['title']}\n{document['summary']}\n{document['content']}".lower()
    return any(key in haystack for key in ("usa", "u.s.", "united states", "америк"))


def extract_person_name(document: dict[str, Any]) -> str:
    text = f"{document['content']}\n{document['summary']}"
    mongolian_name = re.search(r"Нэр:\s*([^\n\r]+?)(?:\s+Хүйс:|\s+Регистр|\s+ШИНЖИЛГЭЭНИЙ|\s*$)", text, re.I)
    mongolian_parent = re.search(r"Эцэг\/эхийн нэр:\s*([^\n\r]+?)(?:\s+Нас:|\s*$)", text, re.I)
    mongolian_full_name = re.search(
        r"(?:Нэр,?\s*Овог:|ОВОГ\s+НЭР:)\s*([^\n\r]+?)(?:\s+Төрсөн|\s+ШИНЖИЛГЭЭНИЙ|\s+Нас:|\s*$)",
        text,
        re.I,
    )
    if mongolian_name:
        primary = normalize_whitespace(mongolian_name.group(1))
        parent = normalize_whitespace(mongolian_parent.group(1)) if mongolian_parent else ""
        return f"{primary} ({parent})" if parent else primary
    if mongolian_full_name:
        return normalize_whitespace(mongolian_full_name.group(1))

    english_name = re.search(r"Name:\s*([A-Z][A-Z' -]+,\s*[A-Z][A-Z' -]+)", text)
    if english_name:
        return normalize_whitespace(english_name.group(1))

    return extract_name_from_title(document["title"])


def score_person_query_match(document: dict[str, Any], person_query: dict[str, Any] | None) -> int:
    if not person_query:
        return 0

    document_candidates = [
        normalize_person_phrase(extract_person_name(document)),
        normalize_person_phrase(extract_name_from_title(document["title"])),
    ]

    required_matches = len(person_query["tokens"])
    if required_matches < 1:
        return 0

    best_score = 0
    for candidate in document_candidates:
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
        overlap = len(matched_tokens)
        if required_matches == 1 and overlap == 1:
            best_score = max(best_score, 96)
            continue
        if overlap >= required_matches:
            best_score = max(best_score, 100 + overlap)

    return best_score


def is_likely_person_document(document: dict[str, Any]) -> bool:
    title = str(document["title"]).lower()
    content = str(document["content"])
    return title.endswith(".pdf") or bool(re.search(r"Нэр:\s*|Name:\s*", content, re.I))


def dedupe_by_name(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for entry in entries:
        key = entry["name"].lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    return unique
