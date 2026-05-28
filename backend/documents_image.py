from __future__ import annotations

import mimetypes
import re
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from .config import DATA_DIR
from .google_vision_service import maybe_extract_google_vision_text
from .openai_service import maybe_extract_openai_image_text
from .text_utils import extract_patient_fields, normalize_whitespace


OCR_PSMS = ("6", "11", "4")


def extract_pdf_text_with_ocr(pdf_path: Path) -> str:
    from .documents_extract import extract_pdf_text  # keep import local-free of cycles? no direct cycle but okay.

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
        if should_cleanup:
            try:
                if prepared_path.exists():
                    prepared_path.unlink()
            except OSError:
                pass


def extract_image_text_with_google_vision(image_path: Path) -> str:
    prepared_path, mime_type, should_cleanup = prepare_image_for_browser(image_path)
    try:
        image_bytes = prepared_path.read_bytes()
    except Exception:
        if should_cleanup and prepared_path.exists():
            try:
                prepared_path.unlink()
            except OSError:
                pass
        return ""

    try:
        return maybe_extract_google_vision_text(image_bytes, mime_type) or ""
    finally:
        if should_cleanup and prepared_path.exists():
            try:
                prepared_path.unlink()
            except OSError:
                pass


def extract_image_text_with_openai(image_path: Path) -> str:
    prepared_path, mime_type, should_cleanup = prepare_image_for_browser(image_path)
    try:
        image_bytes = prepared_path.read_bytes()
    except Exception:
        if should_cleanup and prepared_path.exists():
            try:
                prepared_path.unlink()
            except OSError:
                pass
        return ""

    try:
        return maybe_extract_openai_image_text(image_bytes, mime_type) or ""
    finally:
        if should_cleanup and prepared_path.exists():
            try:
                prepared_path.unlink()
            except OSError:
                pass
        if should_cleanup and prepared_path.exists():
            try:
                prepared_path.unlink()
            except OSError:
                pass


def extract_best_submission_image_text(image_path: Path, title: str) -> tuple[str, str]:
    candidates: list[tuple[str, str]] = []

    google_text = extract_image_text_with_google_vision(image_path).strip()
    if google_text:
        candidates.append((google_text, "google"))

    languages = get_tesseract_languages()
    ocr_language = "eng+mon" if "mon" in languages else "eng"
    tesseract_text = extract_image_text_with_tesseract(image_path, ocr_language).strip()
    if tesseract_text:
        candidates.append((tesseract_text, "tesseract"))

    best_text = ""
    best_source = ""
    best_score = -999.0

    for candidate_text, source in candidates:
        score = score_submission_image_text(title, candidate_text)
        if score > best_score:
            best_text = candidate_text
            best_source = source
            best_score = score

    if best_score < 12.0:
        openai_text = extract_image_text_with_openai(image_path).strip()
        if openai_text:
            openai_score = score_submission_image_text(title, openai_text)
            if openai_score > best_score:
                best_text = openai_text
                best_source = "openai"
                best_score = openai_score

    return best_text, best_source


def score_submission_image_text(title: str, text: str) -> float:
    from .documents_parsing import looks_like_base64_text  # local to avoid circular

    base_score = score_ocr_text(text)
    fields = extract_patient_fields(title, text)
    receipt_bonus = 0.0

    if fields.get("organizationName"):
        receipt_bonus += 2.5
    if fields.get("receiptDate"):
        receipt_bonus += 2.0
    if fields.get("itemInfo"):
        receipt_bonus += 3.0
    if fields.get("totalAmount"):
        receipt_bonus += 4.0

    if looks_like_base64_text(text):
        receipt_bonus -= 10.0

    return base_score + receipt_bonus


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


def is_valid_browser_image(image_path: Path) -> bool:
    if not image_path.exists() or not image_path.is_file():
        return False

    try:
        header = image_path.read_bytes()[:64]
    except OSError:
        return False

    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if header.startswith(b"\xff\xd8\xff"):
        return True
    if header.startswith((b"GIF87a", b"GIF89a")):
        return True
    if header.startswith(b"BM"):
        return True
    if header[:4] in {b"II*\x00", b"MM\x00*"}:
        return True
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return True
    if b"ftypheic" in header or b"ftypheif" in header or b"ftypmif1" in header:
        return True

    return False


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
