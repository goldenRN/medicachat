from __future__ import annotations

import base64
import mimetypes
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .config import UPLOAD_DIR
from .text_utils import (
    derive_tags,
    extract_name_from_title,
    sanitize_filename,
    sanitize_folder_name,
    summarize_content,
    utc_now,
)


IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".gif",
    ".tif",
    ".tiff",
    ".heic",
    ".heif",
}

OFFICE_BINARY_EXTENSIONS = {
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
}


def folder_storage_name(folder: str) -> str:
    return sanitize_filename(sanitize_folder_name(folder)).strip("-") or "general"


def build_storage_path(folder: str, filename: str) -> str:
    return str(Path(folder_storage_name(folder)) / filename)


def infer_folder_from_storage_path(storage_path: Path) -> str:
    if storage_path.parent == UPLOAD_DIR:
        return "Ерөнхий"
    return storage_path.parent.name or "Ерөнхий"


def build_storage_reference(storage_path: Path) -> str:
    return str(storage_path.relative_to(UPLOAD_DIR))


def resolve_document_storage_path(document: dict[str, object]) -> str:
    storage_path = str(document.get("storagePath", "") or "").strip()
    if storage_path:
        safe_path = (UPLOAD_DIR / storage_path).resolve()
        upload_root = UPLOAD_DIR.resolve()
        if str(safe_path).startswith(str(upload_root)) and safe_path.exists() and safe_path.is_file():
            return storage_path

    title = sanitize_filename(str(document.get("title", "") or "").strip())
    if not title:
        return ""

    folder_name = str(document.get("folder", "") or "").strip()
    candidate_dirs: list[Path] = []
    if folder_name:
        candidate_dirs.append(UPLOAD_DIR / folder_storage_name(folder_name))
    candidate_dirs.append(UPLOAD_DIR)

    matches: list[Path] = []
    seen_paths: set[str] = set()
    expected_suffix = f"-{title}"

    for directory in candidate_dirs:
        if not directory.exists() or not directory.is_dir():
            continue
        for file_path in directory.rglob("*"):
            if not file_path.is_file():
                continue
            normalized_name = sanitize_filename(file_path.name)
            if normalized_name != title and not normalized_name.endswith(expected_suffix):
                continue
            resolved_key = str(file_path.resolve())
            if resolved_key in seen_paths:
                continue
            seen_paths.add(resolved_key)
            matches.append(file_path)

    if not matches:
        return ""

    matches.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return build_storage_reference(matches[0].resolve())


def decode_upload_bytes(raw_content: object) -> bytes:
    raw_base64 = str(raw_content or "").strip()
    if not raw_base64:
        return b""

    if raw_base64.startswith("data:") and "," in raw_base64:
        raw_base64 = raw_base64.split(",", 1)[1]

    normalized = re.sub(r"\s+", "", raw_base64)
    if not normalized:
        return b""

    padding = len(normalized) % 4
    if padding:
        normalized += "=" * (4 - padding)

    return base64.b64decode(normalized, validate=False)


def build_document_record(
    title: str,
    uploader_email: str,
    content: str,
    folder: str,
    storage_path: str = "",
) -> dict[str, object]:
    return {
        "id": str(uuid4()),
        "title": title,
        "folder": folder,
        "storagePath": storage_path,
        "source": f"Uploaded by {uploader_email}",
        "summary": summarize_content(content),
        "content": content[:12000],
        "tags": derive_tags(content),
        "createdAt": utc_now(),
    }


def build_scan_pdf_record(title: str, uploader_email: str, folder: str) -> dict[str, object]:
    base_name = extract_name_from_title(title)
    content = (
        f"{title}\n"
        f"Possible subject: {base_name}\n"
        "This PDF appears to be image-only or scanned. Embedded text was not found. OCR is required for full text search."
    )
    return {
        "id": str(uuid4()),
        "title": title,
        "folder": folder,
        "storagePath": "",
        "source": f"Uploaded by {uploader_email}",
        "summary": "Scan PDF detected. Embedded text олдсонгүй, OCR шаардлагатай.",
        "content": content,
        "tags": derive_tags(f"{title} {base_name} scan pdf ocr"),
        "createdAt": utc_now(),
    }


def move_folder_storage(old_folder: str, new_folder: str) -> dict[str, str]:
    old_dir = UPLOAD_DIR / folder_storage_name(old_folder)
    new_dir = UPLOAD_DIR / folder_storage_name(new_folder)
    path_map: dict[str, str] = {}

    if not old_dir.exists():
        return path_map

    new_dir.parent.mkdir(parents=True, exist_ok=True)
    new_dir.mkdir(parents=True, exist_ok=True)
    for file_path in old_dir.iterdir():
        if not file_path.is_file():
            continue
        destination = new_dir / file_path.name
        shutil.move(str(file_path), str(destination))
        path_map[str(Path(folder_storage_name(old_folder)) / file_path.name)] = str(
            Path(folder_storage_name(new_folder)) / file_path.name
        )

    try:
        old_dir.rmdir()
    except OSError:
        pass

    return path_map


def delete_folder_storage(folder: str) -> None:
    folder_path = UPLOAD_DIR / folder_storage_name(folder)
    if not folder_path.exists() or folder_path == UPLOAD_DIR:
        return
    try:
        next(folder_path.iterdir())
    except StopIteration:
        folder_path.rmdir()
    except OSError:
        pass


def delete_document_storage(document: dict[str, object]) -> None:
    storage_path = str(document.get("storagePath", "") or "").strip()
    if not storage_path:
        return
    delete_storage_asset(storage_path)


def delete_storage_asset(storage_path: str) -> None:
    target = UPLOAD_DIR / str(storage_path or "").strip()
    if not str(storage_path or "").strip():
        return
    if target.exists():
        target.unlink()
    parent = target.parent
    if parent.exists() and parent != UPLOAD_DIR:
        try:
            next(parent.iterdir())
        except StopIteration:
            parent.rmdir()


def save_employee_photo(
    employee_id: str,
    display_name: str,
    raw_content: object,
    mime_type: str = "",
    previous_path: str = "",
) -> str:
    photo_bytes = decode_upload_bytes(raw_content)
    if not photo_bytes:
        return str(previous_path or "").strip()

    extension = mimetypes.guess_extension(str(mime_type or "").strip().lower()) or ".png"
    if extension == ".jpe":
        extension = ".jpg"
    if extension not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
        extension = ".png"

    photo_dir = UPLOAD_DIR / "employee-photos"
    photo_dir.mkdir(parents=True, exist_ok=True)
    safe_display_name = sanitize_filename(display_name or employee_id).strip("-") or "employee"
    photo_name = f"{sanitize_filename(employee_id)}-{safe_display_name}{extension}"
    photo_path = photo_dir / photo_name
    photo_path.write_bytes(photo_bytes)
    next_storage_path = str(Path("employee-photos") / photo_name)

    previous_storage_path = str(previous_path or "").strip()
    if previous_storage_path and previous_storage_path != next_storage_path:
        delete_storage_asset(previous_storage_path)

    return next_storage_path


def copy_document_storage(document: dict[str, object], target_folder: str) -> str:
    storage_path = str(document.get("storagePath", "") or "").strip()
    if not storage_path:
        return ""

    source = UPLOAD_DIR / storage_path
    if not source.exists():
        return ""

    destination_dir = UPLOAD_DIR / folder_storage_name(target_folder)
    destination_dir.mkdir(parents=True, exist_ok=True)
    copied_name = f"{int(datetime.now(timezone.utc).timestamp() * 1000)}-{sanitize_filename(document['title'])}"
    destination = destination_dir / copied_name
    shutil.copy2(source, destination)
    return build_storage_path(target_folder, copied_name)
