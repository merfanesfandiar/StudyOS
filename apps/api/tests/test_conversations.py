"""Agent Workspace conversation layer: persistence, isolation, semantics.

Covers the conversation/message API surface, the documented edit semantics,
tenant isolation, the agent run→conversation bridge, and the SSE event
stream's resume/terminal behaviour.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.models import (
    Assignment,
    Course,
    User,
    Workspace,
    WorkspaceMember,
)
from app.models.enums import ConversationRole, WorkspaceRole
from sqlalchemy import select


async def _seed_user(client, db_session) -> tuple[str, UUID, str]:
    """Register a user and give them a workspace (mirrors other suites)."""
    email = f"ws-{uuid4().hex[:8]}@example.com"
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Password123!", "name": "WS"},
    )
    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    workspace = Workspace(name=f"WS-{uuid4().hex[:6]}", owner_id=user.id)
    db_session.add(workspace)
    await db_session.flush()
    db_session.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user.id,
            role=WorkspaceRole.OWNER.value,
        )
    )
    await db_session.flush()
    return str(user.id), workspace.id, email


async def _seed_assignment(db_session, workspace_id: UUID) -> UUID:
    from datetime import UTC as _UTC

    course = Course(
        workspace_id=workspace_id, code=f"CS{uuid4().hex[:4]}", name="Intro"
    )
    db_session.add(course)
    await db_session.flush()
    assignment = Assignment(
        workspace_id=workspace_id,
        course_id=course.id,
        title="Workspace fixture",
        created_at=datetime.now(_UTC),
        updated_at=datetime.now(_UTC),
    )
    db_session.add(assignment)
    await db_session.flush()
    return assignment.id


# ---------------------------------------------------------------------------
# Conversations CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestConversationLifecycle:
    async def test_create_list_search_rename_archive_delete(self, client, db_session) -> None:
        await _seed_user(client, db_session)
        created = await client.post(
            "/api/v1/conversations", json={"title": "Thesis planning"}
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["status"] == "ACTIVE"
        assert body["assignment_id"] is None
        conversation_id = body["id"]

        # A second one, renamed, to exercise search and ordering.
        await client.post("/api/v1/conversations", json={"title": "Lab questions"})

        listed = (await client.get("/api/v1/conversations")).json()
        assert listed["page"]["total"] == 2

        found = (await client.get("/api/v1/conversations", params={"q": "Thesis"})).json()
        assert found["page"]["total"] == 1
        assert found["items"][0]["id"] == conversation_id

        renamed = await client.patch(
            f"/api/v1/conversations/{conversation_id}", json={"title": "Thesis v2"}
        )
        assert renamed.status_code == 200
        assert renamed.json()["title"] == "Thesis v2"

        archived = await client.patch(
            f"/api/v1/conversations/{conversation_id}", json={"status": "ARCHIVED"}
        )
        assert archived.json()["status"] == "ARCHIVED"

        # Archived conversations are excluded unless explicitly requested.
        assert (await client.get("/api/v1/conversations")).json()["page"]["total"] == 1
        archived_list = (
            await client.get("/api/v1/conversations", params={"status": "ARCHIVED"})
        ).json()
        assert archived_list["page"]["total"] == 1

        deleted = await client.delete(f"/api/v1/conversations/{conversation_id}")
        assert deleted.status_code == 200
        assert deleted.json()["status"] == "DELETED"

        # A deleted conversation is invisible everywhere, including direct GET.
        assert (
            await client.get(f"/api/v1/conversations/{conversation_id}")
        ).status_code == 404
        archived_list = (
            await client.get("/api/v1/conversations", params={"status": "ARCHIVED"})
        ).json()
        assert archived_list["page"]["total"] == 0

    async def test_create_binds_assignment_and_validates_membership(
        self, client, db_session
    ) -> None:
        _user_id, workspace_id, _email = await _seed_user(client, db_session)
        assignment_id = await _seed_assignment(db_session, workspace_id)
        created = await client.post(
            "/api/v1/conversations",
            json={"title": "Help with this", "assignment_id": str(assignment_id)},
        )
        assert created.status_code == 201, created.text
        assert created.json()["assignment_id"] == str(assignment_id)

        # Another tenant's assignment id is a 404, never a binding: seed a
        # second user (which switches the session cookie) and have it ask for
        # the FIRST user's assignment, whose workspace it does not belong to.
        await _seed_user(client, db_session)
        foreign = await client.post(
            "/api/v1/conversations",
            json={"title": "cross-tenant", "assignment_id": str(assignment_id)},
        )
        assert foreign.status_code == 404

    async def test_cross_tenant_conversation_invisible(self, client, db_session) -> None:
        _uid, _ws, owner_email = await _seed_user(client, db_session)
        created = await client.post("/api/v1/conversations", json={"title": "mine"})
        conversation_id = created.json()["id"]

        _other_id, _other_ws, other_email = await _seed_user(client, db_session)
        # Switch the session cookie to the other tenant's identity.
        other = await client.post(
            "/api/v1/auth/login",
            json={"email": other_email, "password": "Password123!"},
        )
        assert other.status_code == 200, other.text
        mine_as_other = await client.get(
            f"/api/v1/conversations/{conversation_id}"
        )
        assert mine_as_other.status_code == 404
        listed = await client.get("/api/v1/conversations")
        assert listed.json()["page"]["total"] == 0


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMessages:
    async def test_post_list_pagination_and_edit_history(self, client, db_session) -> None:
        await _seed_user(client, db_session)
        conversation_id = (await client.post("/api/v1/conversations", json={})).json()["id"]

        sent = []
        for i in range(5):
            r = await client.post(
                f"/api/v1/conversations/{conversation_id}/messages",
                json={"content": f"message {i}"},
            )
            assert r.status_code == 201, r.text
            sent.append(r.json())

        # Initial window: most recent 3, oldest→newest.
        window = (
            await client.get(
                f"/api/v1/conversations/{conversation_id}/messages", params={"limit": 3}
            )
        ).json()
        assert [m["content"] for m in window["items"]] == ["message 2", "message 3", "message 4"]
        assert window["has_more_history"] is True

        # Walk back with the cursor.
        older = (
            await client.get(
                f"/api/v1/conversations/{conversation_id}/messages",
                params={"limit": 3, "before": window["next_before_cursor"]},
            )
        ).json()
        assert [m["content"] for m in older["items"]] == ["message 0", "message 1"]
        assert older["has_more_history"] is False

        # Incremental read after the newest id returns nothing new.
        incremental = (
            await client.get(
                f"/api/v1/conversations/{conversation_id}/messages",
                params={"after": sent[-1]["id"]},
            )
        ).json()
        assert incremental["items"] == []

        # Edit the last user message: prior content preserved.
        edited = await client.patch(
            f"/api/v1/conversations/{conversation_id}/messages/{sent[-1]['id']}",
            json={"content": "message 4, corrected"},
        )
        assert edited.status_code == 200
        assert edited.json()["edited_revision"] == 2
        assert edited.json()["edit_history_json"] == [
            {"revision": 1, "content": "message 4"}
        ]

        # Editing an earlier (non-latest) message is refused with explicit semantics.
        early = await client.patch(
            f"/api/v1/conversations/{conversation_id}/messages/{sent[0]['id']}",
            json={"content": "rewrite history"},
        )
        assert early.status_code == 422
        assert early.json()["error"]["code"] == "MESSAGE_NOT_LATEST"

    async def test_agent_messages_not_editable(self, client, db_session) -> None:
        from app.models import ConversationMessage

        await _seed_user(client, db_session)
        conversation_id = (await client.post("/api/v1/conversations", json={})).json()["id"]
        agent_msg = ConversationMessage(
            conversation_id=UUID(conversation_id),
            workspace_id=(
                (await db_session.execute(select(Workspace))).scalars().first()
            ).id,
            role=ConversationRole.AGENT.value,
            content="Run COMPLETED.",
        )
        db_session.add(agent_msg)
        await db_session.flush()

        r = await client.patch(
            f"/api/v1/conversations/{conversation_id}/messages/{agent_msg.id}",
            json={"content": "forged"},
        )
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "MESSAGE_NOT_EDITABLE"


# ---------------------------------------------------------------------------
# Run→conversation bridge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRunOutcomeBridge:
    async def test_completed_run_posts_factual_summary_once(self, client, db_session) -> None:
        from app.models import AcademicWorkPlan, AgentRun, ConversationMessage
        from app.modules.conversations import service as conversation_service

        _user_id, workspace_id, _email = await _seed_user(client, db_session)
        assignment_id = await _seed_assignment(db_session, workspace_id)
        created = await client.post(
            "/api/v1/conversations",
            json={"title": "bound", "assignment_id": str(assignment_id)},
        )
        assert created.status_code == 201, created.text

        plan = AcademicWorkPlan(
            assignment_id=assignment_id,
            version=1,
            title="Plan",
            payload={"tasks": []},
            status="APPROVED",
        )
        db_session.add(plan)
        await db_session.flush()
        run = AgentRun(
            assignment_id=assignment_id,
            plan_id=plan.id,
            plan_version=1,
            status="COMPLETED",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(run)
        await db_session.flush()

        await conversation_service.record_run_outcome(db_session, run)
        await db_session.flush()

        msgs = (
            await db_session.execute(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == UUID(created.json()["id"]))
                .order_by(ConversationMessage.id)
            )
        ).scalars().all()
        summaries = [m for m in msgs if m.kind == "RUN_SUMMARY"]
        assert len(summaries) == 1
        assert summaries[0].role == "AGENT"
        assert "COMPLETED" in summaries[0].content
        assert summaries[0].metadata_json["run_id"] == str(run.id)

        # A replayed terminal transition must not duplicate the message.
        await conversation_service.record_run_outcome(db_session, run)
        await db_session.flush()
        summaries_again = [
            m
            for m in (
                await db_session.execute(
                    select(ConversationMessage).where(
                        ConversationMessage.conversation_id == UUID(created.json()["id"])
                    )
                )
            ).scalars()
            if m.kind == "RUN_SUMMARY"
        ]
        assert len(summaries_again) == 1

        # The sidebar preview reflects the latest message.
        detail = (await client.get(f"/api/v1/conversations/{created.json()['id']}")).json()
        assert detail["last_message_at"] is not None


# ---------------------------------------------------------------------------
# SSE stream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRunEventStream:
    async def _run_with_events(self, client, db_session):
        from app.models import AgentEvent, AgentRun

        _user_id, workspace_id, _email = await _seed_user(client, db_session)
        assignment_id = await _seed_assignment(db_session, workspace_id)
        run = AgentRun(
            assignment_id=assignment_id,
            status="RUNNING",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(run)
        await db_session.flush()
        db_session.add(
            AgentEvent(
                run_id=run.id,
                sequence=1,
                event_type="RUN_STARTED",
                summary="Run started.",
                workspace_id=workspace_id,
                assignment_id=assignment_id,
                user_id=UUID(_user_id),
            )
        )
        db_session.add(
            AgentEvent(
                run_id=run.id,
                sequence=2,
                event_type="TASK_COMPLETED",
                summary="Task one done.",
                workspace_id=workspace_id,
                assignment_id=assignment_id,
                user_id=UUID(_user_id),
            )
        )
        await db_session.flush()
        return run.id

    async def test_stream_emits_persisted_events_and_terminates(
        self, client, db_session, monkeypatch
    ) -> None:
        from app.models import AgentRun
        from app.modules.observability import streaming

        monkeypatch.setattr(streaming, "EVENT_POLL_SECONDS", 0.05)
        run_id = await self._run_with_events(client, db_session)

        # The run starts terminal on the next write; flip it so the stream
        # drains and ends instead of polling forever.
        run = await db_session.get(AgentRun, run_id)
        run.status = "COMPLETED"
        await db_session.flush()

        chunks: list[str] = []
        async with client.stream(
            "GET", f"/api/v1/assignments/{run.assignment_id}/agent/runs/{run_id}/events/stream"
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            async for chunk in response.aiter_text():
                chunks.append(chunk)
                if "event: done" in chunk:
                    break
        body = "".join(chunks)
        assert "RUN_STARTED" in body
        assert "Task one done." in body
        # id: lines carry the run-local sequence for Last-Event-ID resume.
        assert "id: 1" in body and "id: 2" in body
        # The terminal status frame precedes done.
        assert '"status": "COMPLETED"' in body or '"status":"COMPLETED"' in body

    async def test_stream_resumes_from_last_event_id(
        self, client, db_session, monkeypatch
    ) -> None:
        from app.models import AgentRun
        from app.modules.observability import streaming

        monkeypatch.setattr(streaming, "EVENT_POLL_SECONDS", 0.05)
        run_id = await self._run_with_events(client, db_session)
        run = await db_session.get(AgentRun, run_id)
        run.status = "COMPLETED"
        await db_session.flush()

        # A client reconnecting after event 1 must NOT receive event 1 again.
        chunks: list[str] = []
        async with client.stream(
            "GET",
            f"/api/v1/assignments/{run.assignment_id}/agent/runs/{run_id}/events/stream",
            headers={"Last-Event-ID": "1"},
        ) as response:
            async for chunk in response.aiter_text():
                chunks.append(chunk)
                if "event: done" in chunk:
                    break
        body = "".join(chunks)
        assert "id: 2" in body
        assert "RUN_STARTED" not in body

    async def test_stream_of_foreign_run_is_404(self, client, db_session) -> None:
        from app.models import AgentRun

        _first_id, workspace_id, first_email = await _seed_user(client, db_session)
        await _seed_assignment(db_session, workspace_id)
        other_workspace_user, _, _ = await _seed_user(client, db_session)
        other_ws = (
            await db_session.execute(
                select(Workspace).where(Workspace.owner_id == UUID(other_workspace_user))
            )
        ).scalars().first()
        foreign_course = Course(
            workspace_id=other_ws.id, code=f"CS{uuid4().hex[:4]}", name="Foreign"
        )
        db_session.add(foreign_course)
        await db_session.flush()
        foreign_assignment = Assignment(
            workspace_id=other_ws.id,
            course_id=foreign_course.id,
            title="foreign",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(foreign_assignment)
        await db_session.flush()
        foreign_run = AgentRun(
            assignment_id=foreign_assignment.id,
            status="RUNNING",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(foreign_run)
        await db_session.flush()

        # The client's cookie belongs to the *second* user (owner of the
        # foreign run); switch to the first user, who must see a 404.
        login = await client.post(
            "/api/v1/auth/login", json={"email": first_email, "password": "Password123!"}
        )
        assert login.status_code == 200, login.text

        response = await client.get(
            f"/api/v1/assignments/{foreign_assignment.id}/agent/runs/{foreign_run.id}/events/stream"
        )
        assert response.status_code == 404