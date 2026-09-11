"""Content normalization and bounding tests."""

from app.application.web.content_normalizer import normalize_extracted_markdown


def test_normalize_prepends_title_and_collapses_blank_lines() -> None:
    text = normalize_extracted_markdown("Title", "Para one.\n\n\n\nPara two.", 1000)
    assert text.startswith("# Title")
    assert "\n\n\n" not in text
    assert "Para one." in text


def test_normalize_bounds_characters() -> None:
    body = "x" * 500
    text = normalize_extracted_markdown("T", body, 50)
    assert len(text) < 120
    assert "truncated" in text.lower()
