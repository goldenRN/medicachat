from __future__ import annotations

import json
import mimetypes
import secrets
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .chat_logic import (
    build_answer,
    collect_search_terms,
    has_confident_match,
    needs_full_document_scan,
    normalize_question_for_intent,
    rank_documents,
    select_reply_documents,
    should_skip_document_search,
    should_force_local_answer,
)
from .ai_service import get_active_ai_model, get_active_ai_provider, is_ai_configured, maybe_generate_ai_answer
from .config import DB_PATH, DEFAULT_PROMPTS, HOST, PORT, ROOT_DIR
from .documents import (
    UPLOAD_DIR,
    copy_document_storage,
    delete_folder_storage,
    delete_document_storage,
    move_folder_storage,
    parse_uploaded_file,
    prepare_image_for_browser,
)
from .store import (
    append_message,
    create_document_submission,
    create_folder,
    create_history_record,
    create_message,
    delete_document_submission_record,
    delete_history,
    delete_document_record,
    delete_folder,
    ensure_bootstrap,
    find_user_by_credentials,
    get_document_by_id,
    get_document_submission_by_id,
    get_history_by_id,
    insert_documents,
    list_document_folders,
    list_documents,
    list_document_submissions,
    list_history_summaries_by_user,
    rename_folder,
    rename_history,
    sanitize_document,
    sanitize_submission,
    search_documents,
    sanitize_user,
    save_copied_document,
    summarize_history,
    touch_history,
    update_document_storage_path,
    update_history_title,
)
from .text_utils import build_history_title, sanitize_folder_name, summarize_content, utc_now


SESSIONS: dict[str, dict[str, str]] = {}
CHAT_UPLOADS: dict[str, list[dict[str, Any]]] = {}


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


def get_session(handler: BaseHTTPRequestHandler) -> dict[str, str] | None:
    raw_header = handler.headers.get("Authorization", "")
    token = raw_header[7:] if raw_header.startswith("Bearer ") else ""
    return {"token": token, **SESSIONS[token]} if token and token in SESSIONS else None


def serve_storage_file(handler: BaseHTTPRequestHandler, safe_path: Path, download_name: str) -> None:
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


class AppHandler(BaseHTTPRequestHandler):
    server_version = "SOSMedicaPython/1.0"

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/"):
                self.handle_api_get(parsed)
                return
            self.serve_static(parsed.path)
        except Exception as error:
            self.send_json(500, {"error": str(error) or "Internal server error"})

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            if not parsed.path.startswith("/api/"):
                self.send_json(404, {"error": "Not found"})
                return
            self.handle_api_post(parsed)
        except Exception as error:
            self.send_json(500, {"error": str(error) or "Internal server error"})

    def handle_api_get(self, parsed) -> None:
        session = self.require_session()
        if parsed.path == "/api/bootstrap":
            if not session:
                return
            query = parse_qs(parsed.query)
            scope = (query.get("scope", ["chat"])[0] or "chat").strip().lower()
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
                "histories": list_history_summaries_by_user(session["userId"]),
            }
            self.send_json(200, payload)
            return

        if parsed.path == "/api/history":
            if not session:
                return
            history_id = parse_qs(parsed.query).get("id", [None])[0]
            history = get_history_by_id(history_id, session["userId"])
            if not history:
                self.send_json(404, {"error": "Chat history олдсонгүй."})
                return
            self.send_json(200, {"history": history})
            return

        if parsed.path == "/api/admin/document/file":
            if not session:
                return
            if session["role"] != "admin":
                self.send_json(403, {"error": "Admin эрх шаардлагатай."})
                return
            document_id = (parse_qs(parsed.query).get("id", [""])[0] or "").strip()
            if not document_id:
                self.send_json(400, {"error": "Файл ID дутуу байна."})
                return
            document = get_document_by_id(document_id)
            if not document:
                self.send_json(404, {"error": "Файл олдсонгүй."})
                return
            storage_path = str(document.get("storagePath", "") or "").strip()
            if not storage_path:
                self.send_json(404, {"error": "Энэ файлд preview байхгүй байна."})
                return

            safe_path = (UPLOAD_DIR / storage_path).resolve()
            upload_root = UPLOAD_DIR.resolve()
            if not str(safe_path).startswith(str(upload_root)) or not safe_path.exists() or safe_path.is_dir():
                self.send_json(404, {"error": "Файл олдсонгүй."})
                return

            serve_storage_file(self, safe_path, str(document.get("title", safe_path.name)))
            return

        if parsed.path == "/api/admin/submission/file":
            if not session:
                return
            if session["role"] != "admin":
                self.send_json(403, {"error": "Admin эрх шаардлагатай."})
                return
            submission_id = (parse_qs(parsed.query).get("id", [""])[0] or "").strip()
            if not submission_id:
                self.send_json(400, {"error": "Баримтын ID дутуу байна."})
                return
            submission = get_document_submission_by_id(submission_id)
            if not submission:
                self.send_json(404, {"error": "Баримт олдсонгүй."})
                return
            storage_path = str(submission.get("storagePath", "") or "").strip()
            if not storage_path:
                self.send_json(404, {"error": "Энэ баримтад preview байхгүй байна."})
                return

            safe_path = (UPLOAD_DIR / storage_path).resolve()
            upload_root = UPLOAD_DIR.resolve()
            if not str(safe_path).startswith(str(upload_root)) or not safe_path.exists() or safe_path.is_dir():
                self.send_json(404, {"error": "Файл олдсонгүй."})
                return

            serve_storage_file(self, safe_path, str(submission.get("title", safe_path.name)))
            return

        self.send_json(404, {"error": "Not found"})

    def handle_api_post(self, parsed) -> None:
        body = self.read_json_body()

        if parsed.path == "/api/login":
            email = body.get("email", "")
            password = body.get("password", "")
            print(
                "[api] /api/login request",
                {
                    "email": str(email).strip().lower(),
                    "password_length": len(str(password or "").strip()),
                    "remote": self.client_address[0] if self.client_address else "",
                    "user_agent": self.headers.get("User-Agent", "")[:120],
                },
                flush=True,
            )
            user = find_user_by_credentials(body.get("email", ""), body.get("password", ""))
            if not user:
                print(
                    "[api] /api/login response",
                    {"email": str(email).strip().lower(), "status": 401},
                    flush=True,
                )
                self.send_json(401, {"error": "И-мэйл эсвэл нууц үг буруу байна."})
                return
            token = secrets.token_hex(16)
            SESSIONS[token] = {
                "userId": user["id"],
                "email": user["email"],
                "role": user["role"],
                "name": user["name"],
            }
            print(
                "[api] /api/login response",
                {"email": user["email"], "status": 200, "role": user["role"]},
                flush=True,
            )
            self.send_json(200, {"token": token, "user": sanitize_user(user)})
            return

        if parsed.path == "/api/logout":
            session = get_session(self)
            if session:
                clear_chat_uploads(session["userId"])
                SESSIONS.pop(session["token"], None)
            self.send_json(200, {"ok": True})
            return

        session = self.require_session()
        if not session:
            return

        if parsed.path == "/api/history/new":
            history = create_history_record(session["userId"], "Шинэ чат")
            self.send_json(201, {"history": summarize_history(history)})
            return

        if parsed.path == "/api/history/rename":
            history_id = str(body.get("historyId", "")).strip()
            title = build_history_title(str(body.get("title", "")).strip())
            if not history_id or not title:
                self.send_json(400, {"error": "Чатын нэр хоосон байна."})
                return
            if not rename_history(history_id, session["userId"], title):
                self.send_json(404, {"error": "Chat history олдсонгүй."})
                return
            self.send_json(200, {"histories": list_history_summaries_by_user(session["userId"])})
            return

        if parsed.path == "/api/history/delete":
            history_id = str(body.get("historyId", "")).strip()
            if not history_id:
                self.send_json(400, {"error": "Chat history ID дутуу байна."})
                return
            if not delete_history(history_id, session["userId"]):
                self.send_json(404, {"error": "Chat history олдсонгүй."})
                return
            self.send_json(200, {"histories": list_history_summaries_by_user(session["userId"])})
            return

        if parsed.path == "/api/upload":
            if session["role"] != "admin":
                self.send_json(403, {"error": "Файл нэмэх эрх зөвхөн admin хэрэглэгчид байна."})
                return
            files = body.get("files", [])
            if not isinstance(files, list) or not files:
                self.send_json(400, {"error": "Upload хийх файл алга."})
                return
            created = []
            warnings = []
            for file_payload in files:
                parsed_file = parse_uploaded_file(file_payload, session["email"])
                if parsed_file and parsed_file.get("document"):
                    document = parsed_file["document"]
                    insert_documents([document])
                    created.append(sanitize_document(document))
                    if parsed_file.get("warning"):
                        warnings.append(parsed_file["warning"])
            self.send_json(
                201,
                {
                    "documents": created,
                    "warnings": warnings,
                    "folders": list_document_folders(),
                },
            )
            return

        if parsed.path == "/api/chat/upload":
            files = body.get("files", [])
            if not isinstance(files, list) or not files:
                self.send_json(400, {"error": "Upload хийх файл алга."})
                return
            created = []
            warnings = []
            for file_payload in files:
                chat_payload = {**file_payload, "folder": "Чат upload"}
                parsed_file = parse_uploaded_file(chat_payload, session["email"])
                if parsed_file and parsed_file.get("document"):
                    document = parsed_file["document"]
                    created.append(document)
                    if parsed_file.get("warning"):
                        warnings.append(parsed_file["warning"])
            append_chat_uploads(session["userId"], created)
            self.send_json(
                201,
                {
                    "documents": [sanitize_document(document) for document in created],
                    "warnings": warnings,
                },
            )
            return

        if parsed.path == "/api/submission/upload":
            files = body.get("files", [])
            if not isinstance(files, list) or not files:
                self.send_json(400, {"error": "Илгээх баримт алга."})
                return

            created_submissions = []
            needs_resubmit = False
            for file_payload in files:
                submission_payload = {**file_payload, "folder": "Илгээсэн баримт"}
                parsed_file = parse_uploaded_file(submission_payload, session["email"])
                if not parsed_file or not parsed_file.get("document"):
                    needs_resubmit = True
                    continue

                document = parsed_file["document"]
                warning_text = str(parsed_file.get("warning") or "").lower()
                summary_text = str(document.get("summary") or "").lower()
                status = (
                    "needs_resubmit"
                    if "уншиж чадсангүй" in warning_text
                    or "embedded text олдсонгүй" in summary_text
                    or "ocr шаардлагатай" in summary_text
                    else "processed"
                )
                if status != "processed":
                    needs_resubmit = True

                submission = create_document_submission(
                    session["userId"],
                    session["email"],
                    document,
                    status,
                )
                created_submissions.append(sanitize_submission(submission))

            if not created_submissions:
                self.send_json(
                    201,
                    {
                        "submissions": [],
                        "message": "Баримтын зургийг дахин явуулна уу.",
                        "tone": "warning",
                    },
                )
                return

            self.send_json(
                201,
                {
                    "submissions": created_submissions,
                    "message": "Баримтыг илгээлээ." if not needs_resubmit else "Баримтыг хүлээн авлаа. Хэрэв текст тодорхой биш бол баримтын зургийг дахин явуулна уу.",
                    "tone": "success" if not needs_resubmit else "warning",
                },
            )
            return

        if parsed.path == "/api/chat/upload/delete":
            document_id = str(body.get("documentId", "")).strip()
            if not document_id:
                self.send_json(400, {"error": "Файл ID дутуу байна."})
                return
            remaining = remove_chat_upload(session["userId"], document_id)
            self.send_json(
                200,
                {"documents": [sanitize_document(document) for document in remaining]},
            )
            return

        if parsed.path == "/api/admin/folder/create":
            if session["role"] != "admin":
                self.send_json(403, {"error": "Admin эрх шаардлагатай."})
                return
            folder_name = sanitize_folder_name(body.get("name", ""))
            folders = create_folder(folder_name)
            self.send_json(201, {"folders": folders, "selectedFolder": folder_name})
            return

        if parsed.path == "/api/admin/folder/rename":
            if session["role"] != "admin":
                self.send_json(403, {"error": "Admin эрх шаардлагатай."})
                return
            old_name = sanitize_folder_name(body.get("oldName", ""))
            new_name = sanitize_folder_name(body.get("newName", ""))
            if not old_name or not new_name:
                self.send_json(400, {"error": "Folder нэр дутуу байна."})
                return
            ok, message, documents = rename_folder(old_name, new_name)
            if not ok:
                self.send_json(400, {"error": message})
                return
            path_updates = move_folder_storage(old_name, new_name)
            for old_path, new_path in path_updates.items():
                for document in documents:
                    if document.get("storagePath") == old_path:
                        update_document_storage_path(document["id"], new_path, new_name)
            self.send_json(
                200,
                {
                    "message": message,
                    "folders": list_document_folders(),
                    "documents": [sanitize_document(document) for document in list_documents()],
                },
            )
            return

        if parsed.path == "/api/admin/folder/delete":
            if session["role"] != "admin":
                self.send_json(403, {"error": "Admin эрх шаардлагатай."})
                return
            folder_name = sanitize_folder_name(body.get("name", ""))
            ok, message = delete_folder(folder_name)
            if not ok:
                self.send_json(400, {"error": message})
                return
            delete_folder_storage(folder_name)
            self.send_json(200, {"folders": list_document_folders(), "message": message})
            return

        if parsed.path == "/api/admin/document/delete":
            if session["role"] != "admin":
                self.send_json(403, {"error": "Admin эрх шаардлагатай."})
                return
            document_id = str(body.get("documentId", "")).strip()
            document = delete_document_record(document_id)
            if not document:
                self.send_json(404, {"error": "Файл олдсонгүй."})
                return
            delete_document_storage(document)
            self.send_json(
                200,
                {
                    "documents": [sanitize_document(item) for item in list_documents()],
                    "folders": list_document_folders(),
                },
            )
            return

        if parsed.path == "/api/admin/submission/delete":
            if session["role"] != "admin":
                self.send_json(403, {"error": "Admin эрх шаардлагатай."})
                return
            submission_id = str(body.get("submissionId", "")).strip()
            submission = delete_document_submission_record(submission_id)
            if not submission:
                self.send_json(404, {"error": "Баримт олдсонгүй."})
                return
            delete_document_storage(submission)
            self.send_json(
                200,
                {
                    "submissions": [sanitize_submission(item) for item in list_document_submissions()],
                },
            )
            return

        if parsed.path == "/api/admin/document/copy":
            if session["role"] != "admin":
                self.send_json(403, {"error": "Admin эрх шаардлагатай."})
                return
            document_id = str(body.get("documentId", "")).strip()
            target_folder = sanitize_folder_name(body.get("targetFolder", ""))
            source_document = get_document_by_id(document_id)
            if not source_document:
                self.send_json(404, {"error": "Файл олдсонгүй."})
                return

            copied_storage_path = copy_document_storage(source_document, target_folder)
            copied_document = {
                **source_document,
                "id": None,
                "folder": target_folder,
                "storagePath": copied_storage_path,
                "source": f"{source_document['source']} (copied)",
                "summary": summarize_content(source_document["content"]),
                "createdAt": utc_now(),
            }
            copied_document.pop("id", None)
            saved = save_copied_document(copied_document)
            create_folder(target_folder)
            self.send_json(
                201,
                {
                    "document": sanitize_document(saved),
                    "documents": [sanitize_document(item) for item in list_documents()],
                    "folders": list_document_folders(),
                },
            )
            return

        if parsed.path == "/api/chat":
            message_text = str(body.get("message", "")).strip()
            preferred_history_id = str(body.get("historyId", "")).strip() or None
            if not message_text:
                self.send_json(400, {"error": "Асуулт хоосон байна."})
                return

            chat_documents = get_chat_uploads(session["userId"])
            history = get_history_by_id(preferred_history_id, session["userId"]) if preferred_history_id else None
            if not history:
                history = create_history_record(session["userId"], build_history_title(message_text))
            if not history["messages"]:
                update_history_title(history["id"], build_history_title(message_text))

            append_message(history["id"], create_message("user", message_text), len(history["messages"]))
            refreshed_before_reply = get_history_by_id(history["id"], session["userId"]) or history
            if should_skip_document_search(message_text, refreshed_before_reply["messages"]):
                db_search_results = []
            else:
                db_search_results = search_documents(collect_search_terms(message_text))
            documents = merge_documents(chat_documents, db_search_results)
            all_documents = documents
            if needs_full_document_scan(message_text, refreshed_before_reply["messages"]):
                all_documents = merge_documents(chat_documents, list_documents())
            ranked_docs = rank_documents(message_text, documents)
            reply_documents = select_reply_documents(
                message_text,
                ranked_docs,
                all_documents,
                refreshed_before_reply["messages"],
            )
            fallback_reply = build_answer(
                message_text,
                ranked_docs,
                all_documents,
                refreshed_before_reply["messages"],
            )
            reply_text, citation_documents = self.generate_reply_payload(
                message_text,
                ranked_docs,
                reply_documents,
                all_documents,
                refreshed_before_reply["messages"],
                fallback_reply,
            )
            assistant = create_message(
                "bot",
                reply_text,
                [sanitize_document(doc) for doc in citation_documents],
            )
            append_message(history["id"], assistant, len(refreshed_before_reply["messages"]))
            touch_history(history["id"])
            refreshed = get_history_by_id(history["id"], session["userId"])
            self.send_json(
                200,
                {
                    "history": refreshed,
                    "reply": assistant,
                    "documents": [sanitize_document(document) for document in all_documents],
                },
            )
            return

        self.send_json(404, {"error": "Not found"})

    def serve_static(self, raw_path: str) -> None:
        if raw_path == "/":
            self.send_response(302)
            self.send_cors_headers()
            self.send_header("Location", "/login")
            self.end_headers()
            return

        route_map = {
            "/login": ROOT_DIR / "login.html",
            "/chat": ROOT_DIR / "chat.html",
        }
        target = route_map.get(raw_path)
        if target is None:
            safe_path = (ROOT_DIR / raw_path.lstrip("/")).resolve()
            if not str(safe_path).startswith(str(ROOT_DIR)):
                self.send_text(403, "Forbidden")
                return
            target = safe_path

        if not target.exists() or target.is_dir():
            self.send_text(404, "Not found")
            return

        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_cors_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(target.stat().st_size))
        self.send_header("Last-Modified", formatdate(target.stat().st_mtime, usegmt=True))
        self.end_headers()
        self.wfile.write(target.read_bytes())

    def read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(content_length) if content_length else b""
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError("Invalid JSON body") from error

    def require_session(self) -> dict[str, str] | None:
        session = get_session(self)
        if not session:
            self.send_json(401, {"error": "Session дууссан байна. Дахин нэвтэрнэ үү."})
            return None
        return session

    def get_cors_origin(self) -> str | None:
        origin = str(self.headers.get("Origin", "") or "").strip()
        if not origin:
            return None

        allowed_prefixes = (
            "http://127.0.0.1:",
            "http://localhost:",
            "http://[::1]:",
            "https://127.0.0.1:",
            "https://localhost:",
            "https://[::1]:",
        )
        allowed_exact = {
            "http://chat.sosmedica.mn",
            "https://chat.sosmedica.mn",
        }
        if origin.startswith(allowed_prefixes) or origin in allowed_exact:
            return origin
        return None

    def send_cors_headers(self) -> None:
        origin = self.get_cors_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def generate_reply_payload(
        self,
        message_text: str,
        ranked_docs: list[dict[str, Any]],
        reply_documents: list[dict[str, Any]],
        all_documents: list[dict[str, Any]],
        history_messages: list[dict[str, Any]],
        fallback_reply: str,
    ) -> tuple[str, list[dict[str, Any]]]:
        if not is_ai_configured():
            return fallback_reply, reply_documents[:3] if reply_documents else []

        if should_force_local_answer(message_text, ranked_docs, all_documents, history_messages):
            return fallback_reply, reply_documents[:3] if reply_documents else []

        context_documents = reply_documents[:3]
        if not context_documents and has_confident_match(message_text, ranked_docs):
            context_documents = ranked_docs[:3]

        try:
            reply_text = maybe_generate_ai_answer(
                message_text,
                context_documents,
                history_messages,
            ) or fallback_reply
            return reply_text, context_documents if context_documents else []
        except RuntimeError as error:
            print(f"[AI fallback] {error}")
            return fallback_reply, reply_documents[:3] if reply_documents else []

    def send_text(self, status_code: int, text: str) -> None:
        data = text.encode("utf-8")
        self.send_response(status_code)
        self.send_cors_headers()
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args) -> None:
        return


def main() -> None:
    ensure_bootstrap()
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f"Server listening on http://{HOST}:{PORT}")
    print(f"SQLite DB: {DB_PATH}")
    server.serve_forever()
