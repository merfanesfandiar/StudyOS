import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionFactory, engine
from app.models import (
    Assignment,
    AssignmentConstraint,
    AssignmentRequirement,
    Course,
    EvaluationCriterion,
    Notification,
    User,
    Workspace,
    WorkspaceMember,
)
from app.models.enums import (
    AssignmentStatus,
    NotificationType,
    RequirementPriority,
    RequirementType,
    WorkspaceRole,
)

DEMO_EMAIL = "student@studyos.dev"
DEMO_PASSWORD = "Studyos123"


async def seed() -> None:
    async with SessionFactory() as session:
        existing = await session.scalar(select(User).where(User.email == DEMO_EMAIL))
        if existing is not None:
            print(f"Demo data already exists for {DEMO_EMAIL}")
            return

        user = User(
            name="Alex Student",
            email=DEMO_EMAIL,
            password_hash=hash_password(DEMO_PASSWORD),
        )
        workspace = Workspace(name="Alex's workspace", owner=user)
        membership = WorkspaceMember(
            workspace=workspace,
            user=user,
            role=WorkspaceRole.OWNER.value,
        )
        session.add_all([user, workspace, membership])
        await session.flush()

        programming = Course(
            workspace_id=workspace.id,
            name="Advanced Programming",
            code="AP140",
            description="Object-oriented design, testing, and maintainable Java.",
        )
        data_structures = Course(
            workspace_id=workspace.id,
            name="Data Structures",
            code="DS220",
            description="Collections, trees, graphs, and algorithm analysis.",
        )
        session.add_all([programming, data_structures])
        await session.flush()

        assignment = Assignment(
            workspace_id=workspace.id,
            course_id=programming.id,
            title="Strategy game milestone",
            description=(
                "Build a small turn-based strategy game with a playable core and automated tests."
            ),
            deadline=datetime.now(UTC) + timedelta(days=14),
            status=AssignmentStatus.ACTIVE.value,
            requirements=[
                AssignmentRequirement(
                    title="Playable game loop",
                    description="Players alternate turns until a win or draw condition is reached.",
                    priority=RequirementPriority.HIGH.value,
                    type=RequirementType.FUNCTIONAL.value,
                ),
                AssignmentRequirement(
                    title="Automated tests",
                    description="Core rules and win conditions are covered by automated tests.",
                    priority=RequirementPriority.CRITICAL.value,
                    type=RequirementType.TECHNICAL.value,
                ),
                AssignmentRequirement(
                    title="Project documentation",
                    description="Document how to build, run, and play the project.",
                    priority=RequirementPriority.MEDIUM.value,
                    type=RequirementType.DOCUMENTATION.value,
                ),
            ],
            constraints=[
                AssignmentConstraint(
                    title="Java version",
                    description="Build and run with Java 17 or newer.",
                    value="17",
                ),
                AssignmentConstraint(
                    title="Dependencies",
                    description="Only the standard JDK library may be used.",
                ),
            ],
            criteria=[
                EvaluationCriterion(
                    title="Functionality",
                    description="The game satisfies the required gameplay behaviors.",
                    weight=Decimal("60.00"),
                ),
                EvaluationCriterion(
                    title="Code quality",
                    description="The implementation is clear, tested, and maintainable.",
                    weight=Decimal("40.00"),
                ),
            ],
        )
        session.add(assignment)
        await session.flush()

        coursework = Assignment(
            workspace_id=workspace.id,
            course_id=data_structures.id,
            title="Graph traversal report",
            description=(
                "Compare breadth-first and depth-first search on the same dataset and "
                "report the results."
            ),
            deadline=datetime.now(UTC) + timedelta(days=5),
            status=AssignmentStatus.ACTIVE.value,
            requirements=[
                AssignmentRequirement(
                    title="Documented results",
                    description="Include input sizes, run times, and a short comparison.",
                    priority=RequirementPriority.HIGH.value,
                    type=RequirementType.DOCUMENTATION.value,
                ),
                AssignmentRequirement(
                    title="Reproducible script",
                    description="One command regenerates every measurement in the report.",
                    priority=RequirementPriority.MEDIUM.value,
                    type=RequirementType.TECHNICAL.value,
                ),
            ],
            constraints=[
                AssignmentConstraint(
                    title="Dataset",
                    description="Use the provided graph dataset without modification.",
                    value="graphs-v2.csv",
                ),
            ],
            criteria=[
                EvaluationCriterion(
                    title="Correctness",
                    description="Traversals visit every reachable node exactly once.",
                    weight=Decimal("50.00"),
                ),
                EvaluationCriterion(
                    title="Analysis quality",
                    description="The comparison explains when each traversal is preferable.",
                    weight=Decimal("50.00"),
                ),
            ],
        )
        reflection = Assignment(
            workspace_id=workspace.id,
            course_id=programming.id,
            title="Refactoring retrospective",
            description=(
                "Summarize the refactoring work from the strategy game and note what you "
                "would change."
            ),
            deadline=datetime.now(UTC) - timedelta(days=2),
            status=AssignmentStatus.DRAFT.value,
            requirements=[
                AssignmentRequirement(
                    title="Written reflection",
                    description=(
                        "Describe one change that improved the design and one that did not."
                    ),
                    priority=RequirementPriority.MEDIUM.value,
                    type=RequirementType.DOCUMENTATION.value,
                ),
            ],
            constraints=[
                AssignmentConstraint(
                    title="Length",
                    description="At most 500 words.",
                    value="500 words",
                ),
            ],
            criteria=[
                EvaluationCriterion(
                    title="Clarity",
                    description="The reasoning is specific to this project, not generic advice.",
                    weight=Decimal("100.00"),
                ),
            ],
        )
        session.add_all([coursework, reflection])

        session.add(
            Notification(
                user_id=user.id,
                type=NotificationType.INFO.value,
                title="Welcome to StudyOS",
                message="Your demo workspace is ready with two courses and three assignments.",
            )
        )
        await session.commit()
        print(f"Demo account created: {DEMO_EMAIL} / {DEMO_PASSWORD}")


async def main() -> None:
    try:
        await seed()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
