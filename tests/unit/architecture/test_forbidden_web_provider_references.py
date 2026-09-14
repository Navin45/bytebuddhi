"""Regression: forbidden third-party search SDK must not re-enter the runtime."""

from pathlib import Path

_SCAN_ROOTS = [
    Path("app"),
    Path("pyproject.toml"),
    Path(".env.example"),
    Path("docker-compose.yml"),
    Path("tests"),
]

_SKIP_NAMES = {
    "test_forbidden_web_provider_references.py",
}

# Split tokens so this file is not a self-match if scanned by accident.
_FORBIDDEN_TOKENS = (
    "tav" + "ily",
    "TAV" + "ILY",
    "Tav" + "ilyClient",
    "Tav" + "ilySearchService",
    "tav" + "ily-python",
    "tav" + "ily_search",
    "TAV" + "ILY_API_KEY",
)


def _should_skip(path: Path) -> bool:
    if path.name in _SKIP_NAMES:
        return True
    allowed = {".py", ".toml", ".txt", ".yml", ".yaml", ".example", ".md", ".ini", ".cfg", ".env"}
    named = {"pyproject.toml", ".env.example", "docker-compose.yml"}
    return path.suffix not in allowed and path.name not in named


def test_forbidden_search_sdk_absent_from_executable_and_config() -> None:
    hits: list[str] = []
    files: list[Path] = []
    for root in _SCAN_ROOTS:
        if root.is_file():
            files.append(root)
            continue
        if root.is_dir():
            files.extend(p for p in root.rglob("*") if p.is_file())
    for path in files:
        if _should_skip(path):
            continue
        if path.suffix in {".pyc", ".png", ".jpg", ".lock"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        lowered = text.lower()
        for token in _FORBIDDEN_TOKENS:
            if token.lower() in lowered:
                hits.append(f"{path}: matched forbidden token")
                break
    assert not hits, "Forbidden search-provider references remain:\n" + "\n".join(hits)
