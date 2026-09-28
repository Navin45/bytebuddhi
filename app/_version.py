"""Single source of truth for version and protocol constants.

``APP_VERSION`` must always match ``pyproject.toml`` ``[project].version``.
Run ``scripts/sync_version.py`` after any bump to propagate the change to
``desktop/package.json`` and ``app/__init__.py``.

``PROTOCOL_VERSION`` tracks the run/event envelope independently.  Increment it
when the WebSocket framing, event field semantics, or REST contract changes in
a way that older clients cannot interpret.  Application version increases that
do not alter the protocol keep ``PROTOCOL_VERSION`` unchanged.
"""

from __future__ import annotations

# ── Application version ──────────────────────────────────────────────
APP_VERSION = "0.1.4-rc.1"

# ── Run / event protocol ─────────────────────────────────────────────
PROTOCOL_VERSION = 1
MIN_PROTOCOL_VERSION = 1

# ── Update channels ──────────────────────────────────────────────────
STABLE_CHANNEL = "stable"
BETA_CHANNEL = "beta"
DEFAULT_CHANNEL = STABLE_CHANNEL

# ── GitHub repository coordinates (used by updater / installer) ──────
GITHUB_OWNER = "Navin45"
GITHUB_REPO = "bytebuddhi"

# ── Minimum Python version for consumer installs ─────────────────────
MIN_PYTHON = "3.13"
