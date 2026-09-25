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

        session.add(
            Notification(
                user_id=user.id,
                type=NotificationType.INFO.value,
                title="Welcome to StudyOS",
                message="Your demo workspace is ready. Review the seeded assignment brief.",
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
