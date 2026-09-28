"""Connection and run status. Words stay readable without color."""

from __future__ import annotations

from textual.widgets import Static

from app.interfaces.tui.state import TuiState, status_line


class StatusBar(Static):
    def show(self, state: TuiState) -> None:
        self.update(status_line(state))
