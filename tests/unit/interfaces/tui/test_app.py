"""Textual pilot coverage for chat state, one run, cancel, and shutdown."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from textual.widgets import Markdown

from app.interfaces.api.schemas.chat_schema import ConversationResponse, MessageResponse
from app.interfaces.api.schemas.run_schema import RunCreateResponse, RunEventPage
from app.interfaces.gateway.errors import AuthenticationRequired, GatewayUnavailable
from app.interfaces.tui.app import ByteBuddhiApp
from app.interfaces.tui.screens import ErrorScreen, HelpScreen
from app.interfaces.tui.session import LoadedWorkspace
from app.interfaces.tui.state import ConversationRef, ModelRef, ProjectRef
from app.interfaces.tui.widgets.composer import Composer
from app.interfaces.tui.widgets.status_bar import StatusBar
from app.interfaces.tui.widgets.transcript import ToolActivity

_NOW = datetime(2026, 9, 25, tzinfo=UTC)


def _event(sequence: int, event_type: str, data: dict | None = None, run_id: str = "run_1") -> dict:
    return {
        "event_id": f"evt-{sequence}",
        "run_id": run_id,
        "sequence": sequence,
        "type": event_type,
        "schema_version": 1,
        "created_at": "2026-09-25T00:00:00+00:00",
        "data": data or {},
    }


class _Session:
    def __init__(self, workspace: LoadedWorkspace | None = None) -> None:
        self.workspace = workspace or LoadedWorkspace((), (), (), "", "")
        self.messages: dict[str, list[MessageResponse]] = {}
        self.runs: list[dict] = []
        self.cancelled: list[str] = []
        self.closed = 0
        self.release = asyncio.Event()
        self.started = asyncio.Event()
        self.block_stream = False
        self.load_error: Exception | None = None

    async def load(self) -> LoadedWorkspace:
        if self.load_error is not None:
            raise self.load_error
        return self.workspace

    async def list_messages(self, conversation_id: str) -> list[MessageResponse]:
        return list(self.messages.get(conversation_id, []))

    async def create_conversation(self, *, project_id: str | None, title: str) -> ConversationResponse:
        return ConversationResponse(
            id=uuid4(),
            user_id=uuid4(),
            project_id=None,
            title=title,
            is_archived=False,
            created_at=_NOW,
            updated_at=_NOW,
        )

    async def create_run(self, **kwargs: object) -> RunCreateResponse:
        self.runs.append(dict(kwargs))
        conversation_id = kwargs.get("conversation_id")
        return RunCreateResponse(
            run_id="run_1",
            conversation_id=str(conversation_id) if conversation_id else None,
            status="queued",
        )

    async def cancel_run(self, run_id: str) -> None:
        self.cancelled.append(run_id)

    async def aclose(self) -> None:
        self.closed += 1

    async def read_run_socket(self, run_id: str, *, after_sequence: int = 0):
        self.started.set()
        if self.block_stream:
            await self.release.wait()
        if after_sequence < 1:
            yield _event(1, "run_completed", run_id=run_id)

    async def get_run_events(self, run_id: str, *, after_sequence: int = 0, limit: int = 200) -> RunEventPage:
        return RunEventPage(events=[], next_sequence=after_sequence, has_more=False)


def _workspace() -> LoadedWorkspace:
    return LoadedWorkspace(
        projects=(ProjectRef("p1", "bytebuddhi"), ProjectRef("p2", "demo")),
        conversations=(
            ConversationRef("c1", "Repository audit", "p1", "09-25 10:00"),
            ConversationRef("c2", "Research FastAPI", "p2", "09-25 09:00"),
        ),
        models=(ModelRef("openai", "gpt-test", "Test model"),),
        default_provider="openai",
        default_model="gpt-test",
    )


def _message(role: str, content: str) -> MessageResponse:
    return MessageResponse(
        id=uuid4(),
        conversation_id=uuid4(),
        role=role,
        content=content,
        created_at=_NOW,
    )


@pytest.mark.asyncio
async def test_startup_renders_history_for_the_selected_project() -> None:
    session = _Session(_workspace())
    session.messages["c1"] = [_message("user", "Analyze the authentication flow.")]
    app = ByteBuddhiApp(session, project_id="p1")
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert app.state.active_project_id == "p1"
        assert app.state.active_conversation_id == "c1"
        assert app.state.transcript[0].body == "Analyze the authentication flow."
        assert "CONNECTED" in str(app.query_one(StatusBar).render())
        assert "Repository audit" in str(app.query_one("#conversation-c1 Label").render())
        assert app.query_one("#sidebar").display is True


@pytest.mark.asyncio
async def test_empty_workspace_and_narrow_terminal() -> None:
    app = ByteBuddhiApp(_Session())
    async with app.run_test(size=(40, 12)) as pilot:
        await pilot.pause()
        assert "No conversations" in str(app.query_one("#conversations Label").render())
        assert app.query_one("#sidebar").display is False
        assert "server default" in str(app.query_one(StatusBar).render())


@pytest.mark.asyncio
async def test_auth_failure_is_a_dialog() -> None:
    session = _Session()
    session.load_error = AuthenticationRequired("expired")
    app = ByteBuddhiApp(session)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, ErrorScreen)
        assert "bytebuddhi login" in app.screen._message


@pytest.mark.asyncio
async def test_streamed_deltas_update_one_markdown_message() -> None:
    app = ByteBuddhiApp(_Session())
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await app._on_event(_event(1, "run_queued"))
        await app._on_event(_event(2, "run_started"))
        await app._on_event(_event(3, "assistant_delta", {"delta": "Hello"}))
        await app._on_event(_event(4, "assistant_delta", {"delta": " world"}))
        await pilot.pause()
        markdowns = list(app.query(Markdown))
        assert len(markdowns) == 1
        assert markdowns[0].source == "Hello world"
        await app._on_event(_event(5, "run_completed"))
        await pilot.pause()
        assert app.state.run_status == "completed"
        assert app.query_one(Composer).disabled is False


@pytest.mark.asyncio
async def test_tool_activity_updates_one_collapsible() -> None:
    app = ByteBuddhiApp(_Session())
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await app._on_event(_event(1, "tool_started", {"tool_name": "filesystem.search"}))
        await app._on_event(_event(2, "tool_completed", {"tool_name": "filesystem.search", "artifact_id": "art_1"}))
        await pilot.pause()
        tool = app.query_one("#tool-run_1-1", ToolActivity)
        assert tool.title == "[tool] filesystem.search"
        assert "completed" in str(tool._body.render())
        assert len(app.query(ToolActivity)) == 1


@pytest.mark.asyncio
async def test_enter_creates_one_run_and_a_second_enter_does_not() -> None:
    session = _Session(_workspace())
    session.block_stream = True
    app = ByteBuddhiApp(session, project_id="p1")
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        composer = app.query_one(Composer)
        composer.load_text("Say hello in one sentence.")
        await pilot.press("enter")
        await asyncio.wait_for(session.started.wait(), timeout=2)
        composer.load_text("Say it again.")
        await pilot.press("enter")
        await pilot.pause()
        assert len(session.runs) == 1
        assert session.runs[0]["prompt"] == "Say hello in one sentence."
        assert app.state.active_run_id == "run_1"
        assert composer.text == "Say it again."
        session.release.set()
        await pilot.pause()


@pytest.mark.asyncio
async def test_escape_cancels_once_and_waits_for_the_terminal_event() -> None:
    session = _Session()
    app = ByteBuddhiApp(session)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await app._on_event(_event(1, "run_started"))
        await pilot.pause()
        assert app.query_one(Composer).disabled is True
        await pilot.press("escape")
        await pilot.press("escape")
        await pilot.pause()
        assert session.cancelled == ["run_1"]
        assert app.state.run_status == "running"
        await app._on_event(_event(2, "run_cancelled"))
        await pilot.pause()
        assert app.state.run_status == "cancelled"
        assert app.query_one(Composer).disabled is False
        assert "CANCELLED" in str(app.query_one(StatusBar).render())


@pytest.mark.asyncio
async def test_closing_the_app_does_not_cancel_the_run() -> None:
    session = _Session()
    app = ByteBuddhiApp(session)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await app._on_event(_event(1, "run_started"))
        await pilot.pause()
        app.exit()
        await pilot.pause()
    assert session.cancelled == []
    assert session.closed == 1


@pytest.mark.asyncio
async def test_reconnect_and_interrupted_status_are_words() -> None:
    app = ByteBuddhiApp(_Session())
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await app._on_status("reconnecting", 2)
        await pilot.pause()
        assert "RECONNECTING 2/3" in str(app.query_one(StatusBar).render())
        await app._on_event(_event(1, "run_interrupted", {"error_message": "worker stopped"}))
        await pilot.pause()
        rendered = str(app.query_one(StatusBar).render())
        assert "INTERRUPTED" in rendered
        assert "worker stopped" in str(app.query_one("#notice-run_1-interrupted").render())
        assert app.query_one(Composer).disabled is False


@pytest.mark.asyncio
async def test_project_switch_is_blocked_while_a_run_is_active() -> None:
    session = _Session(_workspace())
    app = ByteBuddhiApp(session, project_id="p1")
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await app._on_event(_event(1, "run_started"))
        await pilot.pause()
        app._select_project("p2")
        await pilot.pause()
        assert app.state.active_project_id == "p1"
        assert isinstance(app.screen, ErrorScreen)


@pytest.mark.asyncio
async def test_project_switch_loads_that_projects_conversation() -> None:
    session = _Session(_workspace())
    session.messages["c2"] = [_message("assistant", "FastAPI routes live in interfaces.")]
    app = ByteBuddhiApp(session, project_id="p1")
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app._select_project("p2")
        await pilot.pause()
        assert app.state.active_project_id == "p2"
        assert app.state.active_conversation_id == "c2"
        assert app.query(Markdown).first().source == "FastAPI routes live in interfaces."


@pytest.mark.asyncio
async def test_slash_help_does_not_create_a_run() -> None:
    session = _Session(_workspace())
    app = ByteBuddhiApp(session, project_id="p1")
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        composer = app.query_one(Composer)
        composer.load_text("/help")
        composer.action_submit()
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        assert session.runs == []


@pytest.mark.asyncio
async def test_gateway_unavailable_uses_the_error_dialog() -> None:
    session = _Session(_workspace())
    app = ByteBuddhiApp(session, project_id="p1")

    async def fail_create(**_kwargs: object) -> RunCreateResponse:
        raise GatewayUnavailable("down")

    session.create_run = fail_create  # type: ignore[method-assign]
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        composer = app.query_one(Composer)
        composer.load_text("hello")
        composer.action_submit()
        await pilot.pause()
        assert isinstance(app.screen, ErrorScreen)
        assert "Cannot connect" in app.screen._message
        assert session.runs == []
        assert app.query_one(Composer).disabled is False
