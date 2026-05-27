from __future__ import annotations

import json
from html import unescape
from urllib import error, parse, request

from .config import (
    GOOGLE_TRANSLATE_API_KEY,
    GOOGLE_TRANSLATE_BASE_URL,
    GOOGLE_TRANSLATE_TIMEOUT_SECONDS,
)

GOOGLE_TRANSLATE_PUBLIC_BASE_URL = "https://translate.googleapis.com/translate_a/single"


def is_google_translate_configured() -> bool:
    return bool(GOOGLE_TRANSLATE_API_KEY)


def maybe_translate_text_with_google(
    text: str,
    source_language: str,
    target_language: str,
) -> dict[str, str]:
    cleaned_text = str(text or "").strip()
    normalized_source = normalize_language_code(source_language, allow_auto=True)
    normalized_target = normalize_language_code(target_language)
    api_error_message = ""

    if not cleaned_text:
        raise RuntimeError("Орчуулах текст хоосон байна.")
    if not normalized_target:
        raise RuntimeError("Орчуулах хэлээ сонгоно уу.")
    if normalized_source and normalized_source != "auto" and normalized_source == normalized_target:
        raise RuntimeError("Эх хэл болон орчуулах хэл ижил байна.")

    if is_google_translate_configured():
        try:
            return translate_with_google_api(
                cleaned_text,
                normalized_source,
                normalized_target,
            )
        except RuntimeError as exc:
            api_error_message = str(exc).strip()

    try:
        return translate_with_google_public(
            cleaned_text,
            normalized_source,
            normalized_target,
        )
    except RuntimeError as exc:
        public_error_message = str(exc).strip()
        if api_error_message:
            raise RuntimeError(
                f"{api_error_message} Fallback translate мөн амжилтгүй боллоо: {public_error_message}"
            ) from exc
        raise RuntimeError(public_error_message) from exc


def translate_with_google_api(
    text: str,
    source_language: str,
    target_language: str,
) -> dict[str, str]:
    endpoint = (
        f"{GOOGLE_TRANSLATE_BASE_URL}"
        f"?key={parse.quote(GOOGLE_TRANSLATE_API_KEY, safe='')}"
    )
    payload = {
        "q": text,
        "target": target_language,
        "format": "text",
    }
    if source_language and source_language != "auto":
        payload["source"] = source_language

    req = request.Request(
        endpoint,
        data=parse.urlencode(payload).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=GOOGLE_TRANSLATE_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(build_google_translate_error(exc.code, detail)) from exc
    except error.URLError as exc:
        raise RuntimeError(f"Google Translate connection failed: {exc.reason}") from exc

    translations = body.get("data", {}).get("translations", [])
    first_translation = translations[0] if translations else {}
    translated_text = unescape(str(first_translation.get("translatedText", "") or "")).strip()
    detected_source_language = str(
        first_translation.get("detectedSourceLanguage", "") or source_language or ""
    ).strip()

    if not translated_text:
        raise RuntimeError("Google Translate хариултаас орчуулга олдсонгүй.")

    return {
        "translatedText": translated_text,
        "detectedSourceLanguage": detected_source_language,
        "targetLanguage": target_language,
    }


def translate_with_google_public(
    text: str,
    source_language: str,
    target_language: str,
) -> dict[str, str]:
    query = parse.urlencode(
        {
            "client": "gtx",
            "sl": source_language or "auto",
            "tl": target_language,
            "dt": "t",
            "q": text,
        },
        doseq=True,
    )
    req = request.Request(
        f"{GOOGLE_TRANSLATE_PUBLIC_BASE_URL}?{query}",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
        },
        method="GET",
    )

    try:
        with request.urlopen(req, timeout=GOOGLE_TRANSLATE_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(build_google_translate_error(exc.code, detail)) from exc
    except error.URLError as exc:
        raise RuntimeError(f"Google Translate fallback connection failed: {exc.reason}") from exc

    translated_segments = []
    for item in body[0] if isinstance(body, list) and body else []:
        if isinstance(item, list) and item:
            translated_segments.append(str(item[0] or ""))
    translated_text = unescape("".join(translated_segments)).strip()
    detected_source_language = ""
    if isinstance(body, list) and len(body) > 2:
        detected_source_language = str(body[2] or source_language or "").strip()

    if not translated_text:
        raise RuntimeError("Google Translate fallback хариултаас орчуулга олдсонгүй.")

    return {
        "translatedText": translated_text,
        "detectedSourceLanguage": detected_source_language,
        "targetLanguage": target_language,
    }


def normalize_language_code(value: str, allow_auto: bool = False) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return "auto" if allow_auto else ""
    lowered = cleaned.lower()
    if lowered == "auto":
        return "auto" if allow_auto else ""
    return cleaned


def build_google_translate_error(status_code: int, detail: str) -> str:
    fallback_message = f"Google Translate API error ({status_code})."
    try:
        payload = json.loads(detail)
    except json.JSONDecodeError:
        return f"{fallback_message} {detail[:220]}".strip()

    message = (
        payload.get("error", {}).get("message")
        or payload.get("message")
        or detail[:220]
    )
    return f"{fallback_message} {message}".strip()
