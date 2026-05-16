from __future__ import annotations

import base64
import mimetypes
import re
import shutil
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from .config import DATA_DIR, UPLOAD_DIR
from .text_utils import (
    derive_tags,
    extract_name_from_title,
    normalize_whitespace,
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

OCR_PSMS = ("6", "11", "4")
DOCX_XML_PARTS = (
    "word/document.xml",
    "word/header1.xml",
    "word/header2.xml",
    "word/header3.xml",
    "word/footer1.xml",
    "word/footer2.xml",
    "word/footer3.xml",
)


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

    if is_image_upload:
        raw_base64 = str(file_payload.get("content", "")).strip()
        if not raw_base64:
            return None
        try:
            saved_path.write_bytes(base64.b64decode(raw_base64, validate=False))
        except Exception:
            return {
                "document": build_scan_pdf_record(safe_name, uploader_email, folder_name),
                "warning": f'"{safe_name}" зургаас текст уншиж чадсангүй.',
            }
        languages = get_tesseract_languages()
        ocr_language = "eng+mon" if "mon" in languages else "eng"
        extracted_text = extract_image_text_with_tesseract(saved_path, ocr_language).strip()
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
            "warning": f'"{safe_name}" зургаас OCR ашиглан текст уншлаа.',
        }

    if extension == ".docx":
        raw_base64 = str(file_payload.get("content", "")).strip()
        if not raw_base64:
            return None
        try:
            saved_path.write_bytes(base64.b64decode(raw_base64, validate=False))
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

    try:
        content = saved_path.read_text(encoding="utf-8").strip()
    except Exception:
        return None
    if not content:
        return None
    return build_document_record(title, uploader_email, content, folder_name, storage_reference)


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


def extract_docx_text(docx_path: Path) -> str:
    sections: list[str] = []
    try:
        with zipfile.ZipFile(docx_path) as archive:
            names = set(archive.namelist())
            for part_name in DOCX_XML_PARTS:
                if part_name not in names:
                    continue
                xml_text = archive.read(part_name).decode("utf-8", errors="ignore")
                section_text = extract_text_from_wordprocessingml(xml_text)
                if section_text:
                    sections.append(section_text)
    except Exception:
        return ""
    return normalize_whitespace("\n\n".join(section for section in sections if section))


def extract_text_from_wordprocessingml(xml_text: str) -> str:
    prepared = xml_text
    prepared = re.sub(r"<w:tab(?:\s[^>]*)?/>", "\t", prepared)
    prepared = re.sub(r"<w:br(?:\s[^>]*)?/>", "\n", prepared)
    prepared = re.sub(r"</w:p>", "\n", prepared)
    prepared = re.sub(r"</w:tr>", "\n", prepared)
    prepared = re.sub(r"</w:tc>", " ", prepared)
    prepared = re.sub(r"<[^>]+>", "", prepared)

    # Basic XML entity cleanup for common Word content.
    prepared = (
        prepared.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
    )

    lines = [normalize_whitespace(line) for line in prepared.splitlines()]
    return "\n".join(line for line in lines if line)


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
    prepared_path, should_cleanup = prepare_image_for_ocr(image_path)
    best_text = ""
    best_score = -1.0
    temp_variants: list[Path] = []
    try:
        candidates = [prepared_path]
        enhanced_variant = prepare_image_for_ocr_quality(prepared_path)
        if enhanced_variant and enhanced_variant.exists():
            candidates.append(enhanced_variant)
            temp_variants.append(enhanced_variant)

        for candidate in candidates:
            for psm in OCR_PSMS:
                text = run_tesseract(candidate, language, psm)
                score = score_ocr_text(text)
                if score > best_score:
                    best_text = text
                    best_score = score
        return best_text
    finally:
        for temp_path in temp_variants:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except OSError:
                pass
        if should_cleanup and prepared_path.exists():
            try:
                prepared_path.unlink()
            except OSError:
                pass


def run_tesseract(image_path: Path, language: str, psm: str) -> str:
    try:
        result = subprocess.run(
            ["tesseract", str(image_path), "stdout", "-l", language, "--psm", psm],
            check=True,
            capture_output=True,
        )
        return result.stdout.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def score_ocr_text(text: str) -> float:
    compact = normalize_whitespace(text)
    if not compact:
        return 0.0

    length_score = min(len(compact), 400) / 40.0
    alpha_count = len(re.findall(r"[A-Za-zА-Яа-яӨөҮүЁё]", compact))
    digit_count = len(re.findall(r"\d", compact))
    word_count = len(re.findall(r"[A-Za-zА-Яа-яӨөҮүЁё0-9]{2,}", compact))
    weird_count = len(re.findall(r"[^A-Za-zА-Яа-яӨөҮүЁё0-9\s.,:/()%₮\-]", compact))

    return (
        length_score
        + alpha_count * 0.05
        + digit_count * 0.05
        + word_count * 0.35
        - weird_count * 0.25
    )


def is_unreadable_ocr_text(text: str) -> bool:
    compact = normalize_whitespace(text)
    if len(compact) < 12:
        return True

    word_like = re.findall(r"[A-Za-zА-Яа-яӨөҮүЁё0-9]{2,}", compact)
    if len(word_like) < 3:
        return True

    weird_count = len(re.findall(r"[^A-Za-zА-Яа-яӨөҮүЁё0-9\s.,:/()%₮\-]", compact))
    if weird_count > max(8, len(compact) * 0.08):
        return True

    return score_ocr_text(compact) < 6.0


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


def prepare_image_for_ocr(image_path: Path) -> tuple[Path, bool]:
    extension = image_path.suffix.lower()
    if extension not in {".heic", ".heif"}:
        return image_path, False

    converted_path = image_path.with_suffix(".png")

    try:
        if shutil.which("sips"):
            subprocess.run(
                ["sips", "-s", "format", "png", str(image_path), "--out", str(converted_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            if converted_path.exists():
                return converted_path, True
    except Exception:
        pass

    try:
        if shutil.which("magick"):
            subprocess.run(
                ["magick", str(image_path), str(converted_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            if converted_path.exists():
                return converted_path, True
    except Exception:
        pass

    try:
        if shutil.which("convert"):
            subprocess.run(
                ["convert", str(image_path), str(converted_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            if converted_path.exists():
                return converted_path, True
    except Exception:
        pass

    return image_path, False


def prepare_image_for_browser(image_path: Path) -> tuple[Path, str, bool]:
    extension = image_path.suffix.lower()
    if extension in {".heic", ".heif"}:
        converted_path, should_cleanup = prepare_image_for_ocr(image_path)
        content_type = mimetypes.guess_type(converted_path.name)[0] or "image/png"
        return converted_path, content_type, should_cleanup

    content_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    return image_path, content_type, False


def prepare_image_for_ocr_quality(image_path: Path) -> Path | None:
    if not image_path.exists():
        return None

    enhanced_path = image_path.with_name(f"{image_path.stem}-ocr.png")
    try:
        if shutil.which("magick"):
            subprocess.run(
                [
                    "magick",
                    str(image_path),
                    "-auto-orient",
                    "-resize",
                    "2200x2200>",
                    "-colorspace",
                    "Gray",
                    "-contrast-stretch",
                    "0.5%x0.5%",
                    "-sharpen",
                    "0x1",
                    str(enhanced_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            if enhanced_path.exists():
                return enhanced_path
    except Exception:
        pass

    try:
        if shutil.which("convert"):
            subprocess.run(
                [
                    "convert",
                    str(image_path),
                    "-auto-orient",
                    "-resize",
                    "2200x2200>",
                    "-colorspace",
                    "Gray",
                    "-contrast-stretch",
                    "0.5%x0.5%",
                    "-sharpen",
                    "0x1",
                    str(enhanced_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            if enhanced_path.exists():
                return enhanced_path
    except Exception:
        pass

    try:
        if shutil.which("sips"):
            subprocess.run(
                ["sips", "-s", "format", "png", str(image_path), "--out", str(enhanced_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            if enhanced_path.exists():
                return enhanced_path
    except Exception:
        pass

    return None


def looks_like_base64_text(value: str) -> bool:
    text = normalize_whitespace(value)
    if len(text) < 120:
        return False
    if not text.startswith("AAAA"):
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9+/= _-]+", text))


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

        languages = get_tesseract_languages()
        ocr_language = "eng+mon" if "mon" in languages else "eng"
        extracted_text = extract_image_text_with_tesseract(saved_path, ocr_language).strip()
        if not extracted_text or is_unreadable_ocr_text(extracted_text):
            return build_scan_pdf_record(title, uploader_email, folder_name)
        return build_document_record(title, uploader_email, extracted_text, folder_name, build_storage_reference(saved_path))

    try:
        content = saved_path.read_text(encoding="utf-8").strip()
    except Exception:
        return None
    if not content:
        return None
    return build_document_record(title, uploader_email, content, folder_name, build_storage_reference(saved_path))


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
