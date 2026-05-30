from __future__ import annotations

import secrets
from uuid import uuid4

from .chat_logic import (
    build_answer,
    collect_search_terms,
    needs_full_document_scan,
    rank_documents,
    resolve_effective_question,
    select_reply_documents,
    should_skip_document_search,
)
from .documents import (
    copy_document_storage,
    delete_folder_storage,
    delete_document_storage,
    delete_storage_asset,
    move_folder_storage,
    parse_submission_image_file,
    parse_uploaded_file,
    save_employee_photo,
)
from .google_translate_service import maybe_translate_text_with_google
from .http_server_state import (
    SESSIONS,
    append_chat_uploads,
    clear_chat_uploads,
    get_chat_uploads,
    get_session,
    merge_documents,
    remove_chat_upload,
    run_employee_sync_import,
)
from .store import (
    append_message,
    create_document_submission,
    create_folder,
    create_history_record,
    create_message,
    delete_document_submission_record,
    delete_employee_record,
    delete_history,
    delete_document_record,
    delete_folder,
    find_user_by_credentials,
    get_document_by_id,
    get_employee_by_id,
    get_history_by_id,
    insert_documents,
    list_document_folders,
    list_documents,
    list_document_submissions,
    list_employees,
    list_history_summaries_by_user,
    rename_folder,
    rename_history,
    sanitize_document,
    sanitize_employee,
    sanitize_submission,
    sanitize_user,
    save_copied_document,
    save_employee_record,
    search_documents,
    summarize_history,
    touch_history,
    update_document_storage_path,
    update_history_title,
)
from .text_utils import build_history_title, sanitize_folder_name, summarize_content, utc_now


def handle_api_post(handler, parsed, body) -> None:
    if parsed.path == "/api/login":
        _handle_login(handler, body)
        return
    if parsed.path == "/api/logout":
        _handle_logout(handler)
        return
    if parsed.path == "/api/history/new":
        _handle_history_new(handler)
        return
    if parsed.path == "/api/history/rename":
        _handle_history_rename(handler, body)
        return
    if parsed.path == "/api/history/delete":
        _handle_history_delete(handler, body)
        return
    if parsed.path == "/api/upload":
        _handle_upload(handler, body)
        return
    if parsed.path == "/api/chat/upload":
        _handle_chat_upload(handler, body)
        return
    if parsed.path == "/api/submission/upload":
        _handle_submission_upload(handler, body)
        return
    if parsed.path == "/api/chat/upload/delete":
        _handle_chat_upload_delete(handler, body)
        return
    if parsed.path == "/api/translate":
        _handle_translate(handler, body)
        return
    if parsed.path == "/api/admin/folder/create":
        _handle_admin_folder_create(handler, body)
        return
    if parsed.path == "/api/admin/folder/rename":
        _handle_admin_folder_rename(handler, body)
        return
    if parsed.path == "/api/admin/folder/delete":
        _handle_admin_folder_delete(handler, body)
        return
    if parsed.path == "/api/admin/document/delete":
        _handle_admin_document_delete(handler, body)
        return
    if parsed.path == "/api/admin/submission/delete":
        _handle_admin_submission_delete(handler, body)
        return
    if parsed.path == "/api/admin/document/copy":
        _handle_admin_document_copy(handler, body)
        return
    if parsed.path == "/api/admin/employee/create":
        _handle_admin_employee_create(handler, body)
        return
    if parsed.path == "/api/admin/employee/update":
        _handle_admin_employee_update(handler, body)
        return
    if parsed.path == "/api/admin/employee/delete":
        _handle_admin_employee_delete(handler, body)
        return
    if parsed.path == "/api/admin/employee/sync":
        _handle_admin_employee_sync(handler)
        return
    if parsed.path == "/api/chat":
        _handle_chat(handler, body)
        return

    handler.send_json(404, {"error": "Not found"})


def _handle_login(handler, body) -> None:
    email = body.get("email", "")
    password = body.get("password", "")
    print(
        "[api] /api/login request",
        {
            "email": str(email).strip().lower(),
            "password_length": len(str(password or "").strip()),
            "remote": handler.client_address[0] if handler.client_address else "",
            "user_agent": handler.headers.get("User-Agent", "")[:120],
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
        handler.send_json(401, {"error": "И-мэйл эсвэл нууц үг буруу байна."})
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
    handler.send_json(200, {"token": token, "user": sanitize_user(user)})


def _handle_logout(handler) -> None:
    session = get_session(handler, allow_guest=True)
    if session:
        clear_chat_uploads(session["userId"])
        if session.get("token"):
            SESSIONS.pop(session["token"], None)
    handler.send_json(200, {"ok": True})


def _handle_history_new(handler) -> None:
    session = handler.require_session(allow_guest=True)
    if not session:
        return
    history = create_history_record(session["userId"], "Шинэ чат")
    handler.send_json(201, {"history": summarize_history(history)})


def _handle_history_rename(handler, body) -> None:
    session = handler.require_session(allow_guest=True)
    if not session:
        return
    history_id = str(body.get("historyId", "")).strip()
    title = build_history_title(str(body.get("title", "")).strip())
    if not history_id or not title:
        handler.send_json(400, {"error": "Чатын нэр хоосон байна."})
        return
    if not rename_history(history_id, session["userId"], title):
        handler.send_json(404, {"error": "Chat history олдсонгүй."})
        return
    handler.send_json(200, {"histories": list_history_summaries_by_user(session["userId"])})


def _handle_history_delete(handler, body) -> None:
    session = handler.require_session(allow_guest=True)
    if not session:
        return
    history_id = str(body.get("historyId", "")).strip()
    if not history_id:
        handler.send_json(400, {"error": "Chat history ID дутуу байна."})
        return
    if not delete_history(history_id, session["userId"]):
        handler.send_json(404, {"error": "Chat history олдсонгүй."})
        return
    handler.send_json(200, {"histories": list_history_summaries_by_user(session["userId"])})


def _handle_upload(handler, body) -> None:
    session = handler.require_session()
    if not session:
        return
    if session["role"] != "admin":
        handler.send_json(403, {"error": "Файл нэмэх эрх зөвхөн admin хэрэглэгчид байна."})
        return
    files = body.get("files", [])
    if not isinstance(files, list) or not files:
        handler.send_json(400, {"error": "Upload хийх файл алга."})
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
    handler.send_json(
        201,
        {
            "documents": created,
            "warnings": warnings,
            "folders": list_document_folders(),
        },
    )


def _handle_chat_upload(handler, body) -> None:
    session = handler.require_session(allow_guest=True)
    if not session:
        return
    files = body.get("files", [])
    if not isinstance(files, list) or not files:
        handler.send_json(400, {"error": "Upload хийх файл алга."})
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
    handler.send_json(
        201,
        {
            "documents": [sanitize_document(document) for document in created],
            "warnings": warnings,
        },
    )


def _handle_submission_upload(handler, body) -> None:
    session = handler.require_session(allow_guest=True)
    if not session:
        return
    files = body.get("files", [])
    if not isinstance(files, list) or not files:
        handler.send_json(400, {"error": "Илгээх баримт алга."})
        return

    created_submissions = []
    needs_resubmit = False
    for file_payload in files:
        parsed_file = parse_submission_image_file(file_payload, session["email"])
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
        handler.send_json(
            201,
            {
                "submissions": [],
                "message": "Баримтын зургийг дахин явуулна уу.",
                "tone": "warning",
            },
        )
        return

    handler.send_json(
        201,
        {
            "submissions": created_submissions,
            "message": "Баримтыг илгээлээ." if not needs_resubmit else "Баримтыг хүлээн авлаа. Хэрэв текст тодорхой биш бол баримтын зургийг дахин явуулна уу.",
            "tone": "success" if not needs_resubmit else "warning",
        },
    )


def _handle_chat_upload_delete(handler, body) -> None:
    session = handler.require_session(allow_guest=True)
    if not session:
        return
    document_id = str(body.get("documentId", "")).strip()
    if not document_id:
        handler.send_json(400, {"error": "Файл ID дутуу байна."})
        return
    remaining = remove_chat_upload(session["userId"], document_id)
    handler.send_json(
        200,
        {"documents": [sanitize_document(document) for document in remaining]},
    )


def _handle_translate(handler, body) -> None:
    session = handler.require_session(allow_guest=True)
    if not session:
        return
    text = str(body.get("text", "")).strip()
    source_language = str(body.get("sourceLanguage", "auto")).strip() or "auto"
    target_language = str(body.get("targetLanguage", "")).strip()
    if not text:
        handler.send_json(400, {"error": "Орчуулах текстээ оруулна уу."})
        return
    if not target_language:
        handler.send_json(400, {"error": "Орчуулах хэлээ сонгоно уу."})
        return

    try:
        payload = maybe_translate_text_with_google(
            text,
            source_language,
            target_language,
        )
    except RuntimeError as error:
        handler.send_json(502, {"error": str(error) or "Орчуулга хийх үед алдаа гарлаа."})
        return
    handler.send_json(200, payload)


def _ensure_admin_session(handler):
    session = handler.require_session()
    if not session:
        return None
    if session["role"] != "admin":
        handler.send_json(403, {"error": "Admin эрх шаардлагатай."})
        return None
    return session


def _handle_admin_folder_create(handler, body) -> None:
    if not _ensure_admin_session(handler):
        return
    folder_name = sanitize_folder_name(body.get("name", ""))
    folders = create_folder(folder_name)
    handler.send_json(201, {"folders": folders, "selectedFolder": folder_name})


def _handle_admin_folder_rename(handler, body) -> None:
    if not _ensure_admin_session(handler):
        return
    old_name = sanitize_folder_name(body.get("oldName", ""))
    new_name = sanitize_folder_name(body.get("newName", ""))
    if not old_name or not new_name:
        handler.send_json(400, {"error": "Folder нэр дутуу байна."})
        return
    ok, message, documents = rename_folder(old_name, new_name)
    if not ok:
        handler.send_json(400, {"error": message})
        return
    path_updates = move_folder_storage(old_name, new_name)
    for old_path, new_path in path_updates.items():
        for document in documents:
            if document.get("storagePath") == old_path:
                update_document_storage_path(document["id"], new_path, new_name)
    handler.send_json(
        200,
        {
            "message": message,
            "folders": list_document_folders(),
            "documents": [sanitize_document(document) for document in list_documents()],
        },
    )


def _handle_admin_folder_delete(handler, body) -> None:
    if not _ensure_admin_session(handler):
        return
    folder_name = sanitize_folder_name(body.get("name", ""))
    ok, message = delete_folder(folder_name)
    if not ok:
        handler.send_json(400, {"error": message})
        return
    delete_folder_storage(folder_name)
    handler.send_json(200, {"folders": list_document_folders(), "message": message})


def _handle_admin_document_delete(handler, body) -> None:
    if not _ensure_admin_session(handler):
        return
    document_id = str(body.get("documentId", "")).strip()
    document = delete_document_record(document_id)
    if not document:
        handler.send_json(404, {"error": "Файл олдсонгүй."})
        return
    delete_document_storage(document)
    handler.send_json(
        200,
        {
            "documents": [sanitize_document(item) for item in list_documents()],
            "folders": list_document_folders(),
        },
    )


def _handle_admin_submission_delete(handler, body) -> None:
    if not _ensure_admin_session(handler):
        return
    submission_id = str(body.get("submissionId", "")).strip()
    submission = delete_document_submission_record(submission_id)
    if not submission:
        handler.send_json(404, {"error": "Баримт олдсонгүй."})
        return
    delete_document_storage(submission)
    handler.send_json(
        200,
        {
            "submissions": [sanitize_submission(item) for item in list_document_submissions()],
        },
    )


def _handle_admin_document_copy(handler, body) -> None:
    if not _ensure_admin_session(handler):
        return
    document_id = str(body.get("documentId", "")).strip()
    target_folder = sanitize_folder_name(body.get("targetFolder", ""))
    source_document = get_document_by_id(document_id)
    if not source_document:
        handler.send_json(404, {"error": "Файл олдсонгүй."})
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
    handler.send_json(
        201,
        {
            "document": sanitize_document(saved),
            "documents": [sanitize_document(item) for item in list_documents()],
            "folders": list_document_folders(),
        },
    )


def _build_employee_display_name(employee_payload: dict, employee_id: str) -> str:
    return " ".join(
        part for part in [
            str(employee_payload.get("firstNameEn", "") or "").strip(),
            str(employee_payload.get("lastNameEn", "") or "").strip(),
            str(employee_payload.get("firstNameMn", "") or "").strip(),
            str(employee_payload.get("lastNameMn", "") or "").strip(),
        ] if part
    ) or employee_id


def _handle_admin_employee_create(handler, body) -> None:
    if not _ensure_admin_session(handler):
        return
    employee_payload = body.get("employee", {})
    if not isinstance(employee_payload, dict):
        handler.send_json(400, {"error": "Ажилтны мэдээлэл буруу байна."})
        return

    employee_id = str(uuid4())
    display_name = _build_employee_display_name(employee_payload, employee_id)

    photo_storage_path = ""
    if employee_payload.get("photoContent"):
        photo_storage_path = save_employee_photo(
            employee_id,
            display_name,
            employee_payload.get("photoContent", ""),
            str(employee_payload.get("photoMimeType", "") or ""),
        )

    saved = save_employee_record(
        {
            **employee_payload,
            "photoStoragePath": photo_storage_path,
        },
        employee_id,
    )
    handler.send_json(
        201,
        {
            "employee": sanitize_employee(saved),
            "employees": [sanitize_employee(item) for item in list_employees()],
        },
    )


def _handle_admin_employee_update(handler, body) -> None:
    if not _ensure_admin_session(handler):
        return
    employee_id = str(body.get("employeeId", "")).strip()
    employee_payload = body.get("employee", {})
    if not employee_id or not isinstance(employee_payload, dict):
        handler.send_json(400, {"error": "Ажилтны мэдээлэл дутуу байна."})
        return
    existing = get_employee_by_id(employee_id)
    if not existing:
        handler.send_json(404, {"error": "Ажилтан олдсонгүй."})
        return

    photo_storage_path = str(existing.get("photoStoragePath", "") or "").strip()
    if employee_payload.get("removePhoto") and photo_storage_path:
        delete_storage_asset(photo_storage_path)
        photo_storage_path = ""
    if employee_payload.get("photoContent"):
        display_name = _build_employee_display_name(employee_payload, employee_id)
        photo_storage_path = save_employee_photo(
            employee_id,
            display_name,
            employee_payload.get("photoContent", ""),
            str(employee_payload.get("photoMimeType", "") or ""),
            previous_path=photo_storage_path,
        )

    saved = save_employee_record(
        {
            **existing,
            **employee_payload,
            "photoStoragePath": photo_storage_path,
        },
        employee_id,
    )
    handler.send_json(
        200,
        {
            "employee": sanitize_employee(saved),
            "employees": [sanitize_employee(item) for item in list_employees()],
        },
    )


def _handle_admin_employee_delete(handler, body) -> None:
    if not _ensure_admin_session(handler):
        return
    employee_id = str(body.get("employeeId", "")).strip()
    if not employee_id:
        handler.send_json(400, {"error": "Ажилтны ID дутуу байна."})
        return
    employee = delete_employee_record(employee_id)
    if not employee:
        handler.send_json(404, {"error": "Ажилтан олдсонгүй."})
        return
    if employee.get("photoStoragePath"):
        delete_storage_asset(str(employee.get("photoStoragePath", "") or ""))
    handler.send_json(
        200,
        {
            "employees": [sanitize_employee(item) for item in list_employees()],
        },
    )


def _handle_admin_employee_sync(handler) -> None:
    if not _ensure_admin_session(handler):
        return

    ok, message = run_employee_sync_import()
    if not ok:
        handler.send_json(500, {"error": message})
        return

    handler.send_json(
        200,
        {
            "message": message,
            "employees": [sanitize_employee(item) for item in list_employees()],
        },
    )


def _handle_chat(handler, body) -> None:
    session = handler.require_session(allow_guest=True)
    if not session:
        return
    message_text = str(body.get("message", "")).strip()
    preferred_history_id = str(body.get("historyId", "")).strip() or None
    if not message_text:
        handler.send_json(400, {"error": "Асуулт хоосон байна."})
        return

    chat_documents = get_chat_uploads(session["userId"])
    history = get_history_by_id(preferred_history_id, session["userId"]) if preferred_history_id else None
    if not history:
        history = create_history_record(session["userId"], build_history_title(message_text))
    if not history["messages"]:
        update_history_title(history["id"], build_history_title(message_text))

    append_message(history["id"], create_message("user", message_text), len(history["messages"]))
    refreshed_before_reply = get_history_by_id(history["id"], session["userId"]) or history
    effective_message_text = resolve_effective_question(message_text, refreshed_before_reply["messages"])
    if should_skip_document_search(effective_message_text, refreshed_before_reply["messages"]):
        db_search_results = []
    else:
        db_search_results = search_documents(collect_search_terms(effective_message_text))
    documents = merge_documents(chat_documents, db_search_results)
    all_documents = documents
    if needs_full_document_scan(effective_message_text, refreshed_before_reply["messages"]):
        all_documents = merge_documents(chat_documents, list_documents())
    ranked_docs = rank_documents(effective_message_text, documents)
    reply_documents = select_reply_documents(
        effective_message_text,
        ranked_docs,
        all_documents,
        refreshed_before_reply["messages"],
    )
    fallback_reply = build_answer(
        effective_message_text,
        ranked_docs,
        all_documents,
        refreshed_before_reply["messages"],
    )
    reply_text, citation_documents = handler.generate_reply_payload(
        effective_message_text,
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
    handler.send_json(
        200,
        {
            "history": refreshed,
            "reply": assistant,
            "documents": [sanitize_document(document) for document in all_documents],
        },
    )
