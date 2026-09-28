# Installation

## Quick Install

### macOS / Linux

```bash
curl -fsSL https://github.com/Navin45/bytebuddhi/releases/latest/download/install.sh | bash
```

### Windows (PowerShell)

```powershell
irm https://github.com/Navin45/bytebuddhi/releases/latest/download/install.ps1 | iex
```

After installation, open a new terminal and verify:

```bash
bytebuddhi --version
```

## Desktop Application

Download the installer for your platform from [GitHub Releases](https://github.com/Navin45/bytebuddhi/releases/latest):

| Platform | File |
|----------|------|
| Windows x64 | `ByteBuddhi-Setup-X.Y.Z.exe` |
| macOS Apple Silicon | `ByteBuddhi-X.Y.Z-arm64.dmg` |
| macOS Intel | `ByteBuddhi-X.Y.Z-x64.dmg` |
| Linux x64 (AppImage) | `ByteBuddhi-X.Y.Z-x64.AppImage` |
| Linux x64 (Debian) | `bytebuddhi_X.Y.Z_x64.deb` |

## Pin a Specific Version

```bash
BYTEBUDDHI_VERSION=0.1.4 curl -fsSL https://github.com/Navin45/bytebuddhi/releases/latest/download/install.sh | bash
```

```powershell
$env:BYTEBUDDHI_VERSION = "0.1.4"
irm https://github.com/Navin45/bytebuddhi/releases/latest/download/install.ps1 | iex
```

## Install from PyPI

```bash
pip install bytebuddhi
```

or with [uv](https://docs.astral.sh/uv/):

```bash
uv pip install bytebuddhi
```

## Install from Source (Developer)

```bash
git clone https://github.com/Navin45/bytebuddhi.git
cd bytebuddhi
uv sync --extra dev
```

For the desktop app:

```bash
cd desktop
pnpm install
pnpm dev
```

## Prerequisites

### Consumer Installation (CLI & Desktop)

- **No system Python required.** The consumer installer (`install.sh` / `install.ps1`) automatically provisions a self-contained, isolated Python runtime without touching host system packages.
- Clean machines on Windows x64, macOS (Apple Silicon / Intel), and Linux x64 run out-of-the-box.
- Desktop installers include all components natively.

### Developer Installation (From Source)

- Python 3.13 or later (or [uv](https://docs.astral.sh/uv/))
- Node.js 22+ and pnpm 10+ (for Desktop development)

### Server / Self-hosted

See [Production](production.md) for PostgreSQL, Redis, and model provider setup.

## What Gets Installed

### CLI (Managed Install)

The installer creates a managed directory:

**Unix:** `~/.bytebuddhi/`
**Windows:** `%LOCALAPPDATA%\ByteBuddhi\`

```
installs/
    0.1.3/          ← isolated venv
    0.1.4/
bin/
    bytebuddhi      ← launcher
current              ← active version
state/               ← config, credentials
logs/
cache/
```

Each version is an immutable, isolated virtual environment. Updates install alongside existing versions. Rollback is always available.

### Desktop

Standard platform installation:
- **Windows:** `%LOCALAPPDATA%\Programs\ByteBuddhi\`
- **macOS:** `/Applications/ByteBuddhi.app`
- **Linux:** AppImage (portable) or `/usr/bin/bytebuddhi` (deb)

## Verify Installation

```bash
bytebuddhi --version
bytebuddhi health
bytebuddhi gateway status
```

## Network Requirements

ByteBuddhi needs outbound HTTPS access to:
- Your configured model provider (OpenAI, Anthropic, etc.)
- `github.com` for update checks (optional)

No inbound ports are required for the CLI or desktop client.
