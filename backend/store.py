from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from .config import (
    DATA_DIR,
    DB_PATH,
    DEFAULT_DOCUMENT_FOLDERS,
    DOCS_PATH,
    HISTORIES_PATH,
    SEED_DOCUMENTS,
    SEED_USERS,
    UPLOAD_DIR,
    USERS_PATH,
)
from .documents import (
    IMAGE_EXTENSIONS,
    looks_like_base64_text,
    recover_submission_file,
    recover_uploaded_file,
)
from .text_utils import (
    build_history_title,
    build_text_chunks,
    extract_patient_fields,
    has_suspicious_receipt_fields,
    looks_like_receipt_text,
    parse_json,
    summarize_content,
    utc_now,
)


DB_LOCK = RLock()
DOCUMENT_LIST_CACHE: list[dict[str, Any]] | None = None


def normalize_login_email(value: str) -> str:
    return str(value or "").strip().lower()


def normalize_login_secret(value: str) -> str:
    cleaned = str(value or "").strip()
    for marker in ("\u200b", "\u200c", "\u200d", "\ufeff", "\u2060"):
        cleaned = cleaned.replace(marker, "")
    return cleaned


@contextmanager
def db_connect():
    with DB_LOCK:
        connection = sqlite3.connect(DB_PATH, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA synchronous = NORMAL")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()


def ensure_bootstrap() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    initialize_database()
    migrate_legacy_json_if_needed()
    seed_defaults_if_needed()
    sync_orphaned_uploads()
    repair_submission_uploads()


def invalidate_document_caches() -> None:
    global DOCUMENT_LIST_CACHE
    DOCUMENT_LIST_CACHE = None


def clone_document_entry(document: dict[str, Any]) -> dict[str, Any]:
    cloned = dict(document)
    tags = cloned.get("tags")
    if isinstance(tags, list):
        cloned["tags"] = list(tags)
    return cloned


def initialize_database() -> None:
    with db_connect() as conn:
        conn.executescript(
            """
            PRAGMA journal_mode = WAL;
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS users (
              id TEXT PRIMARY KEY,
              email TEXT NOT NULL UNIQUE,
              password TEXT NOT NULL,
              role TEXT NOT NULL,
              name TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS documents (
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              folder TEXT NOT NULL DEFAULT 'Ерөнхий',
              storage_path TEXT NOT NULL DEFAULT '',
              source TEXT NOT NULL,
              summary TEXT NOT NULL,
              content TEXT NOT NULL,
              tags_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS document_chunks (
              id TEXT PRIMARY KEY,
              document_id TEXT NOT NULL,
              chunk_index INTEGER NOT NULL,
              content TEXT NOT NULL,
              summary TEXT NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS document_patient_index (
              document_id TEXT PRIMARY KEY,
              patient_name TEXT NOT NULL DEFAULT '',
              parent_name TEXT NOT NULL DEFAULT '',
              register_number TEXT NOT NULL DEFAULT '',
              age TEXT NOT NULL DEFAULT '',
              gender TEXT NOT NULL DEFAULT '',
              visit_date TEXT NOT NULL DEFAULT '',
              doctor_name TEXT NOT NULL DEFAULT '',
              diagnosis TEXT NOT NULL DEFAULT '',
              recommendation TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks_fts USING fts5(
              chunk_id UNINDEXED,
              document_id UNINDEXED,
              title,
              summary,
              content,
              folder,
              tags,
              patient_name,
              source,
              tokenize='unicode61'
            );

            CREATE TABLE IF NOT EXISTS folders (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL UNIQUE,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS histories (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              title TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS messages (
              id TEXT PRIMARY KEY,
              history_id TEXT NOT NULL,
              role TEXT NOT NULL,
              text TEXT NOT NULL,
              citations_json TEXT NOT NULL,
              timestamp TEXT NOT NULL,
              sort_order INTEGER NOT NULL,
              FOREIGN KEY (history_id) REFERENCES histories(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS document_submissions (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              user_email TEXT NOT NULL,
              title TEXT NOT NULL,
              storage_path TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL,
              summary TEXT NOT NULL,
              content TEXT NOT NULL,
              tags_json TEXT NOT NULL,
              patient_fields_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_histories_user_updated
              ON histories(user_id, updated_at DESC);

            CREATE INDEX IF NOT EXISTS idx_messages_history_sort
              ON messages(history_id, sort_order ASC);

            CREATE INDEX IF NOT EXISTS idx_document_chunks_document
              ON document_chunks(document_id, chunk_index ASC);

            CREATE INDEX IF NOT EXISTS idx_patient_index_document
              ON document_patient_index(document_id);

            CREATE INDEX IF NOT EXISTS idx_document_submissions_user_created
              ON document_submissions(user_id, created_at DESC);
            """
        )
        ensure_document_folder_column(conn)
        ensure_document_storage_path_column(conn)
        ensure_folders_seeded(conn)
        rebuild_document_indexes_if_needed(conn)


def ensure_document_folder_column(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(documents)").fetchall()
    }
    if "folder" not in columns:
        conn.execute(
            "ALTER TABLE documents ADD COLUMN folder TEXT NOT NULL DEFAULT 'Ерөнхий'"
        )
        conn.execute(
            "UPDATE documents SET folder = 'Ерөнхий' WHERE folder IS NULL OR trim(folder) = ''"
        )


def ensure_document_storage_path_column(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(documents)").fetchall()
    }
    if "storage_path" not in columns:
        conn.execute(
            "ALTER TABLE documents ADD COLUMN storage_path TEXT NOT NULL DEFAULT ''"
        )


def ensure_folders_seeded(conn: sqlite3.Connection) -> None:
    existing = {
        row["name"]
        for row in conn.execute("SELECT name FROM folders").fetchall()
    }
    for folder_name in DEFAULT_DOCUMENT_FOLDERS:
        if folder_name not in existing:
            conn.execute(
                "INSERT INTO folders (id, name, created_at) VALUES (?, ?, ?)",
                (str(uuid4()), folder_name, utc_now()),
            )


def rebuild_document_indexes_if_needed(conn: sqlite3.Connection) -> None:
    document_count = int(conn.execute("SELECT COUNT(*) AS count FROM documents").fetchone()["count"])
    patient_index_count = int(
        conn.execute("SELECT COUNT(*) AS count FROM document_patient_index").fetchone()["count"]
    )
    chunk_count = int(conn.execute("SELECT COUNT(*) AS count FROM document_chunks").fetchone()["count"])
    fts_count = int(conn.execute("SELECT COUNT(*) AS count FROM document_chunks_fts").fetchone()["count"])

    if document_count == 0:
        conn.execute("DELETE FROM document_chunks")
        conn.execute("DELETE FROM document_patient_index")
        conn.execute("DELETE FROM document_chunks_fts")
        return

    if patient_index_count == document_count and chunk_count > 0 and fts_count > 0:
        return

    conn.execute("DELETE FROM document_chunks")
    conn.execute("DELETE FROM document_patient_index")
    conn.execute("DELETE FROM document_chunks_fts")

    rows = conn.execute(
        """
        SELECT id, title, folder, storage_path, source, summary, content, tags_json, created_at
        FROM documents
        ORDER BY datetime(created_at) DESC, rowid DESC
        """
    ).fetchall()
    for row in rows:
        refresh_document_indexes(conn, row_to_document(row))


def refresh_document_indexes(conn: sqlite3.Connection, document: dict[str, Any]) -> None:
    document_id = str(document["id"])
    tags = document.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    tags_text = " ".join(str(tag) for tag in tags if tag)
    patient_fields = extract_patient_fields(document["title"], document["content"])

    clear_document_indexes(conn, document_id)

    conn.execute(
        """
        INSERT OR REPLACE INTO document_patient_index (
          document_id,
          patient_name,
          parent_name,
          register_number,
          age,
          gender,
          visit_date,
          doctor_name,
          diagnosis,
          recommendation,
          created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document_id,
            str(patient_fields.get("patientName", "")),
            str(patient_fields.get("parentName", "")),
            str(patient_fields.get("registerNumber", "")),
            str(patient_fields.get("age", "")),
            str(patient_fields.get("gender", "")),
            str(patient_fields.get("visitDate", "")),
            str(patient_fields.get("doctorName", "")),
            str(patient_fields.get("diagnosis", "")),
            str(patient_fields.get("recommendation", "")),
            document.get("createdAt", utc_now()),
        ),
    )

    chunks = build_text_chunks(document["content"])
    if not chunks:
        chunks = [str(document["content"]).strip()]

    for chunk_index, chunk_content in enumerate(chunks):
        chunk_id = str(uuid4())
        chunk_summary = summarize_content(chunk_content)
        conn.execute(
            """
            INSERT INTO document_chunks (id, document_id, chunk_index, content, summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                chunk_id,
                document_id,
                chunk_index,
                chunk_content,
                chunk_summary,
                document.get("createdAt", utc_now()),
            ),
        )
        conn.execute(
            """
            INSERT INTO document_chunks_fts (
              chunk_id,
              document_id,
              title,
              summary,
              content,
              folder,
              tags,
              patient_name,
              source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk_id,
                document_id,
                document["title"],
                document["summary"],
                chunk_content,
                document.get("folder", "Ерөнхий"),
                tags_text,
                str(patient_fields.get("patientName", "")),
                document.get("source", ""),
            ),
        )


def clear_document_indexes(conn: sqlite3.Connection, document_id: str) -> None:
    conn.execute("DELETE FROM document_chunks_fts WHERE document_id = ?", (document_id,))
    conn.execute("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))
    conn.execute("DELETE FROM document_patient_index WHERE document_id = ?", (document_id,))


def migrate_legacy_json_if_needed() -> None:
    if count_rows("users") or count_rows("documents") or count_rows("histories"):
        return

    legacy_users = read_json(USERS_PATH, [])
    legacy_documents = read_json(DOCS_PATH, [])
    legacy_histories = read_json(HISTORIES_PATH, [])

    if legacy_users:
        insert_users(legacy_users)
    if legacy_documents:
        insert_documents(legacy_documents)
    if legacy_histories:
        insert_histories(legacy_histories)


def seed_defaults_if_needed() -> None:
    if count_rows("users") == 0:
        insert_users(SEED_USERS)
    if count_rows("documents") == 0:
        insert_documents(SEED_DOCUMENTS)
    ensure_default_folders()


def ensure_default_folders() -> None:
    with db_connect() as conn:
        ensure_folders_seeded(conn)


def sync_orphaned_uploads() -> None:
    with db_connect() as conn:
        known_storage_paths = {
            str(row["storage_path"]).strip()
            for row in conn.execute("SELECT storage_path FROM documents WHERE storage_path != ''").fetchall()
        }

    recovered_documents: list[dict[str, Any]] = []
    for saved_path in sorted(UPLOAD_DIR.rglob("*")):
        if not saved_path.is_file():
            continue
        relative_path = str(saved_path.relative_to(UPLOAD_DIR))
        if relative_path in known_storage_paths:
            continue
        recovered = recover_uploaded_file(saved_path)
        if recovered:
            recovered_documents.append(recovered)

    if recovered_documents:
        insert_documents(recovered_documents)


def read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:
        return fallback


def count_rows(table_name: str) -> int:
    with db_connect() as conn:
        return int(conn.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()["count"])


def insert_users(users: list[dict[str, Any]]) -> None:
    with db_connect() as conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO users (id, email, password, role, name)
            VALUES (:id, :email, :password, :role, :name)
            """,
            [
                {
                    "id": user.get("id", str(uuid4())),
                    "email": user["email"],
                    "password": user["password"],
                    "role": user["role"],
                    "name": user["name"],
                }
                for user in users
            ],
        )


def ensure_guest_user(user_id: str, email: str = "guest@sosmedica.mn", name: str = "Зочин") -> None:
    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id:
        return

    insert_users(
        [
            {
                "id": normalized_user_id,
                "email": normalize_login_email(email) or "guest@sosmedica.mn",
                "password": "__guest__",
                "role": "guest",
                "name": str(name or "Зочин").strip() or "Зочин",
            }
        ]
    )


def insert_documents(documents: list[dict[str, Any]]) -> None:
    with db_connect() as conn:
        prepared_documents: list[dict[str, Any]] = []
        for document in documents:
            prepared = {
                "id": document.get("id", str(uuid4())),
                "title": document["title"],
                "folder": document.get("folder", "Ерөнхий"),
                "storage_path": document.get("storagePath", ""),
                "source": document["source"],
                "summary": document["summary"],
                "content": document["content"],
                "tags_json": json.dumps(document.get("tags", []), ensure_ascii=False),
                "created_at": document.get("createdAt", utc_now()),
            }
            conn.execute(
                """
                INSERT OR REPLACE INTO documents (id, title, folder, storage_path, source, summary, content, tags_json, created_at)
                VALUES (:id, :title, :folder, :storage_path, :source, :summary, :content, :tags_json, :created_at)
                """,
                prepared,
            )
            prepared_documents.append(prepared)

        for prepared in prepared_documents:
            refresh_document_indexes(
                conn,
                {
                    "id": prepared["id"],
                    "title": prepared["title"],
                    "folder": prepared["folder"],
                    "storagePath": prepared["storage_path"],
                    "source": prepared["source"],
                    "summary": prepared["summary"],
                    "content": prepared["content"],
                    "tags": parse_json(prepared["tags_json"], []),
                    "createdAt": prepared["created_at"],
                },
            )
    invalidate_document_caches()


def insert_histories(histories: list[dict[str, Any]]) -> None:
    with db_connect() as conn:
        for history in histories:
            history_id = history.get("id", str(uuid4()))
            conn.execute(
                """
                INSERT OR REPLACE INTO histories (id, user_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    history_id,
                    history["userId"],
                    history.get("title", "Шинэ чат"),
                    history.get("createdAt", utc_now()),
                    history.get("updatedAt", utc_now()),
                ),
            )
            for index, message in enumerate(history.get("messages", [])):
                conn.execute(
                    """
                    INSERT OR REPLACE INTO messages (id, history_id, role, text, citations_json, timestamp, sort_order)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message.get("id", str(uuid4())),
                        history_id,
                        message["role"],
                        message["text"],
                        json.dumps(message.get("citations", []), ensure_ascii=False),
                        message.get("timestamp", utc_now()),
                        index,
                    ),
                )


def find_user_by_credentials(email: str, password: str) -> dict[str, Any] | None:
    normalized_email = normalize_login_email(email)
    normalized_password = normalize_login_secret(password)

    print(
        "[auth] lookup",
        {
            "email": normalized_email,
            "password_length": len(normalized_password),
        },
        flush=True,
    )

    with db_connect() as conn:
        rows = conn.execute(
            """
            SELECT id, email, password, role, name
            FROM users
            WHERE lower(email) = ?
            """,
            (normalized_email,),
        ).fetchall()

    print(
        "[auth] matched_email_rows",
        {
            "email": normalized_email,
            "row_count": len(rows),
            "users": [
                {
                    "id": row["id"],
                    "email": row["email"],
                    "password_length": len(normalize_login_secret(row["password"])),
                    "role": row["role"],
                }
                for row in rows
            ],
        },
        flush=True,
    )

    for row in rows:
        if normalize_login_secret(row["password"]) == normalized_password:
            print(
                "[auth] db_match_success",
                {"email": normalized_email, "user_id": row["id"], "role": row["role"]},
                flush=True,
            )
            return dict(row)

    for seed_user in SEED_USERS:
        if (
            normalize_login_email(seed_user["email"]) == normalized_email
            and normalize_login_secret(seed_user["password"]) == normalized_password
        ):
            print(
                "[auth] seed_match_success",
                {"email": normalized_email, "user_id": seed_user["id"], "role": seed_user["role"]},
                flush=True,
            )
            insert_users([seed_user])
            with db_connect() as conn:
                recovered = conn.execute(
                    """
                    SELECT id, email, password, role, name
                    FROM users
                    WHERE lower(email) = ?
                    """,
                    (normalized_email,),
                ).fetchone()
            return dict(recovered) if recovered else dict(seed_user)

    print(
        "[auth] login_failed",
        {"email": normalized_email, "password_length": len(normalized_password)},
        flush=True,
    )
    return None


def list_documents() -> list[dict[str, Any]]:
    global DOCUMENT_LIST_CACHE
    if DOCUMENT_LIST_CACHE is not None:
        return [clone_document_entry(document) for document in DOCUMENT_LIST_CACHE]

    with db_connect() as conn:
        rows = conn.execute(
            """
            SELECT id, title, folder, storage_path, source, summary, content, tags_json, created_at
            FROM documents
            ORDER BY datetime(created_at) DESC, rowid DESC
            """
        ).fetchall()
    DOCUMENT_LIST_CACHE = [row_to_document(row) for row in rows]
    return [clone_document_entry(document) for document in DOCUMENT_LIST_CACHE]


def create_document_submission(
    user_id: str,
    user_email: str,
    document: dict[str, Any],
    status: str,
) -> dict[str, Any]:
    patient_fields = extract_patient_fields(document["title"], document["content"])
    if (
        status != "needs_resubmit"
        and (
            not looks_like_receipt_text(str(document.get("content", "") or ""))
            or has_suspicious_receipt_fields(patient_fields, str(document.get("title", "") or ""))
        )
    ):
        status = "needs_resubmit"

    submission = {
        "id": str(uuid4()),
        "userId": user_id,
        "userEmail": user_email,
        "title": document["title"],
        "storagePath": document.get("storagePath", ""),
        "status": status,
        "summary": document.get("summary", ""),
        "content": document.get("content", ""),
        "tags": document.get("tags", []),
        "patientFields": patient_fields,
        "createdAt": document.get("createdAt", utc_now()),
    }
    with db_connect() as conn:
        conn.execute(
            """
            INSERT INTO document_submissions (
              id, user_id, user_email, title, storage_path, status, summary,
              content, tags_json, patient_fields_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                submission["id"],
                submission["userId"],
                submission["userEmail"],
                submission["title"],
                submission["storagePath"],
                submission["status"],
                submission["summary"],
                submission["content"],
                json.dumps(submission["tags"], ensure_ascii=False),
                json.dumps(submission["patientFields"], ensure_ascii=False),
                submission["createdAt"],
            ),
        )
    return submission


def repair_submission_uploads() -> None:
    with db_connect() as conn:
        rows = conn.execute(
            """
            SELECT id, user_email, title, storage_path, status, summary, content, tags_json, patient_fields_json, created_at
            FROM document_submissions
            ORDER BY datetime(created_at) DESC, rowid DESC
            """
        ).fetchall()

        for row in rows:
            title = str(row["title"] or "")
            extension = Path(title).suffix.lower()
            if extension not in IMAGE_EXTENSIONS:
                continue

            summary = str(row["summary"] or "")
            content = str(row["content"] or "")
            patient_fields = parse_json(row["patient_fields_json"], {})
            combined_text = f"{summary}\n{content}".strip()
            needs_repair = (
                summary.startswith("AAAA")
                or content.startswith("AAAA")
                or not patient_fields.get("totalAmount")
                or not patient_fields.get("itemInfo")
                or not patient_fields.get("organizationName")
                or not patient_fields.get("receiptDate")
                or not looks_like_receipt_text(combined_text)
                or has_suspicious_receipt_fields(patient_fields, title)
            )
            if not needs_repair:
                continue

            storage_path = str(row["storage_path"] or "").strip()
            if not storage_path:
                continue

            saved_path = (UPLOAD_DIR / storage_path).resolve()
            upload_root = UPLOAD_DIR.resolve()
            if not str(saved_path).startswith(str(upload_root)) or not saved_path.exists() or saved_path.is_dir():
                continue

            recovered = recover_submission_file(saved_path, title, str(row["user_email"] or "Recovered submission"))
            if not recovered:
                continue

            refreshed_patient_fields = extract_patient_fields(
                str(recovered.get("title", title)),
                str(recovered.get("content", "")),
            )
            refreshed_patient_fields = {
                **patient_fields,
                **refreshed_patient_fields,
            }
            refreshed_combined_text = f"{recovered.get('summary', '')}\n{recovered.get('content', '')}".strip()
            refreshed_status = (
                "needs_resubmit"
                if "ocr шаардлагатай" in str(recovered.get("summary", "")).lower()
                or "embedded text was not found" in str(recovered.get("content", "")).lower()
                or not looks_like_receipt_text(refreshed_combined_text)
                or has_suspicious_receipt_fields(refreshed_patient_fields, title)
                else "processed"
            )
            conn.execute(
                """
                UPDATE document_submissions
                SET status = ?, summary = ?, content = ?, tags_json = ?, patient_fields_json = ?
                WHERE id = ?
                """,
                (
                    refreshed_status,
                    str(recovered.get("summary", "")),
                    str(recovered.get("content", "")),
                    json.dumps(recovered.get("tags", []), ensure_ascii=False),
                    json.dumps(refreshed_patient_fields, ensure_ascii=False),
                    str(row["id"]),
                ),
            )


def list_document_submissions() -> list[dict[str, Any]]:
    with db_connect() as conn:
        rows = conn.execute(
            """
            SELECT id, user_id, user_email, title, storage_path, status, summary,
                   content, tags_json, patient_fields_json, created_at
            FROM document_submissions
            ORDER BY datetime(created_at) DESC, rowid DESC
            """
        ).fetchall()
    return [row_to_submission(row) for row in rows]


def get_document_submission_by_id(submission_id: str) -> dict[str, Any] | None:
    with db_connect() as conn:
        row = conn.execute(
            """
            SELECT id, user_id, user_email, title, storage_path, status, summary,
                   content, tags_json, patient_fields_json, created_at
            FROM document_submissions
            WHERE id = ?
            """,
            (submission_id,),
        ).fetchone()
    return row_to_submission(row) if row else None


def delete_document_submission_record(submission_id: str) -> dict[str, Any] | None:
    with db_connect() as conn:
        row = conn.execute(
            """
            SELECT id, user_id, user_email, title, storage_path, status, summary,
                   content, tags_json, patient_fields_json, created_at
            FROM document_submissions
            WHERE id = ?
            """,
            (submission_id,),
        ).fetchone()
        if not row:
            return None
        conn.execute("DELETE FROM document_submissions WHERE id = ?", (submission_id,))
    return row_to_submission(row)


def search_documents(search_terms: list[str], limit: int = 80) -> list[dict[str, Any]]:
    normalized_terms = []
    seen_terms: set[str] = set()
    for raw_term in search_terms:
        term = str(raw_term or "").strip().lower()
        if len(term) < 2 or term in seen_terms:
            continue
        normalized_terms.append(term)
        seen_terms.add(term)

    if not normalized_terms:
        return []

    fts_tokens = [term.replace('"', "").replace("'", "").strip() for term in normalized_terms[:12]]
    fts_tokens = [term for term in fts_tokens if term]
    fts_query = " OR ".join(f"{term}*" for term in fts_tokens)

    patient_score_parts: list[str] = []
    patient_where_parts: list[str] = []
    patient_params: list[Any] = []
    metadata_score_parts: list[str] = []
    metadata_where_parts: list[str] = []
    metadata_params: list[Any] = []
    for term in normalized_terms[:12]:
        wildcard = f"%{term}%"
        metadata_score_parts.extend(
            [
                "CASE WHEN lower(title) LIKE ? THEN 24 ELSE 0 END",
                "CASE WHEN lower(summary) LIKE ? THEN 6 ELSE 0 END",
                "CASE WHEN lower(source) LIKE ? THEN 3 ELSE 0 END",
                "CASE WHEN lower(folder) LIKE ? THEN 2 ELSE 0 END",
            ]
        )
        metadata_params.extend([wildcard, wildcard, wildcard, wildcard])
        metadata_where_parts.append(
            "("
            "lower(title) LIKE ? OR "
            "lower(summary) LIKE ? OR "
            "lower(source) LIKE ? OR "
            "lower(folder) LIKE ?"
            ")"
        )
        metadata_params.extend([wildcard, wildcard, wildcard, wildcard])

        patient_score_parts.extend(
            [
                "CASE WHEN lower(patient_name) LIKE ? THEN 14 ELSE 0 END",
                "CASE WHEN lower(parent_name) LIKE ? THEN 8 ELSE 0 END",
                "CASE WHEN lower(register_number) LIKE ? THEN 18 ELSE 0 END",
                "CASE WHEN lower(diagnosis) LIKE ? THEN 5 ELSE 0 END",
                "CASE WHEN lower(recommendation) LIKE ? THEN 4 ELSE 0 END",
            ]
        )
        patient_params.extend([wildcard, wildcard, wildcard, wildcard, wildcard])
        patient_where_parts.append(
            "("
            "lower(patient_name) LIKE ? OR "
            "lower(parent_name) LIKE ? OR "
            "lower(register_number) LIKE ? OR "
            "lower(diagnosis) LIKE ? OR "
            "lower(recommendation) LIKE ?"
            ")"
        )
        patient_params.extend([wildcard, wildcard, wildcard, wildcard, wildcard])

    ordered_ids: list[str] = []
    seen_ids: set[str] = set()
    with db_connect() as conn:
        if fts_query:
            fts_rows = conn.execute(
                """
                SELECT
                  document_id,
                  chunk_id,
                  bm25(document_chunks_fts, 8.0, 5.0, 3.0, 1.5, 1.0, 4.0, 1.0) AS rank
                FROM document_chunks_fts
                WHERE document_chunks_fts MATCH ?
                ORDER BY rank ASC
                LIMIT ?
                """,
                (fts_query, max(limit * 8, 40)),
            ).fetchall()
            for row in fts_rows:
                document_id = str(row["document_id"])
                if document_id not in seen_ids:
                    ordered_ids.append(document_id)
                    seen_ids.add(document_id)

        metadata_score_sql = " + ".join(metadata_score_parts) or "0"
        metadata_where_sql = " OR ".join(metadata_where_parts) or "1=0"
        metadata_rows = conn.execute(
            f"""
            SELECT id, ({metadata_score_sql}) AS metadata_score
            FROM documents
            WHERE {metadata_where_sql}
            ORDER BY metadata_score DESC, created_at DESC
            LIMIT ?
            """,
            [*metadata_params, limit],
        ).fetchall()
        for row in metadata_rows:
            document_id = str(row["id"])
            if document_id not in seen_ids:
                ordered_ids.insert(0, document_id)
                seen_ids.add(document_id)

        patient_score_sql = " + ".join(patient_score_parts) or "0"
        patient_where_sql = " OR ".join(patient_where_parts) or "1=0"
        patient_rows = conn.execute(
            f"""
            SELECT document_id, ({patient_score_sql}) AS patient_score
            FROM document_patient_index
            WHERE {patient_where_sql}
            ORDER BY patient_score DESC, rowid DESC
            LIMIT ?
            """,
            [*patient_params, limit],
        ).fetchall()
        for row in patient_rows:
            document_id = str(row["document_id"])
            if document_id not in seen_ids:
                ordered_ids.insert(0, document_id)
                seen_ids.add(document_id)

        if not ordered_ids:
            return []

        placeholders = ",".join("?" for _ in ordered_ids)
        rows = conn.execute(
            f"""
            SELECT id, title, folder, storage_path, source, summary, content, tags_json, created_at
            FROM documents
            WHERE id IN ({placeholders})
            """,
            ordered_ids,
        ).fetchall()

    mapped_rows = {row["id"]: row_to_document(row) for row in rows}
    return [mapped_rows[document_id] for document_id in ordered_ids if document_id in mapped_rows][:limit]


def list_document_folders() -> list[str]:
    with db_connect() as conn:
        rows = conn.execute(
            """
            SELECT name
            FROM folders
            ORDER BY name COLLATE NOCASE ASC
            """
        ).fetchall()

    folders = [row["name"] for row in rows if row["name"]]
    merged = list(dict.fromkeys([*DEFAULT_DOCUMENT_FOLDERS, *folders]))
    return merged


def create_folder(name: str) -> list[str]:
    with db_connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO folders (id, name, created_at) VALUES (?, ?, ?)",
            (str(uuid4()), name, utc_now()),
        )
    return list_document_folders()


def folder_exists(name: str) -> bool:
    with db_connect() as conn:
        row = conn.execute(
            "SELECT 1 AS found FROM folders WHERE name = ?",
            (name,),
        ).fetchone()
    return bool(row)


def rename_folder(old_name: str, new_name: str) -> tuple[bool, str, list[dict[str, Any]]]:
    if old_name == new_name:
        return True, "Өөрчлөлт алга.", list_documents()
    if folder_exists(new_name):
        return False, "Ийм нэртэй folder аль хэдийн байна.", []
    with db_connect() as conn:
        affected_rows = conn.execute(
            """
            SELECT id, title, folder, storage_path, source, summary, content, tags_json, created_at
            FROM documents
            WHERE folder = ?
            """,
            (old_name,),
        ).fetchall()
        conn.execute("UPDATE folders SET name = ? WHERE name = ?", (new_name, old_name))
        conn.execute("UPDATE documents SET folder = ? WHERE folder = ?", (new_name, old_name))
        for row in affected_rows:
            document = row_to_document(row)
            document["folder"] = new_name
            refresh_document_indexes(conn, document)
    invalidate_document_caches()
    return True, "Folder нэрийг шинэчиллээ.", list_documents()


def delete_folder(name: str) -> tuple[bool, str]:
    if name in DEFAULT_DOCUMENT_FOLDERS:
        return False, "Default folder-уудыг устгахгүй."
    with db_connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM documents WHERE folder = ?",
            (name,),
        ).fetchone()
        if int(row["count"]) > 0:
            return False, "Эхлээд энэ folder доторх файлуудыг зөөх эсвэл устгана уу."
        conn.execute("DELETE FROM folders WHERE name = ?", (name,))
    invalidate_document_caches()
    return True, "Folder устгалаа."


def get_document_by_id(document_id: str) -> dict[str, Any] | None:
    with db_connect() as conn:
        row = conn.execute(
            """
            SELECT id, title, folder, storage_path, source, summary, content, tags_json, created_at
            FROM documents
            WHERE id = ?
            """,
            (document_id,),
        ).fetchone()
    return row_to_document(row) if row else None


def delete_document_record(document_id: str) -> dict[str, Any] | None:
    document = get_document_by_id(document_id)
    if not document:
        return None
    with db_connect() as conn:
        clear_document_indexes(conn, document_id)
        conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    invalidate_document_caches()
    return document


def save_copied_document(document: dict[str, Any]) -> dict[str, Any]:
    created = {
        **document,
        "id": document.get("id") or str(uuid4()),
    }
    insert_documents([created])
    return created


def update_document_storage_path(document_id: str, storage_path: str, folder: str) -> None:
    with db_connect() as conn:
        conn.execute(
            "UPDATE documents SET storage_path = ?, folder = ? WHERE id = ?",
            (storage_path, folder, document_id),
        )
    invalidate_document_caches()


def list_history_summaries_by_user(user_id: str) -> list[dict[str, Any]]:
    with db_connect() as conn:
        history_rows = conn.execute(
            """
            SELECT id, title, created_at, updated_at
            FROM histories
            WHERE user_id = ?
            ORDER BY datetime(updated_at) DESC, rowid DESC
            """,
            (user_id,),
        ).fetchall()
        counts = {
            row["history_id"]: row["count"]
            for row in conn.execute(
                "SELECT history_id, COUNT(*) AS count FROM messages GROUP BY history_id"
            ).fetchall()
        }

    return [
        {
            "id": row["id"],
            "title": row["title"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "messageCount": int(counts.get(row["id"], 0)),
        }
        for row in history_rows
    ]


def get_history_by_id(history_id: str | None, user_id: str) -> dict[str, Any] | None:
    if not history_id:
        return None

    with db_connect() as conn:
        history_row = conn.execute(
            """
            SELECT id, user_id, title, created_at, updated_at
            FROM histories
            WHERE id = ? AND user_id = ?
            """,
            (history_id, user_id),
        ).fetchone()

        if not history_row:
            return None

        message_rows = conn.execute(
            """
            SELECT id, role, text, citations_json, timestamp, sort_order
            FROM messages
            WHERE history_id = ?
            ORDER BY sort_order ASC, rowid ASC
            """,
            (history_id,),
        ).fetchall()

    messages = [row_to_message(row) for row in message_rows]
    return {
        "id": history_row["id"],
        "userId": history_row["user_id"],
        "title": history_row["title"],
        "createdAt": history_row["created_at"],
        "updatedAt": history_row["updated_at"],
        "messageCount": len(messages),
        "messages": messages,
    }


def create_history_record(user_id: str, title: str) -> dict[str, Any]:
    history = {
        "id": str(uuid4()),
        "userId": user_id,
        "title": title,
        "createdAt": utc_now(),
        "updatedAt": utc_now(),
        "messages": [],
    }
    with db_connect() as conn:
        conn.execute(
            """
            INSERT INTO histories (id, user_id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                history["id"],
                history["userId"],
                history["title"],
                history["createdAt"],
                history["updatedAt"],
            ),
        )
    return history


def update_history_title(history_id: str, title: str) -> None:
    with db_connect() as conn:
        conn.execute(
            "UPDATE histories SET title = ?, updated_at = ? WHERE id = ?",
            (title, utc_now(), history_id),
        )


def rename_history(history_id: str, user_id: str, title: str) -> bool:
    with db_connect() as conn:
        cursor = conn.execute(
            "UPDATE histories SET title = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (title, utc_now(), history_id, user_id),
        )
        return cursor.rowcount > 0


def delete_history(history_id: str, user_id: str) -> bool:
    with db_connect() as conn:
        cursor = conn.execute(
            "DELETE FROM histories WHERE id = ? AND user_id = ?",
            (history_id, user_id),
        )
        return cursor.rowcount > 0


def append_message(history_id: str, message: dict[str, Any], sort_order: int) -> None:
    with db_connect() as conn:
        conn.execute(
            """
            INSERT INTO messages (id, history_id, role, text, citations_json, timestamp, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message["id"],
                history_id,
                message["role"],
                message["text"],
                json.dumps(message.get("citations", []), ensure_ascii=False),
                message["timestamp"],
                sort_order,
            ),
        )


def touch_history(history_id: str) -> None:
    with db_connect() as conn:
        conn.execute("UPDATE histories SET updated_at = ? WHERE id = ?", (utc_now(), history_id))


def row_to_document(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "folder": row["folder"] or "Ерөнхий",
        "storagePath": row["storage_path"] or "",
        "source": row["source"],
        "summary": row["summary"],
        "content": row["content"],
        "tags": parse_json(row["tags_json"], []),
        "createdAt": row["created_at"],
    }


def row_to_message(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "role": row["role"],
        "text": row["text"],
        "citations": parse_json(row["citations_json"], []),
        "timestamp": row["timestamp"],
    }


def sanitize_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["id"],
        "email": user["email"],
        "role": user["role"],
        "name": user["name"],
    }


def sanitize_document(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": document["id"],
        "title": document["title"],
        "folder": document.get("folder", "Ерөнхий"),
        "source": document["source"],
        "summary": document["summary"],
        "tags": document.get("tags", []),
        "createdAt": document["createdAt"],
    }


def sanitize_submission(submission: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": submission["id"],
        "userId": submission["userId"],
        "userEmail": submission["userEmail"],
        "title": submission["title"],
        "storagePath": submission.get("storagePath", ""),
        "status": submission["status"],
        "summary": submission["summary"],
        "content": submission.get("content", ""),
        "patientFields": submission.get("patientFields", {}),
        "createdAt": submission["createdAt"],
    }


def summarize_history(history: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": history["id"],
        "title": history["title"],
        "createdAt": history["createdAt"],
        "updatedAt": history["updatedAt"],
        "messageCount": len(history.get("messages", [])),
    }


def create_message(role: str, text: str, citations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "role": role,
        "text": text,
        "citations": citations or [],
        "timestamp": utc_now(),
    }


def row_to_submission(row: sqlite3.Row) -> dict[str, Any]:
    summary = str(row["summary"] or "")
    content = str(row["content"] or "")
    patient_fields = parse_json(row["patient_fields_json"], {})
    status = str(row["status"] or "")

    if looks_like_base64_text(summary) or looks_like_base64_text(content):
        summary = "Баримтын зургийг уншиж чадсангүй. Дахин илгээж шалгана уу."
        content = ""
        patient_fields = {
            **patient_fields,
            "itemInfo": patient_fields.get("itemInfo") or str(row["title"] or ""),
        }

    if (
        not patient_fields.get("totalAmount")
        or not patient_fields.get("itemInfo")
        or not patient_fields.get("organizationName")
        or not patient_fields.get("receiptDate")
        or has_suspicious_receipt_fields(patient_fields, str(row["title"] or ""))
    ):
        derived_fields = extract_patient_fields(str(row["title"] or ""), f"{summary}\n{content}")
        patient_fields = {
            **patient_fields,
            **derived_fields,
        }
        if has_suspicious_receipt_fields(patient_fields, str(row["title"] or "")) or not looks_like_receipt_text(f"{summary}\n{content}"):
            status = "needs_resubmit"
            patient_fields = {
                **patient_fields,
                "organizationName": "Танигдаагүй байгууллага",
                "itemInfo": "Баримтын текстийг найдвартай таньж чадсангүй.",
                "totalAmount": "",
            }

    if status == "needs_resubmit":
        patient_fields = {
            **patient_fields,
            "organizationName": "Танигдаагүй байгууллага",
            "itemInfo": "Баримтын текстийг найдвартай таньж чадсангүй.",
            "totalAmount": "",
        }

    return {
        "id": row["id"],
        "userId": row["user_id"],
        "userEmail": row["user_email"],
        "title": row["title"],
        "storagePath": row["storage_path"] or "",
        "status": status,
        "summary": summary,
        "content": content,
        "tags": parse_json(row["tags_json"], []),
        "patientFields": patient_fields,
        "createdAt": row["created_at"],
    }
