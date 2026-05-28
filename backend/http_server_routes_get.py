from __future__ import annotations

from urllib.parse import parse_qs

from .ai_service import get_active_ai_model, get_active_ai_provider
from .config import DEFAULT_PROMPTS
from .documents import UPLOAD_DIR, is_valid_browser_image, resolve_document_storage_path
from .http_server_state import get_chat_uploads, serve_storage_file
from .store import (
    get_document_by_id,
    get_document_submission_by_id,
    get_employee_by_id,
    get_history_by_id,
    list_document_folders,
    list_documents,
    list_document_submissions,
    list_employees,
    list_history_summaries_by_user,
    sanitize_document,
    sanitize_employee,
    sanitize_submission,
    update_document_storage_path,
)


def handle_api_get(handler, parsed) -> None:
    if parsed.path == "/api/bootstrap":
        _handle_bootstrap(handler, parsed)
        return

    if parsed.path == "/api/history":
        _handle_history_get(handler, parsed)
        return

    if parsed.path == "/api/admin/document/file":
        _handle_admin_document_file(handler, parsed)
        return

    if parsed.path == "/api/admin/submission/file":
        _handle_admin_submission_file(handler, parsed)
        return

    if parsed.path == "/api/admin/employee/photo":
        _handle_admin_employee_photo(handler, parsed)
        return

    handler.send_json(404, {"error": "Not found"})


def _handle_bootstrap(handler, parsed) -> None:
    query = parse_qs(parsed.query)
    scope = (query.get("scope", ["chat"])[0] or "chat").strip().lower()
    session = handler.require_session(allow_guest=scope != "admin")
    if not session:
        return
    include_admin_payload = scope == "admin" and session["role"] == "admin"
    chat_documents = [sanitize_document(document) for document in get_chat_uploads(session["userId"])]
    payload = {
        "user": {
            "email": session["email"],
            "role": session["role"],
            "name": session["name"],
        },
        "ai": {
            "provider": get_active_ai_provider(),
            "model": get_active_ai_model(),
        },
        "prompts": DEFAULT_PROMPTS,
        "folders": list_document_folders() if include_admin_payload else [],
        "chatDocuments": chat_documents,
        "documents": [sanitize_document(document) for document in list_documents()] if include_admin_payload else [],
        "submissions": [sanitize_submission(item) for item in list_document_submissions()] if include_admin_payload else [],
        "employees": [sanitize_employee(item) for item in list_employees()] if include_admin_payload else [],
        "histories": list_history_summaries_by_user(session["userId"]),
    }
    handler.send_json(200, payload)


def _handle_history_get(handler, parsed) -> None:
    session = handler.require_session(allow_guest=True)
    if not session:
        return
    history_id = parse_qs(parsed.query).get("id", [None])[0]
    history = get_history_by_id(history_id, session["userId"])
    if not history:
        handler.send_json(404, {"error": "Chat history олдсонгүй."})
        return
    handler.send_json(200, {"history": history})


def _handle_admin_document_file(handler, parsed) -> None:
    session = handler.require_session()
    if not session:
        return
    if session["role"] != "admin":
        handler.send_json(403, {"error": "Admin эрх шаардлагатай."})
        return
    document_id = (parse_qs(parsed.query).get("id", [""])[0] or "").strip()
    if not document_id:
        handler.send_json(400, {"error": "Файл ID дутуу байна."})
        return
    document = get_document_by_id(document_id)
    if not document:
        handler.send_json(404, {"error": "Файл олдсонгүй."})
        return
    storage_path = str(document.get("storagePath", "") or "").strip()
    if not storage_path:
        storage_path = resolve_document_storage_path(document)
        if storage_path:
            update_document_storage_path(
                str(document.get("id", "")),
                storage_path,
                str(document.get("folder", "Ерөнхий") or "Ерөнхий"),
            )
            document["storagePath"] = storage_path
        else:
            handler.send_json(404, {"error": "Энэ файлд preview байхгүй байна."})
            return

    safe_path = (UPLOAD_DIR / storage_path).resolve()
    upload_root = UPLOAD_DIR.resolve()
    if not str(safe_path).startswith(str(upload_root)) or not safe_path.exists() or safe_path.is_dir():
        storage_path = resolve_document_storage_path(document)
        if not storage_path:
            handler.send_json(404, {"error": "Файл олдсонгүй."})
            return
        update_document_storage_path(
            str(document.get("id", "")),
            storage_path,
            str(document.get("folder", "Ерөнхий") or "Ерөнхий"),
        )
        document["storagePath"] = storage_path
        safe_path = (UPLOAD_DIR / storage_path).resolve()

    serve_storage_file(handler, safe_path, str(document.get("title", safe_path.name)))


def _handle_admin_submission_file(handler, parsed) -> None:
    session = handler.require_session()
    if not session:
        return
    if session["role"] != "admin":
        handler.send_json(403, {"error": "Admin эрх шаардлагатай."})
        return
    submission_id = (parse_qs(parsed.query).get("id", [""])[0] or "").strip()
    if not submission_id:
        handler.send_json(400, {"error": "Баримтын ID дутуу байна."})
        return
    submission = get_document_submission_by_id(submission_id)
    if not submission:
        handler.send_json(404, {"error": "Баримт олдсонгүй."})
        return
    storage_path = str(submission.get("storagePath", "") or "").strip()
    if not storage_path:
        handler.send_json(404, {"error": "Энэ баримтад preview байхгүй байна."})
        return

    safe_path = (UPLOAD_DIR / storage_path).resolve()
    upload_root = UPLOAD_DIR.resolve()
    if not str(safe_path).startswith(str(upload_root)) or not safe_path.exists() or safe_path.is_dir():
        handler.send_json(404, {"error": "Файл олдсонгүй."})
        return
    if safe_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic", ".heif"} and not is_valid_browser_image(safe_path):
        handler.send_json(422, {"error": "Энэ баримтын зураг эвдэрсэн эсвэл буруу хадгалагдсан байна. Дахин илгээнэ үү."})
        return

    serve_storage_file(handler, safe_path, str(submission.get("title", safe_path.name)))


def _handle_admin_employee_photo(handler, parsed) -> None:
    session = handler.require_session()
    if not session:
        return
    if session["role"] != "admin":
        handler.send_json(403, {"error": "Admin эрх шаардлагатай."})
        return
    employee_id = (parse_qs(parsed.query).get("id", [""])[0] or "").strip()
    if not employee_id:
        handler.send_json(400, {"error": "Ажилтны ID дутуу байна."})
        return
    employee = get_employee_by_id(employee_id)
    if not employee:
        handler.send_json(404, {"error": "Ажилтан олдсонгүй."})
        return
    storage_path = str(employee.get("photoStoragePath", "") or "").strip()
    if not storage_path:
        handler.send_json(404, {"error": "Зураг олдсонгүй."})
        return
    safe_path = (UPLOAD_DIR / storage_path).resolve()
    upload_root = UPLOAD_DIR.resolve()
    if not str(safe_path).startswith(str(upload_root)) or not safe_path.exists() or safe_path.is_dir():
        handler.send_json(404, {"error": "Зураг олдсонгүй."})
        return
    download_name = f"{employee.get('id', 'employee')}-{employee.get('lastNameEn', '')}-{employee.get('firstNameEn', '')}{safe_path.suffix}"
    serve_storage_file(handler, safe_path, download_name)
