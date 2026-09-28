"""Textual application. UI state is a projection of gateway data."""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Header, ListView

from app.infrastructure.config.logger import get_logger
from app.interfaces.gateway.errors import GatewayError
from app.interfaces.tui.events import reduce_event
from app.interfaces.tui.messages import ComposerSubmitted, NewConversationRequested
from app.interfaces.tui.screens import ErrorScreen, HelpScreen, PickerScreen
from app.interfaces.tui.session import GatewaySession, history_items, human_error
from app.interfaces.tui.state import ConversationRef, TranscriptItem, TuiState, with_user_message
from app.interfaces.tui.stream import RunStreamController
from app.interfaces.tui.widgets.composer import Composer
from app.interfaces.tui.widgets.sidebar import Sidebar
from app.interfaces.tui.widgets.status_bar import StatusBar
from app.interfaces.tui.widgets.transcript import Transcript

logger = get_logger(__name__)


class ByteBuddhiApp(App[None]):
    """Gateway chat. Closing the app does not cancel the active run."""

    CSS_PATH = "app.tcss"
    TITLE = "ByteBuddhi"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("question_mark", "help", "Help"),
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("ctrl+q", "quit_app", "Quit"),
    ]

    def __init__(
        self,
        session: GatewaySession,
        *,
        project_id: str | None = None,
        controller: RunStreamController | None = None,
    ) -> None:
        super().__init__()
        self.session = session
        self.controller = controller or RunStreamController(session)
        self.state = TuiState(active_project_id=project_id)
        self._preferred_project = project_id

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="body"):
            yield Sidebar(id="sidebar")
            with Vertical(id="main"):
                yield Transcript(id="transcript")
                yield StatusBar(id="status")
                yield Composer()

    def on_mount(self) -> None:
        self.run_worker(self._bootstrap(), exclusive=True)

    async def on_unmount(self) -> None:
        self.controller.stop()
        await self.session.aclose()

    def on_resize(self) -> None:
        if not self._is_mounted:
            return
        self.query_one("#sidebar").display = self.size.width >= 72

    async def _bootstrap(self) -> None:
        try:
            loaded = await self.session.load()
        except GatewayError as exc:
            self._show_error(human_error(exc))
            await self._paint(replace(self.state, connection="disconnected"))
            return
        project_id = self._preferred_project
        if project_id is None and loaded.projects:
            project_id = loaded.projects[0].id
        state = replace(
            self.state,
            connection="connected",
            projects=loaded.projects,
            conversations=loaded.conversations,
            models=loaded.models,
            active_project_id=project_id,
        )
        visible = state.visible_conversations()
        conversation_id = visible[0].id if visible else None
        transcript: tuple[TranscriptItem, ...] = ()
        if conversation_id is not None:
            try:
                transcript = history_items(await self.session.list_messages(conversation_id))
            except GatewayError as exc:
                self._show_error(human_error(exc))
        await self._paint(
            replace(state, active_conversation_id=conversation_id, transcript=transcript),
            structure=True,
        )
        self.query_one(Composer).focus()

    async def on_composer_submitted(self, message: ComposerSubmitted) -> None:
        text = message.text.strip()
        if not text:
            if message.text:
                self.query_one(Composer).clear_text()
            return
        if text.startswith("/"):
            self.query_one(Composer).clear_text()
            self._command(text.split()[0].lower())
            return
        if self.state.run_active:
            return
        self.query_one(Composer).clear_text()
        await self._paint(with_user_message(self.state, text, item_id=f"user-{uuid4()}"))
        self.run_worker(self._send(text))

    def on_new_conversation_requested(self, _message: NewConversationRequested) -> None:
        if self.state.run_active:
            self._show_error("Wait for the current run to finish before starting a conversation.")
            return
        self.run_worker(self._new_conversation("New conversation"))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item_id = str(event.item.id or "")
        if item_id.startswith("project-"):
            self._select_project(item_id.removeprefix("project-"))
        elif item_id.startswith("conversation-"):
            self._select_conversation(item_id.removeprefix("conversation-"))

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    async def action_cancel(self) -> None:
        if isinstance(self.screen, ModalScreen):
            return
        if not self.state.run_active or not self.state.active_run_id or self.state.cancel_sent:
            return
        await self._paint(replace(self.state, cancel_sent=True))
        self.run_worker(self._cancel(self.state.active_run_id))

    def action_quit_app(self) -> None:
        self.exit()

    async def _send(self, text: str) -> None:
        try:
            conversation_id = await self._ensure_conversation(text)
            created = await self.session.create_run(
                prompt=text,
                project_id=self.state.active_project_id,
                conversation_id=conversation_id,
                model_provider=self.state.selected_provider,
                model_name=self.state.selected_model,
                idempotency_key=str(uuid4()),
            )
        except GatewayError as exc:
            await self._paint(replace(self.state, submitting=False))
            self._show_error(human_error(exc))
            return
        run_id = created.run_id
        logger.info("tui_run_created", run_id=run_id, status=created.status)
        await self._paint(
            replace(
                self.state,
                active_run_id=run_id,
                active_conversation_id=created.conversation_id or conversation_id,
                submitting=True,
                cancel_sent=False,
                last_sequence=0,
            )
        )
        await self.controller.follow(run_id, self._on_event, self._on_status)

    async def _ensure_conversation(self, text: str) -> str | None:
        if self.state.active_conversation_id:
            return self.state.active_conversation_id
        created = await self.session.create_conversation(
            project_id=self.state.active_project_id,
            title=text[:60] or "New conversation",
        )
        ref = ConversationRef(
            id=str(created.id),
            title=created.title or "New conversation",
            project_id=str(created.project_id) if created.project_id else None,
            updated_at=created.updated_at.strftime("%m-%d %H:%M"),
        )
        await self._paint(
            replace(
                self.state,
                conversations=(ref, *self.state.conversations),
                active_conversation_id=ref.id,
            ),
            structure=True,
        )
        return ref.id

    async def _new_conversation(self, title: str) -> None:
        try:
            created = await self.session.create_conversation(project_id=self.state.active_project_id, title=title)
        except GatewayError as exc:
            self._show_error(human_error(exc))
            return
        ref = ConversationRef(
            id=str(created.id),
            title=created.title or title,
            project_id=str(created.project_id) if created.project_id else None,
            updated_at=created.updated_at.strftime("%m-%d %H:%M"),
        )
        await self._paint(
            replace(
                self.state,
                conversations=(ref, *self.state.conversations),
                active_conversation_id=ref.id,
                transcript=(),
                active_run_id=None,
                run_status="idle",
                last_sequence=0,
            ),
            structure=True,
        )

    async def _cancel(self, run_id: str) -> None:
        try:
            await self.session.cancel_run(run_id)
        except GatewayError as exc:
            await self._paint(replace(self.state, cancel_sent=False))
            self._show_error(human_error(exc))

    async def _on_event(self, event: object) -> None:
        if isinstance(event, dict):
            await self._paint(reduce_event(self.state, event))

    async def _on_status(self, connection: str, attempt: int) -> None:
        await self._paint(replace(self.state, connection=connection, reconnect_attempt=attempt))

    def _command(self, command: str) -> None:
        if command == "/help":
            self.action_help()
        elif command == "/quit":
            self.exit()
        elif command == "/new":
            self.on_new_conversation_requested(NewConversationRequested())
        elif command == "/projects":
            options = [(f"project-{item.id}", item.name) for item in self.state.projects]
            self.push_screen(PickerScreen("Projects", options), self._chose_project)
        elif command == "/models":
            options = [(f"model-{index}", item.display_name) for index, item in enumerate(self.state.models)]
            self.push_screen(PickerScreen("Models", options), self._chose_model)
        elif command == "/clear":
            if self.state.active_conversation_id and not self.state.run_active:
                self.run_worker(self._reload_history(self.state.active_conversation_id))
        else:
            self._show_error(f"Unknown command {command}. Press ? for help.")

    def _chose_project(self, choice: str | None) -> None:
        if choice:
            self._select_project(choice.removeprefix("project-"))

    def _chose_model(self, choice: str | None) -> None:
        if choice is None or not choice.startswith("model-"):
            return
        index = int(choice.removeprefix("model-"))
        if index < 0 or index >= len(self.state.models):
            return
        chosen = self.state.models[index]
        self.run_worker(
            self._paint(replace(self.state, selected_provider=chosen.provider, selected_model=chosen.model))
        )

    def _select_project(self, project_id: str) -> None:
        if self.state.run_active:
            self._show_error("Wait for the current run to finish before changing projects.")
            return
        if project_id == self.state.active_project_id:
            return
        self.run_worker(self._switch_project(project_id))

    async def _switch_project(self, project_id: str) -> None:
        state = replace(
            self.state,
            active_project_id=project_id,
            active_conversation_id=None,
            transcript=(),
            active_run_id=None,
            run_status="idle",
            last_sequence=0,
        )
        visible = state.visible_conversations()
        conversation_id = visible[0].id if visible else None
        transcript: tuple[TranscriptItem, ...] = ()
        if conversation_id is not None:
            try:
                transcript = history_items(await self.session.list_messages(conversation_id))
            except GatewayError as exc:
                self._show_error(human_error(exc))
        await self._paint(
            replace(state, active_conversation_id=conversation_id, transcript=transcript),
            structure=True,
        )

    def _select_conversation(self, conversation_id: str) -> None:
        if self.state.run_active:
            self._show_error("Wait for the current run to finish before changing conversations.")
            return
        self.run_worker(self._reload_history(conversation_id))

    async def _reload_history(self, conversation_id: str) -> None:
        try:
            messages = await self.session.list_messages(conversation_id)
        except GatewayError as exc:
            self._show_error(human_error(exc))
            return
        await self._paint(
            replace(
                self.state,
                active_conversation_id=conversation_id,
                transcript=history_items(messages),
                active_run_id=None,
                run_status="idle",
                last_sequence=0,
            ),
            structure=True,
        )

    async def _paint(self, state: TuiState, *, structure: bool = False) -> None:
        previous = self.state
        self.state = state
        if not self._is_mounted:
            return
        self.query_one(Transcript).show(state.transcript)
        self.query_one(StatusBar).show(state)
        self.query_one(Composer).disabled = state.run_active
        self.query_one("#sidebar").display = self.size.width >= 72
        lists_changed = (
            structure
            or previous.projects != state.projects
            or previous.conversations != state.conversations
            or previous.active_project_id != state.active_project_id
            or previous.active_conversation_id != state.active_conversation_id
        )
        if lists_changed:
            await self.query_one(Sidebar).show(state)

    def _show_error(self, message: str) -> None:
        logger.warning("tui_error", status="error")
        if self._is_mounted:
            self.push_screen(ErrorScreen(message))
