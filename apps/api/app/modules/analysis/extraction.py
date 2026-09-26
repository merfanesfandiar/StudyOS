"""Best-effort text extraction from assignment resources.

The prompt requires the analysis layer to read at least PDF, DOCX, PPTX, CSV,
XLSX, TXT, MD and images. Text-like files are decoded directly; the OOXML family
(DOCX/PPTX/XLSX) is read with the standard library, because those formats are zip
archives of XML parts; PDF is read with ``pypdf``.

Images carry no extractable text here. OCR needs an external engine that is not a
dependency of this service, so an image is still shown to the student as a resource
and its filename and declared type reach the analyzer, but no text is invented for
it. That is stated rather than hidden, because a resource that was read but whose
content was not is materially different from one that was never opened.

Extracted document text is untrusted. It always reaches the model inside an
explicit data envelope, never as instructions.

Extraction never raises: an unreadable or hostile file is skipped rather than
failing the whole analysis.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections.abc import Callable, Sequence
from xml.etree import ElementTree

from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.logging import logger
from app.models import Document
from app.modules.analysis.input_builder import (
    MAX_DOCUMENT_CHARS,
    MAX_TOTAL_DOCUMENT_CHARS,
    document_text_kind,
)
from app.storage import get_storage

#: OOXML namespaces, so XML parsing is namespace-aware rather than string-matched.
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

#: A zip bomb is bounded before anything is decompressed.
_MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
_MAX_PARTS = 2_000


def _cell_text(value: str) -> str:
    return value.strip()


def _safe_open_zip(data: bytes) -> zipfile.ZipFile:
    archive = zipfile.ZipFile(io.BytesIO(data))
    infos = archive.infolist()
    if len(infos) > _MAX_PARTS:
        archive.close()
        raise ValueError("too many archive parts")
    if sum(info.file_size for info in infos) > _MAX_ARCHIVE_BYTES:
        archive.close()
        raise ValueError("archive expands to too much data")
    return archive


def _read_docx(data: bytes) -> str:
    """Paragraph and table text from a WordprocessingML package."""
    with _safe_open_zip(data) as archive:
        if "word/document.xml" not in archive.namelist():
            return ""
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    lines: list[str] = []
    for paragraph in root.iter(f"{_W}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{_W}t"))
        if text.strip():
            lines.append(text.strip())
    return "\n".join(lines)


def _read_pptx(data: bytes) -> str:
    """Text from every slide, in slide order, so the narrative is preserved."""
    with _safe_open_zip(data) as archive:
        names = [
            name
            for name in archive.namelist()
            if name.startswith("ppt/slides/slide") and name.endswith(".xml")
        ]

        # slide1.xml, slide2.xml ... slide10.xml sorts wrongly as plain strings.
        def slide_number(name: str) -> int:
            found = re.search(r"slide(\d+)\.xml", name)
            return int(found.group(1)) if found else 0

        names.sort(key=slide_number)
        chunks: list[str] = []
        for name in names:
            root = ElementTree.fromstring(archive.read(name))
            texts = [node.text for node in root.iter(f"{_A}t") if node.text]
            joined = " ".join(texts).strip()
            if joined:
                chunks.append(joined)
    return "\n\n".join(chunks)


def _read_xlsx(data: bytes) -> str:
    """Shared strings plus each sheet's cells.

    Sheet values are referenced by index into the shared string table, so a cell is
    emitted as its resolved text rather than a number that means nothing to a model.
    """
    with _safe_open_zip(data) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.iter(f"{_S}si"):
                shared.append("".join(node.text or "" for node in item.iter(f"{_S}t")))
        sheets = sorted(
            name
            for name in archive.namelist()
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        )
        chunks: list[str] = []
        for name in sheets:
            root = ElementTree.fromstring(archive.read(name))
            rows: list[str] = []
            for row in root.iter(f"{_S}row"):
                cells: list[str] = []
                for cell in row.iter(f"{_S}c"):
                    cell_type = cell.get("t")
                    value_node = cell.find(f"{_S}v")
                    inline = cell.find(f"{_S}is")
                    if inline is not None:
                        text = "".join(node.text or "" for node in inline.iter(f"{_S}t"))
                    elif value_node is None or value_node.text is None:
                        text = ""
                    elif cell_type == "s":
                        try:
                            text = shared[int(value_node.text)]
                        except (ValueError, IndexError):
                            text = ""
                    else:
                        text = value_node.text
                    cells.append(_cell_text(text))
                line = ", ".join(cell for cell in cells if cell)
                if line:
                    rows.append(line)
            if rows:
                chunks.append("\n".join(rows))
    return "\n\n".join(chunks)


def _read_pdf(data: bytes) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            # An encrypted handout is common and still readable with an empty
            # password; a genuinely protected one is skipped rather than guessed at.
            try:
                reader.decrypt("")
            except Exception:  # noqa: BLE001 - any failure means "cannot read"
                return ""
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except (PdfReadError, ValueError, OSError, KeyError, IndexError, TypeError):
        return ""


def _read_csv(data: bytes) -> str:
    text = data.decode("utf-8", errors="ignore")
    reader = csv.reader(io.StringIO(text))
    return "\n".join(", ".join(_cell_text(cell) for cell in row) for row in reader)


def _read_plain(data: bytes) -> str:
    return data.decode("utf-8", errors="ignore")


#: extension -> reader. Anything absent stays metadata-only.
_READERS: dict[str, Callable[[bytes], str]] = {
    ".pdf": _read_pdf,
    ".docx": _read_docx,
    ".pptx": _read_pptx,
    ".xlsx": _read_xlsx,
    ".csv": _read_csv,
    ".txt": _read_plain,
    ".md": _read_plain,
    #: A text-like MIME type with no dedicated extension reader (JSON, TSV, ...).
    "text": _read_plain,
}


async def extract_texts(documents: Sequence[Document]) -> list[dict[str, str]]:
    """Return ``[{document_id, filename, text}]`` for resources that yield text.

    The budget is shared across documents so a folder of attachments cannot push the
    prompt past its character limit; documents are visited in the given order.
    """
    settings = get_settings()
    per_document_cap = min(MAX_DOCUMENT_CHARS, settings.analysis_max_input_chars)
    budget = min(MAX_TOTAL_DOCUMENT_CHARS, settings.analysis_max_input_chars)
    storage = get_storage()
    results: list[dict[str, str]] = []
    for document in documents:
        if budget <= 0:
            break
        kind = document_text_kind(document)
        if kind is None:
            continue
        try:
            raw = await run_in_threadpool(storage.read, document.storage_key)
            text = await run_in_threadpool(_READERS[kind], raw) if kind in _READERS else ""
        except (
            FileNotFoundError,
            OSError,
            ValueError,
            KeyError,
            IndexError,
            zipfile.BadZipFile,
            ElementTree.ParseError,
        ) as exc:
            logger.warning(
                "document_extraction_skipped",
                extra={
                    "document_id": str(document.id),
                    "kind": kind,
                    "error_type": type(exc).__name__,
                },
            )
            continue
        text = text.strip()
        if not text:
            logger.info(
                "document_extraction_empty",
                extra={"document_id": str(document.id), "kind": kind},
            )
            continue
        excerpt = text[: min(per_document_cap, budget)]
        budget -= len(excerpt)
        results.append(
            {
                "document_id": str(document.id),
                "filename": document.filename,
                "text": excerpt,
            }
        )
    return results
