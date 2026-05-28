from __future__ import annotations

from .config import DATA_DIR, UPLOAD_DIR
from .documents_extract import (
    DOCX_XML_PARTS,
    XLSX_SHARED_STRINGS_PART,
    XLSX_SHEET_PART_PREFIX,
    count_spreadsheet_data_rows,
    count_xlsx_data_rows,
    extract_docx_text,
    extract_legacy_office_text,
    extract_pdf_text,
    extract_text_from_spreadsheetml,
    extract_text_from_spreadsheetml_inline,
    extract_text_from_wordprocessingml,
    extract_xlsx_shared_strings,
    extract_xlsx_text,
)
from .documents_image import (
    OCR_PSMS,
    extract_best_submission_image_text,
    extract_image_text_with_google_vision,
    extract_image_text_with_openai,
    extract_image_text_with_tesseract,
    extract_pdf_text_with_ocr,
    get_tesseract_languages,
    is_unreadable_ocr_text,
    is_valid_browser_image,
    prepare_image_for_browser,
    prepare_image_for_ocr,
    prepare_image_for_ocr_quality,
    run_tesseract,
    score_ocr_text,
    score_submission_image_text,
)
from .documents_parsing import (
    looks_like_base64_text,
    parse_submission_image_file,
    parse_uploaded_file,
    recover_submission_file,
    recover_uploaded_file,
)
from .documents_storage import (
    IMAGE_EXTENSIONS,
    OFFICE_BINARY_EXTENSIONS,
    build_document_record,
    build_scan_pdf_record,
    build_storage_path,
    build_storage_reference,
    copy_document_storage,
    decode_upload_bytes,
    delete_document_storage,
    delete_folder_storage,
    delete_storage_asset,
    folder_storage_name,
    infer_folder_from_storage_path,
    move_folder_storage,
    resolve_document_storage_path,
    save_employee_photo,
)

