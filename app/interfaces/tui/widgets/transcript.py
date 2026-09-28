"""Message transcript. One widget per logical message, updated in place."""

from __future__ import annotations

from textual.containers import VerticalScroll
from textual.widgets import Collapsible, Markdown, Static

from app.interfaces.tui.state import TranscriptItem


class Transcript(VerticalScroll):
    def show(self, items: tuple[TranscriptItem, ...]) -> None:
        wanted = [item.item_id for item in items]
        current = [child.id or "" for child in self.children]
        if wanted[: len(current)] != current:
            self.remove_children()
            current = [child.id or "" for child in self.children]
        pending = [item for item in items[len(current) :] if (item.item_id or "") not in set(current)]
        if pending:
            self.mount(*[_widget(item) for item in pending])
        by_id = {child.id: child for child in self.children}
        for item in items:
            child = by_id.get(item.item_id)
            if child is not None:
                _update(child, item)
        self.scroll_end(animate=False)


class ToolActivity(Collapsible):
    """One tool row. The body widget is updated in place."""

    def __init__(self, item: TranscriptItem) -> None:
        self._body = Static(_tool_text(item))
        super().__init__(self._body, title=item.title, collapsed=True, id=item.item_id)

    def apply(self, item: TranscriptItem) -> None:
        self.title = item.title
        self._body.update(_tool_text(item))


def _widget(item: TranscriptItem):
    if item.kind == "assistant":
        view = Markdown("", id=item.item_id)
        view.border_title = item.title
        view._initial_markdown = item.body
        return view
    if item.kind == "tool":
        return ToolActivity(item)
    return Static(_plain(item), id=item.item_id)


def _update(child, item: TranscriptItem) -> None:
    if item.kind == "assistant" and isinstance(child, Markdown):
        child.border_title = item.title
        if child.is_mounted and child._initial_markdown is None:
            child.update(item.body)
        else:
            child._initial_markdown = item.body
        return
    if item.kind == "tool" and isinstance(child, ToolActivity):
        child.apply(item)
        return
    if isinstance(child, Static):
        child.update(_plain(item))


def _plain(item: TranscriptItem) -> str:
    return f"{item.title}\n{item.body}"


def _tool_text(item: TranscriptItem) -> str:
    lines = [item.body]
    if item.detail:
        lines.append(item.detail)
    return "\n".join(lines)
