"""Builds the analyzer input from an assignment specification.

Two responsibilities matter here:

* **Privacy.** Only assignment context is sent to a provider. User names,
  emails, ids and unrelated workspace data are never included. Document *text*
  is only included when the deployment explicitly enables it; metadata is always
  included.
* **Versioning.** The specification is hashed canonically so an analysis can be
  tied to the exact specification it was computed against, and so two identical
  requests can be recognised as idempotent.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings, get_settings
from app.models import Assignment, Document
from app.models.identifiers import requirement_code

#: The analysis contract version. Bump when the persisted shape changes.
ANALYSIS_VERSION = 1

#: Resource types that can be read as text without extra parsing dependencies.
_TEXT_MIME_PREFIXES = ("text/",)
_TEXT_MIME_TYPES = frozenset({"application/json", "application/csv"})
_TEXT_EXTENSIONS = (".txt", ".md", ".markdown", ".csv", ".json", ".tsv")
#: Extensions with a dedicated reader in the extraction layer. Order matters only
#: for readability; none of these is a suffix of another.
_READABLE_EXTENSIONS = (".pdf", ".docx", ".pptx", ".xlsx", ".csv", ".txt", ".md")

#: Per-document and total character caps for extracted text.
MAX_DOCUMENT_CHARS = 20_000
MAX_TOTAL_DOCUMENT_CHARS = 60_000


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class AnalyzerInput:
    payload: dict[str, Any]
    specification_hash: str
    input_hash: str
    user_notes: str | None
    document_texts: tuple[dict[str, str], ...] = field(default_factory=tuple)

    def idempotency_key(
        self, *, assignment_id: str, prompt_version: str, provider: str, model: str
    ) -> str:
        return sha256_hex(
            canonical_json(
                {
                    "assignment_id": assignment_id,
                    "specification_hash": self.specification_hash,
                    "analysis_version": ANALYSIS_VERSION,
                    "prompt_version": prompt_version,
                    "provider": provider,
                    "model": model,
                    "notes_hash": sha256_hex(self.user_notes or ""),
                }
            )
        )


def _requirement_payload(assignment: Assignment) -> list[dict[str, Any]]:
    return [
        {
            "id": str(requirement.id),
            "code": requirement_code(requirement.sequence),
            "title": requirement.title,
            "description": requirement.description,
            "priority": requirement.priority,
            "type": requirement.type,
            "is_required": requirement.is_required,
        }
        for requirement in sorted(assignment.requirements, key=lambda item: item.sequence)
    ]


def _constraint_payload(assignment: Assignment) -> list[dict[str, Any]]:
    return [
        {
            "id": str(constraint.id),
            "title": constraint.title,
            "description": constraint.description,
            "value": constraint.value,
            "type": constraint.type,
            "severity": constraint.severity,
        }
        for constraint in assignment.constraints
    ]


def _criterion_payload(assignment: Assignment) -> list[dict[str, Any]]:
    return [
        {
            "id": str(criterion.id),
            "title": criterion.title,
            "description": criterion.description,
            "weight": str(criterion.weight),
        }
        for criterion in assignment.criteria
    ]


def _deliverable_payload(assignment: Assignment) -> list[dict[str, Any]]:
    return [
        {
            "id": str(deliverable.id),
            "title": deliverable.title,
            "description": deliverable.description,
            "type": deliverable.type,
            "is_required": deliverable.is_required,
        }
        for deliverable in assignment.deliverables
    ]


def _resource_payload(assignment: Assignment) -> list[dict[str, Any]]:
    return [
        {
            "id": str(document.id),
            "filename": document.filename,
            "mime_type": document.mime_type,
            "size": document.size,
            "resource_type": _resource_type(document),
        }
        for document in assignment.documents
    ]


def _resource_type(document: Document) -> str:
    from app.ai.lexicon import RESOURCE_TYPE_BY_EXTENSION

    lowered = document.filename.lower()
    for extension, resource_type in RESOURCE_TYPE_BY_EXTENSION.items():
        if lowered.endswith(extension):
            return resource_type
    return "OTHER"


def is_text_extractable(document: Document) -> bool:
    """True when the resource is expected to yield text without an OCR engine.

    Images are readable resources but carry no extractable text, so they are not
    included here; they still reach the analyzer as metadata.
    """
    if document.mime_type.startswith(_TEXT_MIME_PREFIXES) or document.mime_type in _TEXT_MIME_TYPES:
        return True
    return document.filename.lower().endswith(_TEXT_EXTENSIONS)


def document_text_kind(document: Document) -> str | None:
    """The reader key for a document, or ``None`` when it yields no text.

    The extension decides, not the declared MIME type: a client can label a file
    anything, and the extension is what selects the parser. Returns one of the keys
    of :data:`app.modules.analysis.extraction._READERS`, or ``"text"`` for a
    text-like MIME type with no more specific reader.
    """
    lowered = document.filename.lower()
    for extension in _READABLE_EXTENSIONS:
        if lowered.endswith(extension):
            return extension
    if document.mime_type.startswith(_TEXT_MIME_PREFIXES) or document.mime_type in _TEXT_MIME_TYPES:
        return "text"
    return None


def build_analyzer_input(
    assignment: Assignment,
    *,
    user_notes: str | None = None,
    settings: Settings | None = None,
) -> AnalyzerInput:
    """Assemble the redacted, hashed analyzer input for one assignment."""
    config = settings or get_settings()
    requirements = _requirement_payload(assignment)
    constraints = _constraint_payload(assignment)
    criteria = _criterion_payload(assignment)
    deliverables = _deliverable_payload(assignment)
    resources = _resource_payload(assignment)
    course_name = assignment.course.name if assignment.course else None
    course_code = assignment.course.code if assignment.course else None

    # The hash of the authoritative specification excludes per-request notes, so
    # it identifies the specification version, not the request.
    spec_payload = {
        "title": assignment.title,
        "description": assignment.description,
        "deadline": assignment.deadline.isoformat() if assignment.deadline else None,
        "course": {"name": course_name, "code": course_code},
        "requirements": requirements,
        "constraints": constraints,
        "criteria": criteria,
        "deliverables": deliverables,
        "resources": resources,
    }
    specification_hash = sha256_hex(canonical_json(spec_payload))

    payload: dict[str, Any] = {
        "assignment": {
            "id": str(assignment.id),
            "title": assignment.title,
            "description": (assignment.description or "")[: config.analysis_max_input_chars],
            "deadline": assignment.deadline.isoformat() if assignment.deadline else None,
            "status": assignment.status,
            "course_name": course_name,
            "course_code": course_code,
        },
        "course_name": course_name,
        "course_code": course_code,
        "requirements": requirements,
        "constraints": constraints,
        "criteria": criteria,
        "deliverables": deliverables,
        "resources": resources,
        "document_texts": [],
        "assigned_types": [],
        "assigned_domains": [],
        "user_notes": (user_notes or None),
    }
    input_hash = sha256_hex(canonical_json(payload))
    return AnalyzerInput(
        payload=payload,
        specification_hash=specification_hash,
        input_hash=input_hash,
        user_notes=user_notes,
    )


def attach_document_texts(
    analyzer_input: AnalyzerInput, texts: list[dict[str, str]]
) -> AnalyzerInput:
    """Return a copy of the input with extracted document text attached."""
    payload = {**analyzer_input.payload, "document_texts": texts}
    return AnalyzerInput(
        payload=payload,
        specification_hash=analyzer_input.specification_hash,
        input_hash=sha256_hex(canonical_json(payload)),
        user_notes=analyzer_input.user_notes,
    )
