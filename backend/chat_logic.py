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
    "hun",
    "hunii",
    "ovchton",
    "ovchtonii",
    "uvchtun",
    "uvchtunii",
    "patient",
    "гэдэг",
    "хүн",
    "хүний",
    "өвчтөн",
    "өвчтөний",
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
    patterns = [
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
    has_person_hint = any(hint in normalized_question for hint in PERSON_QUERY_HINTS)
    if has_person_hint and len(normalized["tokens"]) == 1 and len(normalized["tokens"][0]) >= 4:
        return normalized
    return None


def normalize_question_for_intent(question: str) -> str:
    normalized = str(question or "").lower()
    replacements = [
        (r"\bemnel(?:egiin|giin|eg|gi)?\b", " эмнэлэг "),
        (r"\bajilch(?:id|diin|in|nii)?\b", " ажилчид "),
        (r"\bajilt(?:an|nii|nuud)?\b", " ажилтан "),
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


def rank_documents(question: str, documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tokens = extract_query_tokens(question)
    person_query = extract_person_query(question)
    if not tokens:
        return []

    ranked: list[dict[str, Any]] = []
    for document in documents:
        person_match_score = score_person_query_match(document, person_query) if person_query else 0
        if person_query and person_match_score <= 0:
            ranked.append({**document, "score": 0, "matchedTokens": [], "personMatchScore": 0})
            continue

        haystack = tokenize(
            f"{document['title']} {document['summary']} {document['content']} {' '.join(document.get('tags', []))}"
        )
        haystack_set = set(haystack)
        score = person_match_score
        matched_tokens: list[str] = []
        for token in tokens:
            matched = False
            if token in haystack_set:
                score += 3
                matched = True
            if token in document["title"].lower():
                score += 2
                matched = True
            if matched and token not in matched_tokens:
                matched_tokens.append(token)
        ranked.append(
            {
                **document,
                "score": score,
                "matchedTokens": matched_tokens,
                "personMatchScore": person_match_score,
            }
        )

    ranked.sort(key=lambda item: item["score"], reverse=True)
    return [document for document in ranked if document["score"] > 0]


def has_confident_match(question: str, ranked_docs: list[dict[str, Any]]) -> bool:
    if not ranked_docs:
        return False

    person_query = extract_person_query(question)
    if person_query:
        return ranked_docs[0].get("personMatchScore", 0) >= 90

    tokens = extract_query_tokens(question)
    best = ranked_docs[0]
    matched_count = len(best.get("matchedTokens", []))
    source_text = str(best.get("source", "")).lower()

    if source_text.startswith("uploaded by") and best.get("score", 0) >= 3 and matched_count >= 1:
        return True

    if len(tokens) <= 2:
        return best.get("score", 0) >= 3 and matched_count >= 1
    return best.get("score", 0) >= 6 and matched_count >= 2


def build_no_match_answer(question: str) -> str:
    normalized = normalize_question_for_intent(question)
    person_query = extract_person_query(question)
    if person_query:
        return (
            f'"{person_query["raw"]}" нэртэй хүнтэй яг тохирох баримт одоогийн индексэлсэн файлуудаас олдсонгүй.\n\n'
            "Ижил төстэй нэртэй бусад хүний PDF-ийг зориуд харуулаагүй."
        )
    if any(key in normalized for key in ("ажилчид", "ажилтан", "employee", "staff")):
        return (
            "Одоогийн индексэлсэн файлуудад эмнэлгийн ажилчдын талаар тусгай мэдээлэл олдсонгүй.\n\n"
            "Одоогийн санд ихэвчлэн өвчтөн, үзлэг, шинжилгээтэй холбоотой PDF баримтууд байна."
        )

    return (
        "Энэ асуултад тохирох мэдээлэл одоогийн индексэлсэн файлуудаас олдсонгүй.\n\n"
        "Хэрэв хүсвэл тохирох файл upload хийгээд дахин асууж болно."
    )


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


def is_detail_followup_request(question: str, normalized: str) -> bool:
    raw = str(question or "").strip().lower()
    raw_compact = re.sub(r"\s+", " ", raw)
    if not raw_compact:
        return False
    if extract_person_query(question) or is_count_question(normalized) or is_list_question(normalized):
        return False

    short_affirmations = {
        "husch baina",
        "husch bn",
        "tiim",
        "tegye",
        "tegeerei",
        "za",
        "okay",
        "ok",
        "yes",
        "yess",
        "bolno",
        "tegii",
    }
    if raw_compact in short_affirmations:
        return True

    detail_patterns = (
        "хүсч байна",
        "хүсэж байна",
        "дэлгэрэнгүй",
        "задлаад",
        "мөр мөрөөр",
        "haruulaad og",
        "gargaad og",
        "zadlaad og",
        "delgerengui",
        "mur muruur",
        "husch baina",
    )
    return any(pattern in raw_compact for pattern in detail_patterns)


def resolve_followup_context(
    question: str,
    documents: list[dict[str, Any]],
    history_messages: list[dict[str, Any]],
) -> dict[str, Any] | None:
    normalized = normalize_question_for_intent(question)
    if not is_detail_followup_request(question, normalized):
        return None

    prior_messages = history_messages[:-1] if history_messages and history_messages[-1]["role"] == "user" else history_messages
    documents_by_id = {document["id"]: document for document in documents}
    documents_by_title = {document["title"]: document for document in documents}

    for message in reversed(prior_messages):
        if message["role"] != "bot":
            continue
        citations = message.get("citations", [])
        if not citations:
            continue
        if "хэрэв хүсвэл" not in message.get("text", "").lower() and "if you want" not in message.get("text", "").lower():
            continue

        resolved: list[dict[str, Any]] = []
        for citation in citations:
            document = documents_by_id.get(citation.get("id")) or documents_by_title.get(citation.get("title"))
            if document:
                resolved.append(document)
        if resolved:
            text = message.get("text", "").lower()
            wants_structured = any(
                key in text for key in ("хүснэгт", "талбарчилсан", "table", "structured")
            ) or any(
                key in normalized for key in ("хүснэгт", "талбар", "table", "structured", "cleaner")
            )
            return {
                "documents": resolved,
                "mode": "structured" if wants_structured else "detail",
            }
    return None


def extract_document_detail_lines(document: dict[str, Any], limit: int = 8) -> list[str]:
    raw_text = str(document.get("content", "")).strip()
    formatted = re.sub(
        r"(?i)\b(Нэр,?\s*Овог:|Эцэг\/эхийн нэр:|Нэр:|Төрсөн он, сар, өдөр:|Нас:|Хүйс:|Регистрийн дугаар:|ШИНЖИЛГЭЭНИЙ ОГНОО:|Name:|Date / Time:|Test Date / Time:|Employee Information:?)",
        r"\n\1",
        raw_text,
    )
    lines = [normalize_whitespace(line) for line in formatted.splitlines() if normalize_whitespace(line)]
    cleaned_lines: list[str] = []
    for line in lines:
        if line.lower() == str(document["title"]).lower():
            continue
        if len(line) < 3:
            continue
        if cleaned_lines and cleaned_lines[-1] == line:
            continue
        cleaned_lines.append(line)
        if len(cleaned_lines) == limit:
            break
    return cleaned_lines


def build_document_detail_answer(document: dict[str, Any]) -> str:
    name = extract_person_name(document) or extract_name_from_title(document["title"])
    cleaned_lines = extract_document_detail_lines(document)
    details = "\n".join(f"- {line}" for line in cleaned_lines) if cleaned_lines else f"- {document['summary']}"
    return "\n\n".join(
        [
            f"{name}-ийн өмнөх дурдсан баримтын дэлгэрэнгүй:",
            details,
            "Хэрэв хүсвэл үүнийг илүү цэвэр хүснэгт эсвэл талбарчилсан хэлбэрээр бас гаргаж өгч болно.",
        ]
    )


def build_document_structured_answer(document: dict[str, Any]) -> str:
    name = extract_person_name(document) or extract_name_from_title(document["title"])
    detail_lines = extract_document_detail_lines(document, limit=12)
    structured_rows: list[str] = []
    extras: list[str] = []

    for line in detail_lines:
        if ":" in line:
            label, value = line.split(":", 1)
            label = normalize_whitespace(label)
            value = normalize_whitespace(value)
            if label and value:
                structured_rows.append(f"{label}: {value}")
            else:
                extras.append(line)
        else:
            extras.append(line)

    sections = [f"{name}-ийн талбарчилсан хэлбэр:"]
    if structured_rows:
        sections.append("\n".join(f"- {row}" for row in structured_rows))
    if extras:
        sections.append("Нэмэлт мэдээлэл:\n" + "\n".join(f"- {row}" for row in extras))
    sections.append("Хэрэв хүсвэл дараагийн удаа зөвхөн аль нэг талбарыг нь тусад нь шүүж гаргаж өгч болно.")
    return "\n\n".join(sections)


def select_reply_documents(
    question: str,
    ranked_docs: list[dict[str, Any]],
    all_documents: list[dict[str, Any]],
    history_messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    followup_context = resolve_followup_context(question, all_documents, history_messages)
    if followup_context:
        return followup_context["documents"][:3]
    if has_confident_match(question, ranked_docs):
        return ranked_docs[:3]
    return []


def build_answer(
    question: str,
    ranked_docs: list[dict[str, Any]],
    all_documents: list[dict[str, Any]] | None = None,
    history_messages: list[dict[str, Any]] | None = None,
) -> str:
    all_documents = all_documents or ranked_docs
    history_messages = history_messages or []
    normalized = normalize_question_for_intent(question)

    followup_context = resolve_followup_context(question, all_documents, history_messages)
    if followup_context:
        if followup_context["mode"] == "structured":
            return build_document_structured_answer(followup_context["documents"][0])
        return build_document_detail_answer(followup_context["documents"][0])

    list_answer = build_list_answer(normalized, ranked_docs, all_documents, history_messages)
    if list_answer:
        return list_answer

    aggregate_answer = build_aggregate_answer(normalized, all_documents, history_messages)
    if aggregate_answer:
        return aggregate_answer

    if is_today_question(question, normalized):
        return build_today_answer()

    if is_greeting_question(question, normalized):
        return build_greeting_answer()

    if not has_confident_match(question, ranked_docs):
        return build_no_match_answer(question)

    best = ranked_docs[0] if ranked_docs else None
    supporting = ranked_docs[1] if len(ranked_docs) > 1 else None
    person_query = extract_person_query(question)

    if person_query and best:
        matched_name = extract_person_name(best) or extract_name_from_title(best["title"])
        return "\n\n".join(
            [
                f"{matched_name}-тай хамгийн сайн таарсан баримт олдлоо.",
                best["summary"],
                "Хэрэв хүсвэл энэ хүний баримтаас дэлгэрэнгүй үзүүлэлтүүдийг мөр мөрөөр нь задлаад өгч болно.",
            ]
        )

    if "triage" in normalized or "улаан" in normalized:
        return "\n\n".join(
            filter(
                None,
                [
                    "Triage баримтаас харахад улаан ангилалд амьсгалын дутагдал, зүрхний тогтворгүй байдал, шок зэрэг амь насанд аюултай шинжүүд орно.",
                    "Ийм тохиолдолд өвчтөнийг нэн тэргүүнд үнэлж, яаралтай тусламжийн баг шууд оролцох ёстой.",
                    f"Дэмжих холбоотой баримтад {supporting['title']} мөн урьдчилсан шалгах урсгалыг сануулж байна." if supporting else "",
                ],
            )
        )

    if "хэвтэн" in normalized or "admission" in normalized:
        return "\n\n".join(
            filter(
                None,
                [
                    "Хэвтэн эмчлүүлэхийн өмнө бүртгэл, иргэний үнэмлэх, даатгалын мэдээлэл, эмийн харшлын асуумж, зөвшөөрлийн маягтыг баталгаажуулах хэрэгтэй.",
                    "Мөн өвчтөнд хоол, эмийн урьдчилсан зааврыг тайлбарлаж өгөх нь чухал байна.",
                    f"Энэ хариулт {best['title']}-д тулгуурлаж байна." if best else "",
                ],
            )
        )

    if "халдвар" in normalized or "infection" in normalized or "ppe" in normalized:
        return "\n\n".join(
            filter(
                None,
                [
                    "Халдвар хамгааллын гол зарчим нь хүрэлцэхийн өмнө болон дараа гар ариутгах, эрсдэлтэй нөхцөлд зохих хамгаалах хэрэгсэл хэрэглэх явдал байна.",
                    "Дуслын халдварын сэжигтэй үед маск, нүдний хамгаалалт, өндөр эрсдэлтэй үед нэг удаагийн бээлий ба халат нэмэлтээр хэрэглэнэ.",
                    f"Илүү дэлгэрэнгүй ишлэл: {best['content']}" if best else "",
                ],
            )
        )

    if "дүрс" in normalized or "radiology" in normalized or "өлөн" in normalized:
        return "\n\n".join(
            filter(
                None,
                [
                    "Дүрс оношилгооны өмнө тодосгогч бодисын харшлын түүх, бөөрний үзүүлэлт, жирэмсний эрсдэлийг шалгах шаардлагатай.",
                    "Зарим шинжилгээнд 6-8 цаг өлөн байх заавар ордог тул товлолт бүрт тусгайлан нягтална.",
                    f"Энэ дүгнэлт {best['title']}-оос гарч байна." if best else "",
                ],
            )
        )

    snippets = "\n".join(
        f"- {document['title']}: {document['summary']}" for document in ranked_docs[:3]
    )
    return (
        "Таны асуулттай хамгийн ойр баримтуудыг нэгтгэж хариуллаа.\n\n"
        f"{snippets}\n\n"
        "Хэрэв хүсвэл эдгээрээс аль нэг хүний дэлгэрэнгүй мэдээлэл эсвэл нэрсийн жагсаалтыг тусад нь гаргаж өгч болно."
    )


def build_list_answer(
    normalized: str,
    ranked_docs: list[dict[str, Any]],
    all_documents: list[dict[str, Any]],
    history_messages: list[dict[str, Any]],
) -> str | None:
    if not is_list_question(normalized):
        return None

    requested_date = resolve_requested_date(normalized, history_messages)
    candidates = (
        [document for document in all_documents if document_matches_date(document, requested_date)]
        if requested_date
        else list(all_documents)
    )

    if any(key in normalized for key in ("америк", "american", "usa")):
        usa_candidates = [document for document in candidates if document_matches_usa_intent(document)]
        if not usa_candidates:
            return "Америкийн визтэй холбоотой тохирох баримт олдсонгүй."
        candidates = usa_candidates

    if not requested_date:
        positive_ranked = [document for document in ranked_docs if document.get("score", 0) > 0]
        if positive_ranked:
            candidates = positive_ranked

    named_people = [
        {"name": extract_person_name(document), "title": document["title"]}
        for document in candidates
        if is_likely_person_document(document)
    ]
    named_people = [entry for entry in named_people if entry["name"]]
    unique_people = dedupe_by_name(named_people)

    if not unique_people:
        return "Энэ асуултад тохирох нэрсийн жагсаалт олдсонгүй."

    heading = (
        f"{requested_date['label']}-нд бүртгэгдсэн нэрсийн жагсаалт"
        if requested_date
        else "Олдсон нэрсийн жагсаалт"
    )
    show_all = any(key in normalized for key in ("бүгд", "bugd", "bugdiig", "all"))
    visible_people = unique_people if show_all else unique_people[:20]
    lines = [f"{index + 1}. {entry['name']}" for index, entry in enumerate(visible_people)]
    if not show_all and len(unique_people) > 20:
        tail = f"\n\nНийт {len(unique_people)} нэр олдлоо. Дээр эхний 20-г үзүүлэв."
    else:
        tail = f"\n\nНийт {len(unique_people)} нэр олдлоо."
    return f"{heading}:\n\n" + "\n".join(lines) + tail


def build_aggregate_answer(
    normalized: str,
    documents: list[dict[str, Any]],
    history_messages: list[dict[str, Any]],
) -> str | None:
    if not is_count_question(normalized):
        return None

    requested_date = resolve_requested_date(normalized, history_messages)
    if not requested_date:
        return None

    matching_documents = [document for document in documents if document_matches_date(document, requested_date)]
    if not matching_documents:
        return f"{requested_date['label']}-нд тохирох үзлэгийн баримт олдсонгүй."

    names = [
        {"name": extract_person_name(document)}
        for document in matching_documents
        if extract_person_name(document)
    ]
    names = [entry["name"] for entry in dedupe_by_name(names)[:10]]

    parts = [
        f"{requested_date['label']}-нд нийт {len(matching_documents)} хүний баримт байна.",
        "Тооллыг тухайн өдрийн PDF баримтуудын тоогоор гаргалаа.",
    ]
    if names:
        parts.append(f"Нэрсийн жишээ: {', '.join(names)}")
    return "\n\n".join(parts)


def should_force_local_answer(
    question: str,
    ranked_docs: list[dict[str, Any]],
    all_documents: list[dict[str, Any]],
    history_messages: list[dict[str, Any]],
) -> bool:
    normalized = normalize_question_for_intent(question)
    if resolve_followup_context(question, all_documents, history_messages):
        return True
    if build_list_answer(normalized, ranked_docs, all_documents, history_messages):
        return True
    if build_aggregate_answer(normalized, all_documents, history_messages):
        return True
    if is_today_question(question, normalized) or is_greeting_question(question, normalized):
        return True

    person_query = extract_person_query(question)
    if person_query and not has_confident_match(question, ranked_docs):
        return True
    return False


def is_count_question(normalized: str) -> bool:
    return "хэдэн" in normalized and any(
        key in normalized for key in ("хүн", "өвчтөн", "үзүүлсэн", "ирсэн", "баримт")
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
