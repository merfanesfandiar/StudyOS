import re
from pathlib import PurePath

from fastapi import UploadFile

from app.core.errors import AppError

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".docx", ".md", ".zip", ".png", ".jpg", ".jpeg"}
ALLOWED_MIME_TYPES = {
    ".pdf": {"application/pdf"},
    ".txt": {"text/plain"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".md": {"text/markdown", "text/plain"},
    ".zip": {"application/zip", "application/x-zip-compressed"},
    ".png": {"image/png"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
}


def safe_filename(filename: str | None) -> str:
    if not filename:
        raise AppError(422, "INVALID_FILENAME", "A filename is required.")
    normalized = PurePath(filename.replace("\\", "/")).name.replace("\x00", "").strip()
    normalized = re.sub(r"[\r\n\t]", "", normalized)
    if not normalized or normalized in {".", ".."}:
        raise AppError(422, "INVALID_FILENAME", "The filename is invalid.")
    if len(normalized) > 255:
        raise AppError(422, "INVALID_FILENAME", "The filename is too long.")
    return normalized


def validate_upload(upload: UploadFile) -> tuple[str, str, str]:
    filename = safe_filename(upload.filename)
    extension = PurePath(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise AppError(
            415,
            "UNSUPPORTED_FILE_TYPE",
            "Supported file types are PDF, TXT, DOCX, MD, ZIP, PNG, JPG, and JPEG.",
        )
    mime_type = (upload.content_type or "").lower().split(";", 1)[0].strip()
    if mime_type not in ALLOWED_MIME_TYPES[extension]:
        raise AppError(415, "UNSUPPORTED_FILE_TYPE", "The file content type is not allowed.")
    return filename, extension, mime_type
