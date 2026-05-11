from __future__ import annotations

import base64
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from .config import DATA_DIR, UPLOAD_DIR
from .text_utils import (
    derive_tags,
    extract_name_from_title,
    sanitize_filename,
    sanitize_folder_name,
    summarize_content,
    utc_now,
)


def folder_storage_name(folder: str) -> str:
    return sanitize_filename(sanitize_folder_name(folder)).strip("-") or "general"


def build_storage_path(folder: str, filename: str) -> str:
    return str(Path(folder_storage_name(folder)) / filename)


def parse_uploaded_file(file_payload: dict[str, str], uploader_email: str) -> dict[str, object] | None:
    safe_name = sanitize_filename(file_payload.get("name", "uploaded.txt"))
    folder_name = sanitize_folder_name(file_payload.get("folder", "Ерөнхий"))
    folder_path = UPLOAD_DIR / folder_storage_name(folder_name)
    folder_path.mkdir(parents=True, exist_ok=True)
    extension = Path(safe_name).suffix.lower()
    saved_name = f"{int(datetime.now(timezone.utc).timestamp() * 1000)}-{safe_name}"
    saved_path = folder_path / saved_name
    relative_storage_path = build_storage_path(folder_name, saved_name)

    if extension == ".pdf":
        raw_base64 = str(file_payload.get("content", "")).strip()
        if not raw_base64:
            return None
        saved_path.write_bytes(base64.b64decode(raw_base64))
        extracted_text = extract_pdf_text(saved_path).strip()
        used_ocr = False
        if not extracted_text:
            extracted_text = extract_pdf_text_with_ocr(saved_path).strip()
            used_ocr = bool(extracted_text)
        if not extracted_text:
            return {
                "document": build_scan_pdf_record(safe_name, uploader_email, folder_name),
                "warning": f'"{safe_name}" нь текстгүй scan PDF байна. OCR-оор ч текст гарч ирсэнгүй, зөвхөн filename-аар бүртгэлээ.',
            }
        warning = f'"{safe_name}" scan PDF байсан тул OCR ашиглан уншлаа.' if used_ocr else None
        return {
            "document": build_document_record(
                safe_name,
                uploader_email,
                extracted_text,
                folder_name,
                relative_storage_path,
            ),
            "warning": warning,
        }

    content = str(file_payload.get("content", "")).strip()
    if not content:
        return None

    saved_path.write_text(content, encoding="utf-8")
    return {
        "document": build_document_record(
            safe_name,
            uploader_email,
            content,
            folder_name,
            relative_storage_path,
        ),
        "warning": None,
    }


def extract_pdf_text(pdf_path: Path) -> str:
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout
    except Exception:
        return ""


def extract_pdf_text_with_ocr(pdf_path: Path) -> str:
    languages = get_tesseract_languages()
    ocr_language = "eng+mon" if "mon" in languages else "eng"

    ocr_root = DATA_DIR / "ocr-cache"
    ocr_root.mkdir(parents=True, exist_ok=True)

    try:
        with TemporaryDirectory(prefix="ocr-", dir=str(ocr_root)) as temp_dir:
            prefix = Path(temp_dir) / "page"
            subprocess.run(
                ["pdftocairo", "-png", "-r", "200", str(pdf_path), str(prefix)],
                check=True,
                capture_output=True,
                text=True,
            )
            image_paths = sorted(Path(temp_dir).glob("page*.png"))
            texts = [extract_image_text_with_tesseract(image_path, ocr_language) for image_path in image_paths]
            return "\n".join(text for text in texts if text.strip())
    except Exception:
        return ""


def extract_image_text_with_tesseract(image_path: Path, language: str) -> str:
    try:
        result = subprocess.run(
            ["tesseract", str(image_path), "stdout", "-l", language, "--psm", "6"],
            check=True,
            capture_output=True,
        )
        return result.stdout.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def get_tesseract_languages() -> set[str]:
    try:
        result = subprocess.run(
            ["tesseract", "--list-langs"],
            check=True,
            capture_output=True,
            text=True,
        )
        lines = [line.strip() for line in result.stdout.splitlines()]
        return {line for line in lines[1:] if line}
    except Exception:
        return set()


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
    target = UPLOAD_DIR / storage_path
    if target.exists():
        target.unlink()
    parent = target.parent
    if parent.exists() and parent != UPLOAD_DIR:
        try:
            next(parent.iterdir())
        except StopIteration:
            parent.rmdir()


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
