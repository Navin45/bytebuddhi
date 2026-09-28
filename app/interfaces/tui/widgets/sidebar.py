"""Projects and conversations loaded from the gateway."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Label, ListItem, ListView

from app.interfaces.tui.messages import NewConversationRequested
from app.interfaces.tui.state import TuiState


class Sidebar(Vertical):
    def compose(self) -> ComposeResult:
        yield Label("Projects")
        yield ListView(id="projects")
        yield Label("Conversations")
        yield ListView(id="conversations")
        yield Button("New conversation", id="new-conversation")

    async def show(self, state: TuiState) -> None:
        await self._fill(
            "#projects",
            [(f"project-{item.id}", _mark(item.id == state.active_project_id, item.name)) for item in state.projects]
            or [("", "No projects")],
        )
        conversations = state.visible_conversations()
        await self._fill(
            "#conversations",
            [
                (
                    f"conversation-{item.id}",
                    _mark(item.id == state.active_conversation_id, f"{item.title}  {item.updated_at}"),
                )
                for item in conversations
            ]
            or [("", "No conversations")],
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "new-conversation":
            self.post_message(NewConversationRequested())

    async def _fill(self, view_id: str, rows: list[tuple[str, str]]) -> None:
        view = self.query_one(view_id, ListView)
        wanted = [item_id for item_id, _label in rows]
        current = [str(child.id or "") for child in view.children]
        if current == wanted and all(wanted):
            for child, (_item_id, label) in zip(view.children, rows, strict=True):
                child.query_one(Label).update(label)
            return
        await view.clear()
        for item_id, label in rows:
            if item_id:
                view.append(ListItem(Label(label), id=item_id))
            else:
                view.append(ListItem(Label(label)))


def _mark(selected: bool, label: str) -> str:
    return f"> {label}" if selected else f"  {label}"
