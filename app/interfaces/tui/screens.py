"""Modal screens for help, errors, and pickers."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, ListItem, ListView, Static


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "close", "Close"), Binding("enter", "close", "Close")]

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("ByteBuddhi help"),
            Static(
                "\n".join(
                    [
                        "Enter          send the composer",
                        "Shift+Enter    insert a newline",
                        "Esc            cancel the active run",
                        "?              this help",
                        "Ctrl+Q         quit without cancelling the run",
                        "/help          this help",
                        "/new           start a conversation",
                        "/projects      choose a project",
                        "/models        choose a model",
                        "/clear         reload history from the server",
                        "/quit          quit without cancelling the run",
                        "",
                        "Closing the TUI disconnects this client.",
                        "The run keeps going on the gateway.",
                        "A reconnect continues the same run.",
                    ]
                )
            ),
            id="help-body",
        )

    def action_close(self) -> None:
        self.dismiss(None)


class ErrorScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "close", "Close"), Binding("enter", "close", "Close")]

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        yield Vertical(Label("ByteBuddhi"), Static(self._message), id="error-body")

    def action_close(self) -> None:
        self.dismiss(None)


class PickerScreen(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(self, title: str, options: list[tuple[str, str]]) -> None:
        super().__init__()
        self._title = title
        self._options = options

    def compose(self) -> ComposeResult:
        items = [ListItem(Label(label), id=item_id) for item_id, label in self._options]
        yield Vertical(Label(self._title), ListView(*items, id="picker"), id="picker-body")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()
        if event.item.id:
            self.dismiss(str(event.item.id))

    def action_close(self) -> None:
        self.dismiss(None)
