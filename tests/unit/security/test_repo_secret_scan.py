"""Lightweight scan of application and docs for committed credential material."""

from pathlib import Path

ROOTS = (Path("app"), Path("docs"), Path("vscode-extension/src"), Path(".github"))
NEEDLES = (
    "BEGIN " + "RSA PRIVATE KEY",
    "BEGIN " + "OPENSSH PRIVATE KEY",
)


def test_no_private_keys_in_application_sources() -> None:
    hits: list[str] = []
    for root in ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".ts", ".md", ".yml", ".yaml", ".json"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for token in NEEDLES:
                if token in text:
                    hits.append(f"{path}: {token}")
    assert hits == []
