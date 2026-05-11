from __future__ import annotations

import json
from urllib import error, request

from .config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL, OPENAI_TIMEOUT_SECONDS
from .text_utils import normalize_whitespace


def is_openai_configured() -> bool:
    return bool(OPENAI_API_KEY)


def maybe_generate_openai_answer(
    question: str,
    context_documents: list[dict],
    history_messages: list[dict],
) -> str | None:
    if not is_openai_configured():
        return None

    payload = {
        "model": OPENAI_MODEL,
        "input": build_openai_input(question, context_documents, history_messages),
    }
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{OPENAI_BASE_URL}/responses",
        data=data,
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=OPENAI_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"OpenAI API error ({exc.code}): {detail[:300]}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"OpenAI connection failed: {exc.reason}") from exc

    text = extract_response_text(body)
    if not text:
        raise RuntimeError("OpenAI хариултаас текст уншиж чадсангүй.")
    return text


def build_openai_input(
    question: str,
    context_documents: list[dict],
    history_messages: list[dict],
) -> list[dict]:
    developer_message = {
        "role": "developer",
        "content": (
            "You are SOS Medica's assistant. "
            "Answer in Mongolian unless the user clearly asks in another language. "
            "Keep answers concise and practical. "
            "If document context is provided, use it faithfully and do not dump raw PDF text; summarize the relevant facts cleanly. "
            "If document context is empty, you may answer general questions normally. "
            "But if the user is asking about a specific patient, file, or document fact that is not supported by context, clearly say it was not found and do not invent facts."
        ),
    }
    messages: list[dict] = [developer_message]
    if context_documents:
        messages.append(
            {
                "role": "developer",
                "content": build_document_context(context_documents),
            }
        )
    for message in history_messages[-8:]:
        role = "assistant" if message.get("role") == "bot" else "user"
        text = normalize_whitespace(message.get("text", ""))
        if text:
            messages.append({"role": role, "content": text})

    messages.append({"role": "user", "content": normalize_whitespace(question)})
    return messages


def build_document_context(documents: list[dict]) -> str:
    sections = ["DOCUMENT_CONTEXT"]
    for index, document in enumerate(documents[:3], start=1):
        excerpt = normalize_whitespace(str(document.get("content", "")))[:1800]
        summary = normalize_whitespace(str(document.get("summary", "")))
        sections.append(
            "\n".join(
                [
                    f"[Document {index}]",
                    f"Title: {document.get('title', '')}",
                    f"Summary: {summary}",
                    f"Excerpt: {excerpt}",
                ]
            )
        )
    return "\n\n".join(sections)


def extract_response_text(payload: dict) -> str:
    output_text = normalize_whitespace(payload.get("output_text", ""))
    if output_text:
        return output_text

    parts: list[str] = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"}:
                text_value = normalize_whitespace(content.get("text", ""))
                if text_value:
                    parts.append(text_value)
    return "\n\n".join(parts)
