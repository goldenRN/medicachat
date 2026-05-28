from __future__ import annotations

import re
import subprocess
import zipfile
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree as ET

from .config import DATA_DIR, UPLOAD_DIR
from .documents_storage import IMAGE_EXTENSIONS
from .text_utils import normalize_whitespace


DOCX_XML_PARTS = (
    "word/document.xml",
    "word/header1.xml",
    "word/header2.xml",
    "word/header3.xml",
    "word/footer1.xml",
    "word/footer2.xml",
    "word/footer3.xml",
)
XLSX_SHARED_STRINGS_PART = "xl/sharedStrings.xml"
XLSX_SHEET_PART_PREFIX = "xl/worksheets/"


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


def extract_xlsx_text(xlsx_path: Path) -> str:
    sections: list[str] = []
    try:
        with zipfile.ZipFile(xlsx_path) as archive:
            shared_strings = extract_xlsx_shared_strings(archive)
            sheet_names = sorted(
                name for name in archive.namelist() if name.startswith(XLSX_SHEET_PART_PREFIX) and name.endswith(".xml")
            )
            for sheet_name in sheet_names:
                xml_text = archive.read(sheet_name).decode("utf-8", errors="ignore")
                sheet_text = extract_text_from_spreadsheetml(xml_text, shared_strings)
                if sheet_text:
                    sections.append(sheet_text)
    except Exception:
        return ""
    return normalize_whitespace("\n\n".join(section for section in sections if section))


def extract_xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if XLSX_SHARED_STRINGS_PART not in set(archive.namelist()):
        return []
    try:
        xml_text = archive.read(XLSX_SHARED_STRINGS_PART).decode("utf-8", errors="ignore")
    except Exception:
        return []

    entries = re.findall(r"<si\b.*?>.*?</si>", xml_text, flags=re.DOTALL)
    return [normalize_whitespace(extract_text_from_spreadsheetml_inline(entry)) for entry in entries]


@lru_cache(maxsize=64)
def count_xlsx_data_rows(xlsx_path_str: str) -> int:
    xlsx_path = Path(xlsx_path_str)
    if not xlsx_path.exists() or xlsx_path.suffix.lower() != ".xlsx":
        return 0

    total_rows = 0
    try:
        with zipfile.ZipFile(xlsx_path) as archive:
            sheet_names = sorted(
                name for name in archive.namelist() if name.startswith(XLSX_SHEET_PART_PREFIX) and name.endswith(".xml")
            )
            for sheet_name in sheet_names:
                saw_header = False
                with archive.open(sheet_name) as sheet_stream:
                    for _, element in ET.iterparse(sheet_stream, events=("end",)):
                        if not element.tag.endswith("row"):
                            continue
                        has_cells = any(child.tag.endswith("c") for child in list(element))
                        element.clear()
                        if not has_cells:
                            continue
                        if not saw_header:
                            saw_header = True
                            continue
                        total_rows += 1
    except Exception:
        return 0

    return total_rows


def count_spreadsheet_data_rows(storage_path: str) -> int:
    safe_storage_path = str(storage_path or "").strip()
    if not safe_storage_path:
        return 0

    file_path = (UPLOAD_DIR / safe_storage_path).resolve()
    if not str(file_path).startswith(str(UPLOAD_DIR.resolve())) or not file_path.exists():
        return 0

    if file_path.suffix.lower() == ".xlsx":
        return count_xlsx_data_rows(str(file_path))

    return 0


def extract_text_from_spreadsheetml(xml_text: str, shared_strings: list[str]) -> str:
    rows = re.findall(r"<row\b.*?>.*?</row>", xml_text, flags=re.DOTALL)
    rendered_rows: list[str] = []
    for row_xml in rows:
        values: list[str] = []
        cells = re.findall(r"<c\b([^>]*)>(.*?)</c>", row_xml, flags=re.DOTALL)
        for attributes, cell_body in cells:
            cell_type_match = re.search(r'\bt="([^"]+)"', attributes)
            cell_type = cell_type_match.group(1) if cell_type_match else ""
            value_match = re.search(r"<v>(.*?)</v>", cell_body, flags=re.DOTALL)
            inline_match = re.search(r"<is\b.*?>.*?</is>", cell_body, flags=re.DOTALL)
            value = ""
            if cell_type == "s" and value_match:
                try:
                    shared_index = int(value_match.group(1).strip())
                except ValueError:
                    shared_index = -1
                if 0 <= shared_index < len(shared_strings):
                    value = shared_strings[shared_index]
            elif inline_match:
                value = extract_text_from_spreadsheetml_inline(inline_match.group(0))
            elif value_match:
                value = normalize_whitespace(value_match.group(1))
            if value:
                values.append(value)
        if values:
            rendered_rows.append(" | ".join(values))
    return "\n".join(rendered_rows)


def extract_text_from_spreadsheetml_inline(xml_text: str) -> str:
    prepared = re.sub(r"</(?:t|r|p)>", " ", xml_text)
    prepared = re.sub(r"<[^>]+>", "", prepared)
    prepared = (
        prepared.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
    )
    return normalize_whitespace(prepared)


def extract_legacy_office_text(file_path: Path) -> str:
    try:
        result = subprocess.run(
            ["strings", "-n", "4", str(file_path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return ""

    lines = [normalize_whitespace(line) for line in result.stdout.splitlines()]
    filtered = [line for line in lines if line and len(line) > 2]
    return "\n".join(filtered[:400])


def extract_text_from_wordprocessingml(xml_text: str) -> str:
    prepared = xml_text
    prepared = re.sub(r"<w:tab(?:\s[^>]*)?/>", "\t", prepared)
    prepared = re.sub(r"<w:br(?:\s[^>]*)?/>", "\n", prepared)
    prepared = re.sub(r"</w:p>", "\n", prepared)
    prepared = re.sub(r"</w:tr>", "\n", prepared)
    prepared = re.sub(r"</w:tc>", " ", prepared)
    prepared = re.sub(r"<[^>]+>", "", prepared)
    prepared = (
        prepared.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
    )

    lines = [normalize_whitespace(line) for line in prepared.splitlines()]
    return "\n".join(line for line in lines if line)
