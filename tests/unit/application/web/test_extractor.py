"""HTML extraction and structure-preservation tests."""

from app.application.web.extractor import extract_html
from tests.fixtures.web.html_samples import MALFORMED_HTML, MALICIOUS_HTML, SIMPLE_HTML


def test_extract_preserves_headings_lists_tables_and_code() -> None:
    extracted = extract_html(SIMPLE_HTML)
    assert extracted.title == "Example Guide"
    assert "# Example Guide" in extracted.markdown or "## Setup" in extracted.markdown
    assert "## Setup" in extracted.markdown
    assert "- First item" in extracted.markdown
    assert "```text" in extracted.markdown
    assert "print(" in extracted.markdown
    assert "| column | value |" in extracted.markdown or "column" in extracted.markdown
    assert "the docs" in extracted.markdown
    assert "https://example.com/docs" in extracted.markdown


def test_extract_strips_script_and_style() -> None:
    extracted = extract_html(MALICIOUS_HTML)
    assert "document.cookie" not in extracted.markdown
    assert "alert" not in extracted.markdown
    assert "Safe paragraph about Python dataclasses." in extracted.markdown


def test_extract_malformed_html_does_not_crash() -> None:
    extracted = extract_html(MALFORMED_HTML)
    assert "Hello" in extracted.markdown or "Still recoverable" in extracted.markdown
    assert "Two" in extracted.markdown
