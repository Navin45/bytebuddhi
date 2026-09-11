"""Normalize extracted web content without flattening useful structure."""

import re

_MULTI_BLANK = re.compile(r"\n{3,}")
_TRAILING_WS = re.compile(r"[ \t]+\n")


def normalize_extracted_markdown(title: str, markdown: str, max_chars: int) -> str:
    """Preserve headings, lists, tables, and code fences while bounding size.

    Does not strip technical structure. Applies whitespace cleanup and a hard
    character limit so model context cannot grow without bound.
    """
    body = markdown.replace("\x00", "")
    body = _TRAILING_WS.sub("\n", body)
    body = _MULTI_BLANK.sub("\n\n", body).strip()
    if title:
        heading = f"# {title.strip()}"
        if not body.startswith("#"):
            body = f"{heading}\n\n{body}" if body else heading
    if len(body) > max_chars:
        body = body[:max_chars].rstrip() + "\n\n[Content truncated at extraction limit]"
    return body
