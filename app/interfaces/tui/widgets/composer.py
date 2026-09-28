"""Multiline composer. Enter sends; Shift+Enter inserts a newline."""

from __future__ import annotations

from textual.binding import Binding
from textual.widgets import TextArea

from app.interfaces.tui.messages import ComposerSubmitted


class Composer(TextArea):
    BINDINGS = [
        Binding("enter", "submit", "Send", priority=True),
        Binding("shift+enter", "newline", "New line", priority=True),
    ]

    def __init__(self) -> None:
        super().__init__("", id="composer", soft_wrap=True)
        self.placeholder = "Type a message..."

    def action_newline(self) -> None:
        self.insert("\n")

    def action_submit(self) -> None:
        text = self.text
        self.post_message(ComposerSubmitted(text))

    def clear_text(self) -> None:
        self.load_text("")
