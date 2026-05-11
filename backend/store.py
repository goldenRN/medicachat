from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
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
from .text_utils import build_history_title, parse_json, utc_now


@contextmanager
def db_connect():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
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

            CREATE INDEX IF NOT EXISTS idx_histories_user_updated
              ON histories(user_id, updated_at DESC);

            CREATE INDEX IF NOT EXISTS idx_messages_history_sort
              ON messages(history_id, sort_order ASC);
            """
        )
        ensure_document_folder_column(conn)
        ensure_document_storage_path_column(conn)
        ensure_folders_seeded(conn)


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


def insert_documents(documents: list[dict[str, Any]]) -> None:
    with db_connect() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO documents (id, title, folder, storage_path, source, summary, content, tags_json, created_at)
            VALUES (:id, :title, :folder, :storage_path, :source, :summary, :content, :tags_json, :created_at)
            """,
            [
                {
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
                for document in documents
            ],
        )


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
    with db_connect() as conn:
        row = conn.execute(
            """
            SELECT id, email, password, role, name
            FROM users
            WHERE lower(email) = ? AND password = ?
            """,
            (str(email or "").strip().lower(), str(password or "")),
        ).fetchone()
    return dict(row) if row else None


def list_documents() -> list[dict[str, Any]]:
    with db_connect() as conn:
        rows = conn.execute(
            """
            SELECT id, title, folder, storage_path, source, summary, content, tags_json, created_at
            FROM documents
            ORDER BY datetime(created_at) DESC, rowid DESC
            """
        ).fetchall()
    return [row_to_document(row) for row in rows]


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
        conn.execute("UPDATE folders SET name = ? WHERE name = ?", (new_name, old_name))
        conn.execute("UPDATE documents SET folder = ? WHERE folder = ?", (new_name, old_name))
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
        conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
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
