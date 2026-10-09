from typing import Annotated
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.dependencies import get_current_user, get_owned_document
from app.core.errors import AppError
from app.db.session import get_db
from app.models import Document, User
from app.models.enums import AuditEventType
from app.modules.assignments.service import load_owned_assignment, record_specification_change
from app.schemas.common import Page, PageParams, PageResponse, error_responses
from app.schemas.documents import DocumentResponse
from app.services.file_validation import validate_upload
from app.storage import get_storage

router = APIRouter(tags=["Documents"])
settings = get_settings()


def document_response(document: Document) -> DocumentResponse:
    return DocumentResponse(
        id=str(document.id),
        assignment_id=str(document.assignment_id),
        filename=document.filename,
        mime_type=document.mime_type,
        size=document.size,
        created_at=document.created_at,
    )


@router.get(
    "/api/v1/assignments/{assignment_id}/documents",
    response_model=PageResponse[DocumentResponse],
    summary="List assignment documents",
    responses=error_responses(404, 422),
)
async def list_documents(
    assignment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    params: Annotated[PageParams, Query()] = PageParams(),
) -> PageResponse[DocumentResponse]:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    total = await db.scalar(
        select(func.count(Document.id)).where(Document.assignment_id == assignment.id)
    )
    result = await db.scalars(
        select(Document)
        .where(Document.assignment_id == assignment.id)
        .order_by(Document.created_at.desc(), Document.filename.asc())
        .offset(params.offset)
        .limit(params.limit)
    )
    documents = list(result)
    pages = max(1, -(-(total or 0) // params.page_size))
    return PageResponse(
        items=[document_response(document) for document in documents],
        page=Page(page=params.page, page_size=params.page_size, total=total or 0, pages=pages),
    )


@router.post(
    "/api/v1/assignments/{assignment_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload an assignment document",
)
async def upload_document(
    assignment_id: UUID,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    filename, extension, mime_type = validate_upload(file)
    storage_key = f"{assignment.workspace_id}/{assignment.id}/{uuid4()}{extension}"
    storage = get_storage()
    await file.seek(0)
    try:
        size = await run_in_threadpool(
            storage.save, storage_key, file.file, settings.max_upload_size
        )
    except ValueError as exc:
        raise AppError(
            413, "FILE_TOO_LARGE", "The uploaded file exceeds the maximum allowed size."
        ) from exc
    document = Document(
        assignment=assignment,
        filename=filename,
        storage_key=storage_key,
        mime_type=mime_type,
        size=size,
    )
    db.add(document)
    try:
        await db.flush()
        # Resources take part in the readiness checklist, so an upload is a
        # specification change: the stored score, audit trail, and version
        # history all have to move with it.
        await record_specification_change(
            db,
            assignment=assignment,
            user_id=user.id,
            event_type=AuditEventType.DOCUMENT_UPLOADED,
            entity_type="Document",
            entity_id=document.id,
            change_summary=f"Uploaded {filename}",
            metadata={"filename": filename, "size": size},
        )
        await db.commit()
    except Exception:
        await db.rollback()
        await run_in_threadpool(storage.delete, storage_key)
        raise
    await db.refresh(document)
    return document_response(document)


@router.get(
    "/api/v1/documents/{document_id}",
    response_model=DocumentResponse,
    summary="Get document metadata",
)
async def get_document(
    document_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    return document_response(await get_owned_document(document_id, user, db))


@router.get("/api/v1/documents/{document_id}/download", summary="Download a document")
async def download_document(
    document_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    document = await get_owned_document(document_id, user, db)
    storage = get_storage()
    try:
        content = await run_in_threadpool(storage.read, document.storage_key)
    except FileNotFoundError as exc:
        raise AppError(
            404, "DOCUMENT_CONTENT_NOT_FOUND", "The document content is unavailable."
        ) from exc
    encoded_name = quote(document.filename, safe="")
    return Response(
        content=content,
        media_type=document.mime_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"},
    )


@router.delete(
    "/api/v1/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document",
)
async def delete_document(
    document_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    document = await get_owned_document(document_id, user, db)
    assignment = await load_owned_assignment(document.assignment_id, user.id, db)
    filename = document.filename
    await db.delete(document)
    # Reload the graph from the database so the recomputed score reflects the
    # assignment as it looks once the delete is committed. Disassociating the
    # document from the collection instead would null its foreign key and make
    # the DELETE match no rows.
    await db.flush()
    await db.refresh(assignment, ["documents"])
    await record_specification_change(
        db,
        assignment=assignment,
        user_id=user.id,
        event_type=AuditEventType.DOCUMENT_DELETED,
        entity_type="Document",
        entity_id=document.id,
        change_summary=f"Deleted {filename}",
    )
    await db.commit()
    await run_in_threadpool(get_storage().delete, document.storage_key)
