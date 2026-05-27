from __future__ import annotations

import base64
import json
from urllib import error, parse, request

from .config import (
    GOOGLE_CLOUD_VISION_API_KEY,
    GOOGLE_CLOUD_VISION_BASE_URL,
    GOOGLE_CLOUD_VISION_TIMEOUT_SECONDS,
)
from .text_utils import normalize_multiline_text


def is_google_vision_configured() -> bool:
    return bool(GOOGLE_CLOUD_VISION_API_KEY)


def maybe_extract_google_vision_text(image_bytes: bytes, mime_type: str) -> str | None:
    if not is_google_vision_configured() or not image_bytes:
        return None

    endpoint = (
        f"{GOOGLE_CLOUD_VISION_BASE_URL}/images:annotate"
        f"?key={parse.quote(GOOGLE_CLOUD_VISION_API_KEY, safe='')}"
    )
    payload = {
        "requests": [
            {
                "image": {
                    "content": base64.b64encode(image_bytes).decode("ascii"),
                },
                "features": [
                    {"type": "DOCUMENT_TEXT_DETECTION"},
                ],
                "imageContext": {
                    "languageHints": ["mn", "en"],
                },
            }
        ]
    }
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        endpoint,
        data=data,
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=GOOGLE_CLOUD_VISION_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (error.HTTPError, error.URLError, TimeoutError, json.JSONDecodeError):
        return None

    responses = body.get("responses", [])
    if not responses:
        return None

    response = responses[0]
    full_text = response.get("fullTextAnnotation", {}).get("text", "")
    cleaned = normalize_multiline_text(full_text).strip()
    if cleaned:
        return cleaned

    texts = response.get("textAnnotations", [])
    if texts:
        cleaned = normalize_multiline_text(str(texts[0].get("description", ""))).strip()
        if cleaned:
            return cleaned

    return None
