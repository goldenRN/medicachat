from __future__ import annotations

import json
from urllib import error, parse, request

from .config import GEMINI_API_KEY, GEMINI_BASE_URL, GEMINI_MODEL, GEMINI_TIMEOUT_SECONDS
from .text_utils import normalize_whitespace


def is_gemini_configured() -> bool:
    return bool(GEMINI_API_KEY)


def maybe_generate_gemini_answer(
    question: str,
    context_documents: list[dict],
    history_messages: list[dict],
) -> str | None:
    if not is_gemini_configured():
        return None

    model_name = normalize_gemini_model_name(GEMINI_MODEL)
    endpoint = f"{GEMINI_BASE_URL}/models/{model_name}:generateContent?key={parse.quote(GEMINI_API_KEY, safe='')}"
    payload = {
        "systemInstruction": {
            "parts": [
                {
                    "text": (
                        "You are SOS Medica's assistant. "
                        "Answer in Mongolian unless the user clearly asks in another language. "
                        "Keep answers concise and practical. "
                        "If document context is provided, use it faithfully and summarize the relevant facts cleanly instead of dumping raw PDF text. "
                        "If document context is empty, you may answer general questions normally. "
                        "But if the user is asking about a specific patient, file, or document fact that is not supported by context, clearly say it was not found and do not invent facts."
                    )
                }
            ]
        },
        "contents": build_gemini_contents(question, context_documents, history_messages),
        "generationConfig": {
            "temperature": 0.2,
        },
    }
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        endpoint,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=GEMINI_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Gemini API error ({exc.code}): {detail[:300]}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Gemini connection failed: {exc.reason}") from exc

    text = extract_gemini_text(body)
    if not text:
        raise RuntimeError("Gemini хариултаас текст уншиж чадсангүй.")
    return text


def normalize_gemini_model_name(model_name: str) -> str:
    cleaned = model_name.strip()
    if cleaned.startswith("models/"):
        return cleaned.removeprefix("models/")
    return cleaned


def build_gemini_contents(
    question: str,
    context_documents: list[dict],
    history_messages: list[dict],
) -> list[dict]:
    contents: list[dict] = []
    if context_documents:
        contents.append(
            {
                "role": "user",
                "parts": [
                    {
                        "text": build_document_context(context_documents),
                    }
                ],
            }
        )

    for message in history_messages[-8:]:
        role = "model" if message.get("role") == "bot" else "user"
        text = normalize_whitespace(message.get("text", ""))
        if text:
            contents.append({"role": role, "parts": [{"text": text}]})

    contents.append(
        {
            "role": "user",
            "parts": [{"text": normalize_whitespace(question)}],
        }
    )
    return contents


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


def extract_gemini_text(payload: dict) -> str:
    parts: list[str] = []
    for candidate in payload.get("candidates", []):
        content = candidate.get("content", {})
        for part in content.get("parts", []):
            text = normalize_whitespace(part.get("text", ""))
            if text:
                parts.append(text)
    return "\n\n".join(parts)
