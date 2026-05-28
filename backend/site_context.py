from __future__ import annotations

import re
from functools import lru_cache
from html import unescape
from urllib import error, request

from .config import SITE_FETCH_TIMEOUT_SECONDS, SOSMEDICA_SITE_URL
from .text_utils import normalize_whitespace


SOSMEDICA_HINTS = (
    "сос медика",
    "сос мед",
    "сос медика монгол"
    "sos medica",
    "sosmedica",
    "sosmed"
)

SITE_INFO_HINTS = (
    "хаана",
    "хаяг",
    "утас",
    "байрш",
    "холбоо",
    "салбар",
    "website",
    "веб",
    "site",
    "address",
    "phone",
    "contact",
    "location",
)

SITE_PATHS = ("/contact", "", "/about")


def maybe_fetch_site_context(question: str) -> str:
    normalized = normalize_whitespace(str(question or "").lower())
    if not any(hint in normalized for hint in SOSMEDICA_HINTS):
        return ""
    if not any(hint in normalized for hint in SITE_INFO_HINTS):
        return ""

    sections: list[str] = []
    for path in SITE_PATHS:
        url = f"{SOSMEDICA_SITE_URL}{path}"
        snippet = fetch_site_snippet(url)
        if snippet:
            sections.append(f"Source URL: {url}\nContent: {snippet}")
        if len(sections) == 1:
            break
    return "\n\n".join(sections)


@lru_cache(maxsize=8)
def fetch_site_snippet(url: str) -> str:
    try:
        req = request.Request(
            url,
            headers={
                "User-Agent": "SOSMedicaAssistant/1.0",
            },
            method="GET",
        )
        with request.urlopen(req, timeout=SITE_FETCH_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get("Content-Type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                return ""
            body = response.read().decode("utf-8", errors="ignore")
    except (error.HTTPError, error.URLError, TimeoutError, ValueError):
        return ""

    text = html_to_text(body)
    if not text:
        return ""

    lines = [line for line in text.splitlines() if line]
    preferred = [
        line
        for line in lines
        if any(keyword in line.lower() for keyword in ("хаяг", "байрш", "утас", "contact", "address", "phone", "location"))
    ]
    selected = preferred[:8] if preferred else lines[:12]
    return "\n".join(selected)[:1800]


def html_to_text(html: str) -> str:
    stripped = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    stripped = re.sub(r"(?i)<br\s*/?>", "\n", stripped)
    stripped = re.sub(r"(?i)</p\s*>", "\n", stripped)
    stripped = re.sub(r"(?s)<[^>]+>", " ", stripped)
    stripped = unescape(stripped)
    stripped = re.sub(r"[ \t\r\f\v]+", " ", stripped)
    lines = [normalize_whitespace(line) for line in stripped.split("\n")]
    return "\n".join(line for line in lines if len(line) > 2)
