from __future__ import annotations

from .config import AI_PROVIDER, GEMINI_MODEL, OPENAI_MODEL
from .gemini_service import is_gemini_configured, maybe_generate_gemini_answer
from .openai_service import is_openai_configured, maybe_generate_openai_answer


def get_active_ai_provider() -> str:
    provider = AI_PROVIDER
    if provider == "gemini":
        return "gemini" if is_gemini_configured() else "local"
    if provider == "openai":
        return "openai" if is_openai_configured() else "local"
    if provider == "local":
        return "local"
    if is_gemini_configured():
        return "gemini"
    if is_openai_configured():
        return "openai"
    return "local"


def get_active_ai_model() -> str | None:
    provider = get_active_ai_provider()
    if provider == "gemini":
        return GEMINI_MODEL
    if provider == "openai":
        return OPENAI_MODEL
    return None


def is_ai_configured() -> bool:
    return get_active_ai_provider() in {"gemini", "openai"}


def maybe_generate_ai_answer(
    question: str,
    context_documents: list[dict],
    history_messages: list[dict],
) -> str | None:
    provider = get_active_ai_provider()
    if provider == "gemini":
        return maybe_generate_gemini_answer(question, context_documents, history_messages)
    if provider == "openai":
        return maybe_generate_openai_answer(question, context_documents, history_messages)
    return None
