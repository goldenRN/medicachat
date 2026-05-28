from __future__ import annotations

import re
from typing import Any

from .chat_logic_employee import (
    build_employee_answer,
    build_employee_heading,
    count_employee_rows,
    detect_employee_category_keys,
    document_matches_employee_intent,
    extract_employee_query_tokens,
    find_employee_matches,
    format_employee_list_line,
    is_employee_address_question,
    is_employee_contact_question,
    is_employee_directory_question,
    is_employee_question,
)
from .chat_logic_shared import (
    build_greeting_answer,
    build_today_answer,
    collect_search_terms,
    dedupe_by_name,
    document_matches_date,
    document_matches_usa_intent,
    extract_person_name,
    extract_person_query,
    extract_query_tokens,
    is_count_question,
    is_greeting_question,
    is_likely_person_document,
    is_list_question,
    is_today_question,
    normalize_question_for_intent,
    resolve_requested_date,
    score_person_query_match,
)
from .chat_logic_site import build_site_information_answer, is_site_information_question
from .store import list_employees
from .text_utils import extract_name_from_title, normalize_whitespace, tokenize


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


def build_no_match_answer(question: str, history_messages: list[dict[str, Any]] | None = None) -> str:
    normalized = normalize_question_for_intent(question)
    person_query = extract_person_query(question)
    if is_employee_directory_question(question, normalized, history_messages):
        if person_query:
            return (
                f'"{person_query["raw"]}" нэртэй ажилтан ажилтны хүснэгтээс олдсонгүй.\n\n'
                "Нэрийн бичлэг өөр байж болох тул овог, нэр эсвэл ангиллыг нь нэмж асуугаад үзээрэй."
            )
        return (
            "Ажилтны хүснэгтээс энэ асуултад тохирох мэдээлэл олдсонгүй.\n\n"
            "Нэр, албан тушаал, ангилал эсвэл холбоо барих мэдээллээр нь дахин хайж үзэж болно."
        )
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
    if is_site_information_question(question, history_messages):
        return []
    followup_context = resolve_followup_context(question, all_documents, history_messages)
    if followup_context:
        return followup_context["documents"][:3]
    person_query = extract_person_query(question)
    if person_query and ranked_docs:
        top_person_score = ranked_docs[0].get("personMatchScore", 0)
        if top_person_score >= 90:
            exact_person_documents = [
                document
                for document in ranked_docs
                if document.get("personMatchScore", 0) >= 90
            ]
            unique_documents: list[dict[str, Any]] = []
            seen_titles: set[str] = set()
            for document in exact_person_documents:
                title = str(document.get("title", ""))
                if title in seen_titles:
                    continue
                seen_titles.add(title)
                unique_documents.append(document)
            return unique_documents[:3]
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

    site_information_answer = build_site_information_answer(question, history_messages)
    if site_information_answer:
        return site_information_answer

    list_answer = build_list_answer(question, normalized, ranked_docs, all_documents, history_messages)
    if list_answer:
        return list_answer

    aggregate_answer = build_aggregate_answer(question, normalized, all_documents, history_messages)
    if aggregate_answer:
        return aggregate_answer

    employee_answer = build_employee_answer(question, normalized, history_messages)
    if employee_answer:
        return employee_answer

    if is_today_question(question, normalized):
        return build_today_answer()

    if is_greeting_question(question, normalized):
        return build_greeting_answer()

    if not has_confident_match(question, ranked_docs):
        return build_no_match_answer(question, history_messages)

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
    question: str,
    normalized: str,
    ranked_docs: list[dict[str, Any]],
    all_documents: list[dict[str, Any]],
    history_messages: list[dict[str, Any]],
) -> str | None:
    if not is_list_question(normalized):
        return None

    if is_employee_directory_question(question, normalized, history_messages):
        matches = find_employee_matches(question, normalized, history_messages)
        if not matches:
            return "Ажилтны хүснэгтээс тохирох жагсаалт олдсонгүй."

        show_all = any(key in normalized for key in ("бүгд", "bugd", "all"))
        visible_matches = matches if show_all else matches[:20]
        contact_requested = is_employee_contact_question(normalized)
        address_requested = is_employee_address_question(normalized)
        lines = [
            format_employee_list_line(
                employee,
                contact_requested=contact_requested,
                address_requested=address_requested,
            )
            for employee in visible_matches
        ]
        heading = build_employee_heading(matches, normalized, fallback="Ажилтны жагсаалт")
        tail = (
            f"\n\nНийт {len(matches)} ажилтан олдлоо. Дээр эхний 20-г үзүүлэв."
            if not show_all and len(matches) > 20
            else f"\n\nНийт {len(matches)} ажилтан олдлоо."
        )
        return f"{heading}:\n\n" + "\n".join(f"{index + 1}. {line}" for index, line in enumerate(lines)) + tail

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
    question: str,
    normalized: str,
    documents: list[dict[str, Any]],
    history_messages: list[dict[str, Any]],
) -> str | None:
    if is_employee_directory_question(question, normalized, history_messages) and is_count_question(normalized):
        category_keys = detect_employee_category_keys(normalized)
        filtered_tokens = extract_employee_query_tokens(question)
        person_query = extract_person_query(question)
        matches = find_employee_matches(question, normalized, history_messages)
        if not matches and not category_keys and not filtered_tokens and not person_query:
            matches = list_employees()
        if not matches:
            return "Ажилтны хүснэгтээс тохирох тооллого гаргах мэдээлэл олдсонгүй."

        if category_keys or filtered_tokens or person_query:
            if is_employee_address_question(normalized):
                return f"Тухайн хаяг, байршилд бүртгэлтэй нийт {len(matches)} ажилтан байна."
            heading = build_employee_heading(matches, normalized, fallback="Ажилтны хүснэгт")
            return f"{heading}-д нийт {len(matches)} ажилтан байна."

        category_counts: dict[str, int] = {}
        for employee in matches:
            label = str(employee.get("categoryNameMn") or employee.get("categoryKey") or "Бусад")
            category_counts[label] = category_counts.get(label, 0) + 1
        breakdown = "\n".join(
            f"- {label}: {count} ажилтан"
            for label, count in sorted(category_counts.items(), key=lambda item: item[0])
        )
        return f"Ажилтны хүснэгтэд нийт {len(matches)} ажилтан байна.\n\n{breakdown}"

    if not is_count_question(normalized):
        return None

    if is_employee_question(normalized):
        employee_documents = [document for document in documents if document_matches_employee_intent(document)]
        if not employee_documents:
            return "Ажилчдын мэдээлэлтэй тохирох файл одоогийн санд олдсонгүй."

        counted_documents: list[dict[str, Any]] = []
        total_rows = 0
        for document in employee_documents:
            row_count = count_employee_rows(document)
            if row_count <= 0:
                continue
            counted_documents.append(document)
            total_rows += row_count

        if total_rows <= 0:
            return "Ажилчдын мэдээллийн файлыг олсон ч нийт мөрийн тоог найдвартай гаргаж чадсангүй."

        visible_titles = ", ".join(document["title"] for document in counted_documents[:3])
        suffix = "" if len(counted_documents) <= 3 else f" болон өөр {len(counted_documents) - 3} файл"
        return (
            f"Ажилчдын мэдээлэлтэй {len(counted_documents)} файлаас нийт {total_rows} мөрийн бүртгэл олдлоо.\n\n"
            f"Ашигласан файл: {visible_titles}{suffix}."
        )

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
    if is_site_information_question(question, history_messages):
        return True
    if is_employee_directory_question(question, normalized, history_messages):
        return True
    if resolve_followup_context(question, all_documents, history_messages):
        return True
    if build_list_answer(question, normalized, ranked_docs, all_documents, history_messages):
        return True
    if build_aggregate_answer(question, normalized, all_documents, history_messages):
        return True
    if is_today_question(question, normalized) or is_greeting_question(question, normalized):
        return True

    person_query = extract_person_query(question)
    if person_query and not has_confident_match(question, ranked_docs):
        return True
    return False


def needs_full_document_scan(
    question: str,
    history_messages: list[dict[str, Any]] | None = None,
) -> bool:
    history_messages = history_messages or []
    normalized = normalize_question_for_intent(question)
    if is_employee_directory_question(question, normalized, history_messages):
        return False
    if is_detail_followup_request(question, normalized):
        return True
    if is_count_question(normalized) or is_list_question(normalized):
        return True
    return False


def should_skip_document_search(
    question: str,
    history_messages: list[dict[str, Any]] | None = None,
) -> bool:
    history_messages = history_messages or []
    normalized = normalize_question_for_intent(question)
    if is_employee_directory_question(question, normalized, history_messages):
        return True
    if is_greeting_question(question, normalized) or is_today_question(question, normalized):
        return True
    if is_site_information_question(question, history_messages):
        return True
    return False
