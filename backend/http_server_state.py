from __future__ import annotations

import mimetypes
import shutil
import subprocess
import sys
from email.utils import formatdate
from pathlib import Path
from typing import Any

from .config import ROOT_DIR
from .documents import UPLOAD_DIR, prepare_image_for_browser
from .store import ensure_guest_user


SESSIONS: dict[str, dict[str, str]] = {}
CHAT_UPLOADS: dict[str, list[dict[str, Any]]] = {}


def run_employee_sync_import() -> tuple[bool, str]:
    script_path = ROOT_DIR / "scripts" / "import_employees_from_workbook.py"
    if not script_path.exists():
        return False, "Employee import script олдсонгүй."

    runtime_candidates = [
        Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "python" / "bin" / "python3",
        Path(sys.executable),
    ]

    python_executable = None
    checked: list[str] = []
    for candidate in runtime_candidates:
        if not candidate.exists():
            continue
        checked.append(str(candidate))
        try:
            probe = subprocess.run(
                [str(candidate), "-c", "import openpyxl"],
                capture_output=True,
                text=True,
                timeout=20,
                cwd=str(ROOT_DIR),
            )
        except Exception:
            continue
        if probe.returncode == 0:
            python_executable = candidate
            break

    if python_executable is None:
        fallback_python = shutil.which("python3")
        if fallback_python:
            checked.append(fallback_python)
            try:
                probe = subprocess.run(
                    [fallback_python, "-c", "import openpyxl"],
                    capture_output=True,
                    text=True,
                    timeout=20,
                    cwd=str(ROOT_DIR),
                )
            except Exception:
                probe = None
            if probe and probe.returncode == 0:
                python_executable = Path(fallback_python)

    if python_executable is None:
        return False, f"Excel sync хийх Python runtime олдсонгүй. Шалгасан: {', '.join(checked) or 'none'}"

    try:
        result = subprocess.run(
            [str(python_executable), str(script_path)],
            capture_output=True,
            text=True,
            timeout=180,
            cwd=str(ROOT_DIR),
        )
    except subprocess.TimeoutExpired:
        return False, "Excel sync хугацаа хэтэрлээ."
    except Exception as error:
        return False, str(error) or "Excel sync хийх үед алдаа гарлаа."

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return False, detail[:500] or "Excel sync хийх үед алдаа гарлаа."

    return True, (result.stdout or "Ажилтны мэдээллийг Excel-ээс дахин sync хийлээ.").strip()


def merge_documents(*document_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for group in document_groups:
        for document in group:
            document_id = str(document.get("id", "")).strip()
            dedupe_key = document_id or f"title:{document.get('title', '')}"
            if dedupe_key in seen_ids:
                continue
            seen_ids.add(dedupe_key)
            merged.append(document)
    return merged


def get_chat_uploads(user_id: str) -> list[dict[str, Any]]:
    return CHAT_UPLOADS.get(user_id, [])


def append_chat_uploads(user_id: str, documents: list[dict[str, Any]]) -> None:
    if not documents:
        return
    CHAT_UPLOADS[user_id] = [*documents, *CHAT_UPLOADS.get(user_id, [])]


def clear_chat_uploads(user_id: str) -> None:
    CHAT_UPLOADS.pop(user_id, None)


def remove_chat_upload(user_id: str, document_id: str) -> list[dict[str, Any]]:
    remaining = [
        document
        for document in CHAT_UPLOADS.get(user_id, [])
        if str(document.get("id")) != document_id
    ]
    CHAT_UPLOADS[user_id] = remaining
    return remaining


def build_guest_session(handler: Any) -> dict[str, str] | None:
    guest_id = str(handler.headers.get("X-Guest-Id", "") or "").strip()
    if not guest_id:
        return None
    safe_guest_id = "".join(char for char in guest_id if char.isalnum() or char in {"-", "_"})
    if not safe_guest_id:
        return None
    guest_key = safe_guest_id[:48]
    guest_user_id = f"guest:{safe_guest_id[:80]}"
    guest_email = f"{guest_key}@guest.sosmedica.mn"
    ensure_guest_user(guest_user_id, guest_email)
    return {
        "token": "",
        "userId": guest_user_id,
        "email": guest_email,
        "role": "guest",
        "name": "Зочин",
    }


def get_session(handler: Any, allow_guest: bool = False) -> dict[str, str] | None:
    raw_header = handler.headers.get("Authorization", "")
    token = raw_header[7:] if raw_header.startswith("Bearer ") else ""
    if token and token in SESSIONS:
        return {"token": token, **SESSIONS[token]}
    if allow_guest:
        return build_guest_session(handler)
    return None


def serve_storage_file(handler: Any, safe_path: Path, download_name: str) -> None:
    prepared_path = safe_path
    content_type = mimetypes.guess_type(safe_path.name)[0] or "application/octet-stream"
    should_cleanup = False

    if content_type.startswith("image/") or safe_path.suffix.lower() in {".heic", ".heif"}:
        prepared_path, content_type, should_cleanup = prepare_image_for_browser(safe_path)

    try:
        handler.send_response(200)
        handler.send_cors_headers()
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(prepared_path.stat().st_size))
        handler.send_header("Content-Disposition", f'inline; filename="{Path(download_name).name}"')
        handler.send_header("Last-Modified", formatdate(prepared_path.stat().st_mtime, usegmt=True))
        handler.end_headers()
        handler.wfile.write(prepared_path.read_bytes())
    finally:
        if should_cleanup and prepared_path != safe_path and prepared_path.exists():
            try:
                prepared_path.unlink()
            except OSError:
                pass
