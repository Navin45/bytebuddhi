"""Textual messages posted by TUI widgets."""

from __future__ import annotations

from textual.message import Message


class ComposerSubmitted(Message):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class NewConversationRequested(Message):
    pass
