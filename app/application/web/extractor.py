"""Structure-preserving HTML extraction using the standard library html.parser.

Limitations:
- Heuristic main-content selection is not perfect for every site layout.
- Heavily scripted pages may yield little text until a renderer is used.
- Nested tables and complex widgets are simplified.
- Tracking pixels and some boilerplate may still remain.
"""

from __future__ import annotations

from html.parser import HTMLParser

from app.application.web.models import ExtractedContent, ExtractionMethod

_SKIP_TAGS = frozenset(
    {
        "script",
        "style",
        "noscript",
        "iframe",
        "object",
        "embed",
        "svg",
        "canvas",
        "template",
        "link",
        "meta",
        "head",
        "button",
        "input",
        "select",
        "textarea",
        "form",
        "nav",
        "footer",
        "aside",
        "header",
        "advertisement",
    }
)

_HEADING_TAGS = {"h1": "#", "h2": "##", "h3": "###", "h4": "####", "h5": "#####", "h6": "######"}
_BLOCK_TAGS = frozenset({"p", "div", "section", "article", "main", "blockquote", "pre", "li", "br", "hr", "tr"})


class _Node:
    __slots__ = ("attrs", "children", "parent", "tag", "text")

    def __init__(self, tag: str, attrs: dict[str, str], parent: _Node | None) -> None:
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children: list[_Node] = []
        self.text = ""


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("document", {}, None)
        self._current = self.root
        self._skip_depth = 0
        self.title = ""
        self._in_title = False
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        if tag == "title" and self._skip_depth == 0:
            self._in_title = True
        if self._skip_depth or tag in _SKIP_TAGS:
            if tag in _SKIP_TAGS:
                self._skip_depth += 1
            return
        child = _Node(tag, attr_map, self._current)
        self._current.children.append(child)
        self._current = child

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
            if not self.title:
                self.title = "".join(self._title_parts).strip()
        if self._skip_depth:
            if tag in _SKIP_TAGS:
                self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._current.parent is not None and self._current.tag == tag:
            self._current = self._current.parent
            return
        cursor = self._current
        while cursor.parent is not None:
            if cursor.tag == tag:
                self._current = cursor.parent
                return
            cursor = cursor.parent

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        if self._skip_depth:
            return
        self._current.text += data

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self._skip_depth or tag in _SKIP_TAGS:
            return
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        self._current.children.append(_Node(tag, attr_map, self._current))


def extract_html(html: str, content_type: str = "text/html") -> ExtractedContent:
    """Extract structure-preserving markdown from HTML."""
    builder = _TreeBuilder()
    try:
        builder.feed(html)
        builder.close()
    except Exception:
        text = _fallback_text(html)
        return ExtractedContent(
            title="",
            markdown=text,
            method=ExtractionMethod.HTTP,
            content_type=content_type,
        )

    root = _select_main(builder.root)
    markdown = _render_markdown(root).strip()
    title = builder.title.strip()
    if not title:
        title = _first_heading(root) or ""
    return ExtractedContent(
        title=title,
        markdown=markdown,
        method=ExtractionMethod.HTTP,
        content_type=content_type,
    )


def extract_plain_text(text: str, content_type: str, method: ExtractionMethod) -> ExtractedContent:
    """Treat a textual payload as already-extracted content."""
    cleaned = text.replace("\x00", "")
    title = cleaned.strip().splitlines()[0][:120] if cleaned.strip() else ""
    return ExtractedContent(title=title, markdown=cleaned.strip(), method=method, content_type=content_type)


def _select_main(root: _Node) -> _Node:
    candidates: list[_Node] = []

    def walk(node: _Node) -> None:
        if node.tag in {"article", "main"}:
            candidates.append(node)
        for child in node.children:
            walk(child)

    walk(root)
    if candidates:
        return max(candidates, key=_text_len)
    body = _find_tag(root, "body")
    return body or root


def _find_tag(node: _Node, tag: str) -> _Node | None:
    if node.tag == tag:
        return node
    for child in node.children:
        found = _find_tag(child, tag)
        if found is not None:
            return found
    return None


def _text_len(node: _Node) -> int:
    total = len(node.text.strip())
    for child in node.children:
        total += _text_len(child)
    return total


def _first_heading(node: _Node) -> str:
    if node.tag in _HEADING_TAGS:
        return _collect_text(node).strip()
    for child in node.children:
        heading = _first_heading(child)
        if heading:
            return heading
    return ""


def _collect_text(node: _Node) -> str:
    parts = [node.text]
    for child in node.children:
        parts.append(_collect_text(child))
    return " ".join(part for part in parts if part)


def _render_markdown(node: _Node) -> str:
    tag = node.tag
    if tag in _HEADING_TAGS:
        text = _inline(node).strip()
        return f"\n{_HEADING_TAGS[tag]} {text}\n" if text else ""
    if tag == "p":
        text = _inline(node).strip()
        return f"\n{text}\n" if text else ""
    if tag == "br":
        return "\n"
    if tag == "hr":
        return "\n---\n"
    if tag == "blockquote":
        inner = _render_markdown_children(node).strip()
        quoted = "\n".join(f"> {line}" if line else ">" for line in inner.splitlines())
        return f"\n{quoted}\n" if quoted else ""
    if tag in {"pre", "code"} and (tag == "pre" or (node.parent and node.parent.tag == "pre")):
        code = _collect_text(node).strip("\n")
        if tag == "pre":
            return f"\n```text\n{code}\n```\n" if code else ""
        if node.parent and node.parent.tag != "pre":
            return f"`{code}`" if code else ""
        return code
    if tag == "code":
        code = _collect_text(node).strip()
        return f"`{code}`" if code else ""
    if tag == "li":
        text = _inline(node).strip()
        return f"- {text}" if text else ""
    if tag in {"ul", "ol"}:
        items = []
        for child in node.children:
            if child.tag == "li":
                rendered = _render_markdown(child).strip()
                if rendered:
                    items.append(rendered)
        return ("\n" + "\n".join(items) + "\n") if items else ""
    if tag == "table":
        return _render_table(node)
    if tag == "a":
        text = _collapse_ws(node.text + _inline_children(node)).strip() or node.attrs.get("href", "")
        href = node.attrs.get("href", "")
        if href and text:
            return f"[{text}]({href})"
        return text
    if tag in {"strong", "b"}:
        inner = _inline(node).strip()
        return f"**{inner}**" if inner else ""
    if tag in {"em", "i"}:
        inner = _inline(node).strip()
        return f"*{inner}*" if inner else ""
    return _render_markdown_children(node)


def _render_markdown_children(node: _Node) -> str:
    chunks = [_render_markdown(child) for child in node.children]
    text = node.text + "".join(chunks)
    return text


def _inline(node: _Node) -> str:
    return _collapse_ws(node.text + _inline_children(node))


def _inline_children(node: _Node) -> str:
    parts: list[str] = []
    for child in node.children:
        parts.append(
            _render_markdown(child) if child.tag in {"a", "code", "strong", "b", "em", "i"} else _inline(child)
        )
    return "".join(parts)


def _collapse_ws(text: str) -> str:
    return " ".join(text.split())


def _render_table(node: _Node) -> str:
    rows: list[list[str]] = []

    def walk_rows(current: _Node) -> None:
        if current.tag == "tr":
            cells = [_collapse_ws(_collect_text(cell)) for cell in current.children if cell.tag in {"td", "th"}]
            if cells:
                rows.append(cells)
            return
        for child in current.children:
            walk_rows(child)

    walk_rows(node)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    header = normalized[0]
    body = normalized[1:] if len(normalized) > 1 else []
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(row) + " |")
    return "\n" + "\n".join(lines) + "\n"


def _fallback_text(html: str) -> str:
    stripped: list[str] = []
    skipping = 0
    i = 0
    lower = html.lower()
    while i < len(html):
        if lower.startswith("<script", i) or lower.startswith("<style", i):
            skipping += 1
            gt = html.find(">", i)
            i = gt + 1 if gt != -1 else len(html)
            continue
        if lower.startswith("</script", i) or lower.startswith("</style", i):
            skipping = max(0, skipping - 1)
            gt = html.find(">", i)
            i = gt + 1 if gt != -1 else len(html)
            continue
        if html[i] == "<":
            gt = html.find(">", i)
            i = gt + 1 if gt != -1 else len(html)
            continue
        if skipping == 0:
            stripped.append(html[i])
        i += 1
    return _collapse_ws("".join(stripped))
