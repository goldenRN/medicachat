from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import Path

from .config import UPLOAD_DIR
from .documents_extract import (
    extract_docx_text,
    extract_legacy_office_text,
    extract_pdf_text,
    extract_xlsx_text,
)
from .documents_image import (
    extract_best_submission_image_text,
    extract_image_text_with_openai,
    extract_image_text_with_tesseract,
    extract_pdf_text_with_ocr,
    get_tesseract_languages,
    is_unreadable_ocr_text,
)
from .documents_storage import (
    IMAGE_EXTENSIONS,
    build_document_record,
    build_scan_pdf_record,
    build_storage_path,
    build_storage_reference,
    decode_upload_bytes,
    folder_storage_name,
    infer_folder_from_storage_path,
)
from .text_utils import format_receipt_ocr_text, normalize_whitespace, sanitize_filename, sanitize_folder_name, summarize_content


def parse_uploaded_file(file_payload: dict[str, str], uploader_email: str) -> dict[str, object] | None:
    safe_name = sanitize_filename(file_payload.get("name", "uploaded.txt"))
    folder_name = sanitize_folder_name(file_payload.get("folder", "Ерөнхий"))
    folder_path = UPLOAD_DIR / folder_storage_name(folder_name)
    folder_path.mkdir(parents=True, exist_ok=True)
    extension = Path(safe_name).suffix.lower()
    mime_type = str(file_payload.get("mimeType", "") or "").strip().lower()
    is_image_upload = mime_type.startswith("image/") or extension in IMAGE_EXTENSIONS
    saved_name = f"{int(datetime.now(timezone.utc).timestamp() * 1000)}-{safe_name}"
    saved_path = folder_path / saved_name
    relative_storage_path = build_storage_path(folder_name, saved_name)

    if extension == ".pdf":
        try:
            file_bytes = decode_upload_bytes(file_payload.get("content", ""))
        except Exception:
            return {
                "document": build_scan_pdf_record(safe_name, uploader_email, folder_name),
                "warning": f'"{safe_name}" PDF файлыг уншихад алдаа гарлаа. Файлаа дахин upload хийнэ үү.',
            }
        if not file_bytes:
            return None
        saved_path.write_bytes(file_bytes)
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

    if is_image_upload:
        try:
            file_bytes = decode_upload_bytes(file_payload.get("content", ""))
        except Exception:
            return {
                "document": build_scan_pdf_record(safe_name, uploader_email, folder_name),
                "warning": f'"{safe_name}" зургаас текст уншиж чадсангүй.',
            }
        if not file_bytes:
            return None
        try:
            saved_path.write_bytes(file_bytes)
        except Exception:
            return {
                "document": build_scan_pdf_record(safe_name, uploader_email, folder_name),
                "warning": f'"{safe_name}" зургаас текст уншиж чадсангүй.',
            }
        languages = get_tesseract_languages()
        ocr_language = "eng+mon" if "mon" in languages else "eng"
        extracted_text = extract_image_text_with_tesseract(saved_path, ocr_language).strip()
        used_ai_ocr = False
        if not extracted_text or is_unreadable_ocr_text(extracted_text):
            extracted_text = extract_image_text_with_openai(saved_path).strip()
            used_ai_ocr = bool(extracted_text)
        if not extracted_text or is_unreadable_ocr_text(extracted_text):
            return {
                "document": build_scan_pdf_record(safe_name, uploader_email, folder_name),
                "warning": f'"{safe_name}" зургаас текст тодорхой уншигдсангүй.',
            }
        return {
            "document": build_document_record(
                safe_name,
                uploader_email,
                extracted_text,
                folder_name,
                relative_storage_path,
            ),
            "warning": (
                f'"{safe_name}" зургаас OpenAI vision ашиглан текст уншлаа.'
                if used_ai_ocr
                else f'"{safe_name}" зургаас OCR ашиглан текст уншлаа.'
            ),
        }

    if extension == ".docx":
        try:
            file_bytes = decode_upload_bytes(file_payload.get("content", ""))
        except Exception:
            return {
                "document": build_scan_pdf_record(safe_name, uploader_email, folder_name),
                "warning": f'"{safe_name}" Word файлаас текст уншиж чадсангүй.',
            }
        if not file_bytes:
            return None
        try:
            saved_path.write_bytes(file_bytes)
        except Exception:
            return {
                "document": build_scan_pdf_record(safe_name, uploader_email, folder_name),
                "warning": f'"{safe_name}" Word файлаас текст уншиж чадсангүй.',
            }
        extracted_text = extract_docx_text(saved_path).strip()
        if not extracted_text:
            return {
                "document": build_scan_pdf_record(safe_name, uploader_email, folder_name),
                "warning": f'"{safe_name}" Word файлаас танигдах текст олдсонгүй.',
            }
        return {
            "document": build_document_record(
                safe_name,
                uploader_email,
                extracted_text,
                folder_name,
                relative_storage_path,
            ),
            "warning": None,
        }

    if extension == ".doc":
        try:
            file_bytes = decode_upload_bytes(file_payload.get("content", ""))
        except Exception:
            return {
                "document": build_scan_pdf_record(safe_name, uploader_email, folder_name),
                "warning": f'"{safe_name}" Word файлаас текст уншиж чадсангүй.',
            }
        if not file_bytes:
            return None
        try:
            saved_path.write_bytes(file_bytes)
        except Exception:
            return {
                "document": build_scan_pdf_record(safe_name, uploader_email, folder_name),
                "warning": f'"{safe_name}" Word файлаас текст уншиж чадсангүй.',
            }
        extracted_text = extract_legacy_office_text(saved_path).strip()
        if not extracted_text:
            return {
                "document": build_scan_pdf_record(safe_name, uploader_email, folder_name),
                "warning": f'"{safe_name}" Word файлаас танигдах текст олдсонгүй.',
            }
        return {
            "document": build_document_record(
                safe_name,
                uploader_email,
                extracted_text,
                folder_name,
                relative_storage_path,
            ),
            "warning": f'"{safe_name}" legacy Word файлаас fallback text extraction ашиглалаа.',
        }

    if extension == ".xlsx":
        try:
            file_bytes = decode_upload_bytes(file_payload.get("content", ""))
        except Exception:
            return {
                "document": build_scan_pdf_record(safe_name, uploader_email, folder_name),
                "warning": f'"{safe_name}" Excel файлаас текст уншиж чадсангүй.',
            }
        if not file_bytes:
            return None
        try:
            saved_path.write_bytes(file_bytes)
        except Exception:
            return {
                "document": build_scan_pdf_record(safe_name, uploader_email, folder_name),
                "warning": f'"{safe_name}" Excel файлаас текст уншиж чадсангүй.',
            }
        extracted_text = extract_xlsx_text(saved_path).strip()
        if not extracted_text:
            return {
                "document": build_scan_pdf_record(safe_name, uploader_email, folder_name),
                "warning": f'"{safe_name}" Excel файлаас танигдах текст олдсонгүй.',
            }
        return {
            "document": build_document_record(
                safe_name,
                uploader_email,
                extracted_text,
                folder_name,
                relative_storage_path,
            ),
            "warning": None,
        }

    if extension == ".xls":
        try:
            file_bytes = decode_upload_bytes(file_payload.get("content", ""))
        except Exception:
            return {
                "document": build_scan_pdf_record(safe_name, uploader_email, folder_name),
                "warning": f'"{safe_name}" Excel файлаас текст уншиж чадсангүй.',
            }
        if not file_bytes:
            return None
        try:
            saved_path.write_bytes(file_bytes)
        except Exception:
            return {
                "document": build_scan_pdf_record(safe_name, uploader_email, folder_name),
                "warning": f'"{safe_name}" Excel файлаас текст уншиж чадсангүй.',
            }
        extracted_text = extract_legacy_office_text(saved_path).strip()
        if not extracted_text:
            return {
                "document": build_scan_pdf_record(safe_name, uploader_email, folder_name),
                "warning": f'"{safe_name}" Excel файлаас танигдах текст олдсонгүй.',
            }
        return {
            "document": build_document_record(
                safe_name,
                uploader_email,
                extracted_text,
                folder_name,
                relative_storage_path,
            ),
            "warning": f'"{safe_name}" legacy Excel файлаас fallback text extraction ашиглалаа.',
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


def parse_submission_image_file(
    file_payload: dict[str, str],
    uploader_email: str,
) -> dict[str, object] | None:
    safe_name = sanitize_filename(file_payload.get("name", "uploaded-image"))
    extension = Path(safe_name).suffix.lower()
    mime_type = str(file_payload.get("mimeType", "") or "").strip().lower()
    is_image_upload = mime_type.startswith("image/") or extension in IMAGE_EXTENSIONS
    if not is_image_upload:
        return {
            "document": build_scan_pdf_record(safe_name, uploader_email, "Илгээсэн баримт"),
            "warning": "Баримт илгээх хэсэгт зөвхөн зураг upload хийнэ үү.",
        }

    folder_name = "Илгээсэн баримт"
    folder_path = UPLOAD_DIR / folder_storage_name(folder_name)
    folder_path.mkdir(parents=True, exist_ok=True)
    saved_name = f"{int(datetime.now(timezone.utc).timestamp() * 1000)}-{safe_name}"
    saved_path = folder_path / saved_name
    relative_storage_path = build_storage_path(folder_name, saved_name)
    try:
        file_bytes = decode_upload_bytes(file_payload.get("content", ""))
    except Exception:
        return {
            "document": build_scan_pdf_record(safe_name, uploader_email, folder_name),
            "warning": "Баримтын зургийг дахин явуулна уу.",
        }
    if not file_bytes:
        return None

    try:
        saved_path.write_bytes(file_bytes)
    except Exception:
        return {
            "document": build_scan_pdf_record(safe_name, uploader_email, folder_name),
            "warning": "Баримтын зургийг дахин явуулна уу.",
        }

    extracted_text, source = extract_best_submission_image_text(saved_path, safe_name)

    if not extracted_text or is_unreadable_ocr_text(extracted_text):
        return {
            "document": build_scan_pdf_record(safe_name, uploader_email, folder_name),
            "warning": "Баримтын зургийг дахин явуулна уу.",
        }

    extracted_text = format_receipt_ocr_text(safe_name, extracted_text)

    if source == "google":
        warning = f'"{safe_name}" зургаас Google Vision OCR ашиглан текст уншлаа.'
    elif source == "openai":
        warning = f'"{safe_name}" зургаас OpenAI vision ашиглан текст уншлаа.'
    else:
        warning = f'"{safe_name}" зургаас OCR ашиглан текст уншлаа.'

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


def recover_uploaded_file(saved_path: Path) -> dict[str, object] | None:
    if not saved_path.exists() or not saved_path.is_file():
        return None

    folder_name = infer_folder_from_storage_path(saved_path)
    storage_reference = build_storage_reference(saved_path)
    title = saved_path.name.split("-", 1)[1] if "-" in saved_path.name else saved_path.name
    uploader_email = "Recovered upload"
    extension = saved_path.suffix.lower()

    if extension == ".pdf":
        extracted_text = extract_pdf_text(saved_path).strip()
        used_ocr = False
        if not extracted_text:
            extracted_text = extract_pdf_text_with_ocr(saved_path).strip()
            used_ocr = bool(extracted_text)
        if not extracted_text:
            return build_scan_pdf_record(title, uploader_email, folder_name)
        document = build_document_record(
            title,
            uploader_email,
            extracted_text,
            folder_name,
            storage_reference,
        )
        if used_ocr:
            document["summary"] = summarize_content(extracted_text) or 'Scan PDF байсан тул OCR ашиглан сэргээж индексэллээ.'
        return document

    if extension in IMAGE_EXTENSIONS:
        return recover_submission_file(saved_path, title, uploader_email, folder_name)

    if extension == ".docx":
        extracted_text = extract_docx_text(saved_path).strip()
        if not extracted_text:
            return None
        return build_document_record(title, uploader_email, extracted_text, folder_name, storage_reference)

    if extension == ".doc":
        extracted_text = extract_legacy_office_text(saved_path).strip()
        if not extracted_text:
            return None
        return build_document_record(title, uploader_email, extracted_text, folder_name, storage_reference)

    if extension == ".xlsx":
        extracted_text = extract_xlsx_text(saved_path).strip()
        if not extracted_text:
            return None
        return build_document_record(title, uploader_email, extracted_text, folder_name, storage_reference)

    if extension == ".xls":
        extracted_text = extract_legacy_office_text(saved_path).strip()
        if not extracted_text:
            return None
        return build_document_record(title, uploader_email, extracted_text, folder_name, storage_reference)

    try:
        content = saved_path.read_text(encoding="utf-8").strip()
    except Exception:
        return None
    if not content:
        return None
    return build_document_record(title, uploader_email, content, folder_name, storage_reference)


def looks_like_base64_text(value: str) -> bool:
    text = normalize_whitespace(value)
    if len(text) < 120:
        return False
    if not text.startswith("AAAA"):
        return False
    import re as _re
    return bool(_re.fullmatch(r"[A-Za-z0-9+/= _-]+", text))


def recover_submission_file(
    saved_path: Path,
    title: str,
    uploader_email: str,
    folder_name: str = "Илгээсэн баримт",
) -> dict[str, object] | None:
    extension = saved_path.suffix.lower()

    if extension == ".pdf":
        extracted_text = extract_pdf_text(saved_path).strip()
        if not extracted_text:
            extracted_text = extract_pdf_text_with_ocr(saved_path).strip()
        if not extracted_text:
            return build_scan_pdf_record(title, uploader_email, folder_name)
        return build_document_record(title, uploader_email, extracted_text, folder_name, build_storage_reference(saved_path))

    if extension in IMAGE_EXTENSIONS:
        try:
            maybe_text = saved_path.read_text(encoding="utf-8").strip()
            if looks_like_base64_text(maybe_text):
                saved_path.write_bytes(base64.b64decode(maybe_text, validate=False))
        except Exception:
            pass

        extracted_text, _source = extract_best_submission_image_text(saved_path, title)
        if not extracted_text or is_unreadable_ocr_text(extracted_text):
            return build_scan_pdf_record(title, uploader_email, folder_name)
        extracted_text = format_receipt_ocr_text(title, extracted_text)
        return build_document_record(title, uploader_email, extracted_text, folder_name, build_storage_reference(saved_path))

    try:
        content = saved_path.read_text(encoding="utf-8").strip()
    except Exception:
        return None
    if not content:
        return None
    return build_document_record(title, uploader_email, content, folder_name, build_storage_reference(saved_path))
