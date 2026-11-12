"""Verification service: snapshots, triggering, execution, persistence.

Boundaries this module keeps:

* The **service** is the only place that touches the database. Validators see
  snapshots; the pipeline sees the context; nothing else persists.
* Every load is workspace-scoped through membership — ids that are not visible
  return 404, so existence is never leaked across tenants.
* The persisted report body (``summary_json``) is bounded structured JSON:
  statuses, finding titles, evidence digests. Raw artifact content stays in
  ``agent_artifacts``; verification never duplicates it.
* Re-verification is just a new run with ``previous_run_id`` set; comparison
  between runs is derived from the rows, so history is immutable.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.core.errors import AppError
from app.models import (
    AgentArtifact,
    AgentRun,
    Assignment,
    AssignmentRequirement,
    EvaluationCriterion,
    RequirementVerification,
    RubricEvaluation,
    User,
    VerificationEvidence,
    VerificationFinding,
    VerificationRun,
    WorkspaceMember,
)
from app.models.enums import (
    AcademicDomain,
    AgentArtifactStatus,
    AuditEventType,
    VerificationRunStatus,
    VerificationTrigger,
)
from app.modules.agent.ui.envelopes import build_verification_ui
from app.modules.verification.contracts import (
    ArtifactSnapshot,
    AssignmentSnapshot,
    CriterionSnapshot,
    DeliverableSnapshot,
    RequirementSnapshot,
    VerificationContext,
)
from app.modules.verification.pipeline import PipelineReport, VerificationPipeline
from app.modules.verification.registry import ValidatorRegistry
from app.modules.verification.rubric import RubricResult, evaluate_rubric
from app.modules.verification.validators import REGISTERED
from app.services.events import record_audit
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_CONTENT_LIMIT = 100_000


def default_registry() -> ValidatorRegistry:
    return ValidatorRegistry(REGISTERED)


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------


async def build_assignment_snapshot(assignment: Assignment, db: AsyncSession) -> AssignmentSnapshot:
    """Freeze the assignment's authoritative data for verification."""
    requirements = list(
        await db.scalars(
            select(AssignmentRequirement)
            .where(AssignmentRequirement.assignment_id == assignment.id)
            .order_by(AssignmentRequirement.position)
        )
    )
    criteria = list(
        await db.scalars(
            select(EvaluationCriterion)
            .where(EvaluationCriterion.assignment_id == assignment.id)
            .order_by(EvaluationCriterion.position)
        )
    )
    deliverables = [
        DeliverableSnapshot(
            id=d.id, title=d.title, is_required=d.is_required
        )
        for d in assignment.deliverables
    ]
    types, domain = await _classified(assignment, db)
    return AssignmentSnapshot(
        id=assignment.id,
        workspace_id=assignment.workspace_id,
        title=assignment.title,
        description=assignment.description,
        assignment_types=types,
        academic_domain=domain,
        requirements=[
            RequirementSnapshot(
                id=r.id,
                code=f"REQ-{r.sequence:03d}",
                title=r.title,
                description=r.description,
                is_required=r.is_required,
                priority=r.priority,
            )
            for r in requirements
        ],
        criteria=[
            CriterionSnapshot(id=c.id, title=c.title, description=c.description, weight=c.weight)
            for c in criteria
        ],
        deliverables=deliverables,
    )


async def _classified(
    assignment: Assignment, db: AsyncSession
) -> tuple[list[str], str | None]:
    """Effective types/domain from the newest non-stale analysis, if any."""
    from app.models import AssignmentAnalysis

    latest = await db.scalar(
        select(AssignmentAnalysis)
        .where(
            AssignmentAnalysis.assignment_id == assignment.id,
            AssignmentAnalysis.is_stale.is_(False),
        )
        .order_by(AssignmentAnalysis.revision.desc())
        .limit(1)
    )
    if latest is None:
        return [], None
    payload = latest.payload or {}
    types: list[str] = []
    for item in payload.get("assignment_types") or []:
        value = item.get("type") if isinstance(item, dict) else item
        if value:
            types.append(str(value))
    domain_value: str | None = None
    for item in payload.get("academic_domains") or []:
        value = item.get("domain") if isinstance(item, dict) else item
        if value:
            domain_value = str(value)
            break
    return types[:8], domain_value


async def load_active_artifacts(assignment: Assignment, db: AsyncSession) -> list[AgentArtifact]:
    """The newest ACTIVE artifacts across the assignment's agent runs."""
    result = await db.execute(
        select(AgentArtifact)
        .join(AgentRun, AgentArtifact.run_id == AgentRun.id)
        .where(
            AgentRun.assignment_id == assignment.id,
            AgentArtifact.status == AgentArtifactStatus.ACTIVE.value,
        )
        .order_by(AgentArtifact.created_at.desc())
        .limit(50)
    )
    artifacts = result.scalars().all()
    # Keep one per (task_id, title) — the highest revision.
    best: dict[tuple[UUID | None, str], AgentArtifact] = {}
    for artifact in artifacts:
        key = (artifact.task_id, artifact.title)
        if key not in best or artifact.revision > best[key].revision:
            best[key] = artifact
    return list(best.values())


def artifact_snapshots(artifacts: list[AgentArtifact]) -> list[ArtifactSnapshot]:
    return [
        ArtifactSnapshot(
            id=artifact.id,
            title=artifact.title,
            artifact_type=artifact.artifact_type,
            content=(artifact.content or "")[:_CONTENT_LIMIT],
            revision=artifact.revision,
            worker_name=artifact.worker_name,
            metadata_json=artifact.metadata_json,
        )
        for artifact in artifacts
    ]


# ---------------------------------------------------------------------------
# Triggering
# ---------------------------------------------------------------------------


async def trigger_verification(
    assignment: Assignment,
    user: User,
    db: AsyncSession,
    *,
    scope_kind: str = "FULL",
    artifact_ids: frozenset[UUID] | None = None,
    requirement_ids: frozenset[UUID] | None = None,
    previous_run_id: UUID | None = None,
    agent_run_id: UUID | None = None,
    idempotency_key: str | None = None,
    registry: ValidatorRegistry | None = None,
) -> VerificationRun:
    """Create a verification run and execute the pipeline synchronously.

    Synchronous execution keeps the first version honest: a run either finishes
    and persists a full report, or fails and persists the failure. Moving to a
    queue/worker is an operational change, not a semantic one, and is documented
    as future work.
    """
    registry = registry or default_registry()
    idempotency_value = f"{scope_kind}:{idempotency_key}" if idempotency_key else None
    if idempotency_value:
        existing = await db.scalar(
            select(VerificationRun).where(
                VerificationRun.assignment_id == assignment.id,
                VerificationRun.idempotency_key == idempotency_value,
            )
        )
        if existing is not None:
            return existing

    run = VerificationRun(
        workspace_id=assignment.workspace_id,
        assignment_id=assignment.id,
        agent_run_id=agent_run_id,
        previous_run_id=previous_run_id,
        trigger=VerificationTrigger.AGENT_RUNTIME.value
        if agent_run_id
        else VerificationTrigger.MANUAL.value,
        scope_kind=scope_kind,
        scope_json=_scope_payload(artifact_ids, requirement_ids),
        status=VerificationRunStatus.RUNNING.value,
        idempotency_key=idempotency_value,
        started_at=datetime.now(UTC),
    )
    db.add(run)
    await db.flush()

    try:
        snapshot = await build_assignment_snapshot(assignment, db)
        artifacts = await load_active_artifacts(assignment, db)
        if artifact_ids is not None:
            artifacts = [a for a in artifacts if a.id in artifact_ids]
        report, rubric = await run_pipeline_for_assignment(
            snapshot, artifact_snapshots(artifacts), registry
        )
        await _persist_report(db, run, snapshot, report, rubric)
        run.status = VerificationRunStatus.COMPLETED.value
        run.finished_at = datetime.now(UTC)
    except Exception as error:  # noqa: BLE001 - the failure must be visible
        logger.exception("Verification run failed for assignment %s", assignment.id)
        run.status = VerificationRunStatus.FAILED.value
        run.error_message = str(error)[:2000]
        run.finished_at = datetime.now(UTC)
        await _audit(db, user, assignment, run, event_type=AuditEventType.ASSIGNMENT_UPDATED)
        raise AppError(
            500, "VERIFICATION_FAILED", "The verification pipeline failed.", None
        ) from error

    await _audit(db, user, assignment, run, event_type=AuditEventType.ASSIGNMENT_UPDATED)
    await db.flush()
    return run


async def run_pipeline_for_assignment(
    snapshot: AssignmentSnapshot,
    artifacts: list[ArtifactSnapshot],
    registry: ValidatorRegistry,
    *,
    execution: Any | None = None,
    artifact_ids: frozenset[UUID] | None = None,
    requirement_ids: frozenset[UUID] | None = None,
) -> tuple[PipelineReport, RubricResult]:
    """Pipeline + rubric for a snapshot. Separated for reuse and testing."""
    ctx = VerificationContext(
        assignment=snapshot,
        artifacts=artifacts,
        execution=execution,
        artifact_ids=artifact_ids,
        requirement_ids=requirement_ids,
    )
    pipeline = VerificationPipeline(registry)
    domain: AcademicDomain | None = None
    if snapshot.academic_domain:
        try:
            domain = AcademicDomain(snapshot.academic_domain)
        except ValueError:
            domain = None
    types = frozenset(snapshot.assignment_types)
    report = await pipeline.run(ctx, domain=domain, assignment_types=types)
    requirement_status = {
        verdict.code: verdict.status
        for result in report.results
        for verdict in result.requirement_verdicts
    }
    rubric = evaluate_rubric(snapshot.criteria, report, requirement_status)
    return report, rubric


async def _persist_report(
    db: AsyncSession,
    run: VerificationRun,
    snapshot: AssignmentSnapshot,
    report: PipelineReport,
    rubric: RubricResult | None = None,
) -> None:
    run.verdict = report.overall_status.value
    run.completion_percentage = report.completion_percentage
    run.summary_json = _summary_payload(report, rubric)

    requirement_id_by_code = {r.code: r.id for r in snapshot.requirements}
    for result in report.results:
        for finding in result.findings:
            db.add(
                VerificationFinding(
                    run_id=run.id,
                    validator_name=result.validator,
                    validator_version=result.version,
                    level=result.level.value,
                    severity=finding.severity.value,
                    title=finding.title[:300],
                    description=finding.description,
                    recommendation=finding.recommendation,
                    requirement_codes=finding.requirement_codes,
                    artifact_ids=[str(a) for a in finding.artifact_ids],
                    heuristic=finding.heuristic,
                )
            )
        for evidence in result.evidence:
            db.add(
                VerificationEvidence(
                    run_id=run.id,
                    validator_name=result.validator,
                    kind=evidence.kind,
                    source=evidence.source[:200],
                    method=evidence.method.value,
                    status=evidence.status.value,
                    content=evidence.content,
                    artifact_ids=[str(a) for a in evidence.artifact_ids],
                )
            )
        for verdict in result.requirement_verdicts:
            requirement_id = requirement_id_by_code.get(verdict.code)
            if requirement_id is None:
                continue
            await db.merge(
                RequirementVerification(
                    run_id=run.id,
                    requirement_id=requirement_id,
                    requirement_code=verdict.code,
                    status=verdict.status.value,
                    explanation=verdict.explanation,
                )
            )

    if rubric is not None and snapshot.criteria:
        criterion_by_id = {str(c.id): c for c in snapshot.criteria}
        for score in rubric.criteria:
            criterion = criterion_by_id.get(score.criterion_id)
            if criterion is None:
                continue
            await db.merge(
                RubricEvaluation(
                    run_id=run.id,
                    criterion_id=criterion.id,
                    status=score.status.value,
                    score=score.score,
                    justification=score.justification,
                    improvement=score.improvement,
                )
            )


def _summary_payload(report: PipelineReport, rubric: RubricResult | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "verdict": report.overall_status.value,
        "completion_percentage": report.completion_percentage,
        "levels_executed": [level.value for level in report.levels_executed],
        "critical_failures": report.critical_failures,
        "warnings": report.warnings,
        "unverified": report.unverified,
        "limitations": report.limitations,
        "validators": [
            {
                "name": result.validator,
                "version": result.version,
                "level": result.level.value,
                "status": result.status.value,
                "method": result.method.value,
                "confidence": result.confidence,
                "executed": result.executed,
                "summary": result.summary,
            }
            for result in report.results
        ],
        "score_kind": "estimated",
    }
    if rubric is not None:
        payload["rubric"] = {
            "scale": rubric.scale,
            "estimated": rubric.estimated,
            "weighted_total": rubric.weighted_total,
            "ambiguities": rubric.ambiguities,
            "criteria": [
                {
                    "criterion_id": c.criterion_id,
                    "title": c.title,
                    "weight": float(c.weight) if c.weight is not None else None,
                    "status": c.status.value,
                    "score": c.score,
                    "justification": c.justification,
                    "improvement": c.improvement,
                }
                for c in rubric.criteria
            ],
        }
    return payload


def _scope_payload(
    artifact_ids: frozenset[UUID] | None, requirement_ids: frozenset[UUID] | None
) -> dict[str, Any] | None:
    if artifact_ids is None and requirement_ids is None:
        return None
    return {
        "artifact_ids": [str(a) for a in (artifact_ids or ())],
        "requirement_ids": [str(r) for r in (requirement_ids or ())],
    }


async def _audit(
    db: AsyncSession,
    user: User,
    assignment: Assignment,
    run: VerificationRun,
    *,
    event_type: AuditEventType,
) -> None:
    try:
        await record_audit(
            db,
            user_id=user.id,
            workspace_id=assignment.workspace_id,
            event_type=event_type,
            entity_type="verification_run",
            entity_id=run.id,
            metadata={
                "verification_run_id": str(run.id),
                "scope_kind": run.scope_kind,
                "status": run.status,
            },
        )
    except Exception:  # noqa: BLE001 - audit must not break verification
        logger.exception("Failed to record verification audit event")


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


async def load_owned_run(run_id: UUID, user_id: UUID, db: AsyncSession) -> VerificationRun:
    """Load a verification run for a member of its workspace; 404 otherwise."""
    result = await db.execute(
        select(VerificationRun)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == VerificationRun.workspace_id)
        .where(VerificationRun.id == run_id, WorkspaceMember.user_id == user_id)
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise AppError(404, "VERIFICATION_RUN_NOT_FOUND", "Verification run not found.")
    return run


async def list_runs(
    assignment_id: UUID, user_id: UUID, db: AsyncSession, *, page: int, page_size: int
) -> tuple[list[VerificationRun], int]:
    visible = (
        select(VerificationRun)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == VerificationRun.workspace_id)
        .where(
            VerificationRun.assignment_id == assignment_id,
            WorkspaceMember.user_id == user_id,
        )
    )
    total = await db.scalar(select(func.count()).select_from(visible.subquery()))
    rows = (
        await db.scalars(
            visible.order_by(VerificationRun.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return list(rows), int(total or 0)



async def build_run_report(run: VerificationRun, db: AsyncSession) -> dict[str, Any]:
    """The full machine-readable report for one run, including comparisons."""
    findings = list(
        await db.scalars(
            select(VerificationFinding)
            .where(VerificationFinding.run_id == run.id)
            .order_by(VerificationFinding.created_at)
        )
    )
    evidence = list(
        await db.scalars(
            select(VerificationEvidence).where(VerificationEvidence.run_id == run.id)
        )
    )
    requirement_results = list(
        await db.scalars(
            select(RequirementVerification).where(RequirementVerification.run_id == run.id)
        )
    )
    rubric_scores = list(
        await db.scalars(
            select(RubricEvaluation).where(RubricEvaluation.run_id == run.id)
        )
    )
    report: dict[str, Any] = {
        "id": str(run.id),
        "assignment_id": str(run.assignment_id),
        "workspace_id": str(run.workspace_id),
        "status": run.status,
        "scope_kind": run.scope_kind,
        "trigger": run.trigger,
        "verdict": run.verdict,
        "completion_percentage": run.completion_percentage,
        "summary": run.summary_json or {},
        "findings": [
            {
                "id": str(f.id),
                "validator": f.validator_name,
                "level": f.level,
                "severity": f.severity,
                "title": f.title,
                "description": f.description,
                "recommendation": f.recommendation,
                "requirement_codes": f.requirement_codes,
                "artifact_ids": f.artifact_ids,
                "heuristic": f.heuristic,
            }
            for f in findings
        ],
        "evidence": [
            {
                "id": str(e.id),
                "validator": e.validator_name,
                "kind": e.kind,
                "source": e.source,
                "method": e.method,
                "status": e.status,
                "content": e.content,
            }
            for e in evidence
        ],
        "requirements": [
            {
                "requirement_id": str(r.requirement_id),
                "code": r.requirement_code,
                "status": r.status,
                "explanation": r.explanation,
            }
            for r in requirement_results
        ],
        "rubric": [
            {
                "criterion_id": str(s.criterion_id),
                "status": s.status,
                "score": s.score,
                "justification": s.justification,
                "improvement": s.improvement,
            }
            for s in rubric_scores
        ],
        "previous_run_id": str(run.previous_run_id) if run.previous_run_id else None,
        # Server-built UI envelope using only block types the client's
        # validator already accepts, so any renderer (including the Dynamic
        # Agent Workspace) can show this report without trusting model output.
        "ui": build_verification_ui(
            verdict=run.verdict or "UNVERIFIED",
            completion_percentage=run.completion_percentage,
            critical=(run.summary_json or {}).get("critical_failures", []),
            warnings=(run.summary_json or {}).get("warnings", []),
            unverified=(run.summary_json or {}).get("unverified", []),
            requirements=[
                {"code": row.requirement_code, "status": row.status}
                for row in requirement_results
            ],
        ),
    }
    if run.previous_run_id:
        report["comparison"] = await compare_runs(run.previous_run_id, run, db)
    return report


async def compare_runs(
    previous_run_id: UUID, current: VerificationRun, db: AsyncSession
) -> dict[str, Any] | None:
    """Status movement between two runs, per requirement."""
    previous = await db.get(VerificationRun, previous_run_id)
    if previous is None:
        return None
    previous_results = list(
        await db.scalars(
            select(RequirementVerification).where(RequirementVerification.run_id == previous.id)
        )
    )
    current_results = list(
        await db.scalars(
            select(RequirementVerification).where(RequirementVerification.run_id == current.id)
        )
    )
    previous_by_code = {r.requirement_code: r.status for r in previous_results}
    current_by_code = {r.requirement_code: r.status for r in current_results}
    changes: list[dict[str, str]] = []
    for code, status in current_by_code.items():
        before = previous_by_code.get(code)
        if before and before != status:
            changes.append({"code": code, "before": before, "after": status})
    return {
        "previous_verdict": previous.verdict,
        "current_verdict": current.verdict,
        "changes": changes,
    }
