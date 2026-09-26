"""Best-effort extraction of plain text from assignment resources.

Only formats that can be decoded without heavy, attack-surface-increasing
parsing dependencies are read directly (text, Markdown, CSV, JSON). Binary
formats (PDF, DOCX, PPTX, XLSX, images) are represented by metadata only; the
student still sees them as analyzed resources. Document text is untrusted and is
always delivered to the model inside an explicit data envelope.

Extraction never raises: an unreadable file is skipped rather than failing an
analysis.
"""

from __future__ import annotations

from collections.abc import Sequence

from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.logging import logger
from app.models import Document
from app.modules.analysis.input_builder import (
    MAX_DOCUMENT_CHARS,
    MAX_TOTAL_DOCUMENT_CHARS,
    is_text_extractable,
)
from app.storage import get_storage


async def extract_texts(documents: Sequence[Document]) -> list[dict[str, str]]:
    """Return ``[{document_id, filename, text}]`` for text-extractable resources."""
    settings = get_settings()
    configurable_cap = min(MAX_DOCUMENT_CHARS, settings.analysis_max_input_chars)
    budget = min(MAX_TOTAL_DOCUMENT_CHARS, settings.analysis_max_input_chars)
    storage = get_storage()
    results: list[dict[str, str]] = []
    for document in documents:
        if budget <= 0:
            break
        if not is_text_extractable(document):
            continue
        try:
            raw = await run_in_threadpool(storage.read, document.storage_key)
            text = raw.decode("utf-8", errors="ignore")
        except (FileNotFoundError, OSError, ValueError) as exc:
            logger.warning(
                "document_extraction_skipped",
                extra={"document_id": str(document.id), "error_type": type(exc).__name__},
            )
            continue
        excerpt = text[: min(configurable_cap, budget)]
        budget -= len(excerpt)
        results.append(
            {
                "document_id": str(document.id),
                "filename": document.filename,
                "text": excerpt,
            }
        )
    return results
