# Clean-Machine Release Validation

This document defines the procedure for validating ByteBuddhi release candidates on clean, isolated environments without source repository dependencies or pre-installed Python runtimes.

---

## Supported Matrix

| Platform | Architecture | Runtime Bootstrap | Keyring Backend | Installer Target |
| :--- | :--- | :--- | :--- | :--- |
| **Windows** | x64 | Self-contained `uv.exe` | Windows DPAPI | `%LOCALAPPDATA%\ByteBuddhi` |
| **macOS** | arm64 (Apple Silicon) | Self-contained `uv` | macOS Keychain | `~/.local/share/bytebuddhi` |
| **macOS** | x64 (Intel) | Self-contained `uv` | macOS Keychain | `~/.local/share/bytebuddhi` |
| **Linux** | x64 (glibc 2.28+) | Self-contained `uv` | Secret Service / Encrypted | `~/.local/share/bytebuddhi` |

---

## Validation Lifecycle

Every platform must execute the following sequence on a clean VM or container:

```
[Clean Machine (No Python)]
         ↓
  Consumer Install
         ↓
  bytebuddhi --version
         ↓
  bytebuddhi --help
         ↓
  bytebuddhi doctor
         ↓
  bytebuddhi gateway status
         ↓
  Launch Application / Desktop
```

---

## Step-by-Step Instructions

### 1. Windows x64

Run in a clean PowerShell session (e.g. Windows Sandbox, clean VM):

```powershell
# 1. Install via consumer bootstrap script (zero system Python required)
irm https://raw.githubusercontent.com/Navin45/bytebuddhi/main/scripts/install.ps1 | iex

# 2. Add to PATH for current session
$env:Path = "$env:LOCALAPPDATA\ByteBuddhi\bin;" + $env:Path

# 3. Verify version & protocol
bytebuddhi --version

# 4. Verify help text
bytebuddhi --help

# 5. Run operational doctor
bytebuddhi doctor

# 6. Verify gateway lifecycle
bytebuddhi gateway start
bytebuddhi gateway status
bytebuddhi gateway stop
```

### 2. macOS (arm64 & x64)

Run in a clean macOS environment:

```bash
# 1. Install via consumer bootstrap script
curl -fsSL https://raw.githubusercontent.com/Navin45/bytebuddhi/main/scripts/install.sh | bash

# 2. Add to PATH
export PATH="$HOME/.local/bin:$PATH"

# 3. Verify CLI execution
bytebuddhi --version
bytebuddhi --help
bytebuddhi doctor

# 4. Gateway lifecycle
bytebuddhi gateway start
bytebuddhi gateway status
bytebuddhi gateway stop

# 5. Desktop Application Launch
open /Applications/ByteBuddhi.app
```

### 3. Linux x64

Run in a clean container or VM (e.g. `ubuntu:22.04` or `debian:12`):

```bash
# Ensure curl is available
apt-get update && apt-get install -y curl

# 1. Install
curl -fsSL https://raw.githubusercontent.com/Navin45/bytebuddhi/main/scripts/install.sh | bash

# 2. Add to PATH
export PATH="$HOME/.local/bin:$PATH"

# 3. Verify
bytebuddhi --version
bytebuddhi --help
bytebuddhi doctor
bytebuddhi gateway status
```

---

## Automated Validation Script

The repository includes [`scripts/validate_clean_machine.py`](../scripts/validate_clean_machine.py) which performs this full sequence programmatically:

```bash
python scripts/validate_clean_machine.py --install-dir /tmp/bb-clean-test
```
