# Uninstalling ByteBuddhi

## CLI

Remove the managed CLI installation:

```bash
bytebuddhi uninstall
```

This removes:
- All installed versions (`~/.bytebuddhi/installs/`)
- The launcher (`~/.bytebuddhi/bin/`)
- Cache and logs

**Config and credentials are preserved** by default.

To remove everything including config and credentials:

```bash
bytebuddhi uninstall --purge
```

### Manual PATH Cleanup

If the installer added `~/.bytebuddhi/bin` to your PATH, remove the line from your shell profile:

**bash:** `~/.bashrc` or `~/.bash_profile`
**zsh:** `~/.zshrc`
**PowerShell:** The installer modifies the user PATH environment variable

### If the CLI is Already Broken

Remove the installation directory manually:

**Unix:**
```bash
rm -rf ~/.bytebuddhi
```

**Windows:**
```powershell
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\ByteBuddhi"
```

## Desktop

### Windows

Use **Settings → Apps → ByteBuddhi → Uninstall**, or run the uninstaller from the Start Menu.

User data is stored in `%APPDATA%\bytebuddhi-desktop\` and is **not** removed by the uninstaller. Delete it manually if desired.

### macOS

Drag `ByteBuddhi.app` from `/Applications` to the Trash.

User data is stored in `~/Library/Application Support/bytebuddhi-desktop/`. Delete it manually if desired.

### Linux

**AppImage:** Delete the `.AppImage` file.

**Debian:**
```bash
sudo dpkg -r bytebuddhi
```

User data is stored in `~/.config/bytebuddhi-desktop/`. Delete it manually if desired.

## PyPI Installation

If you installed via `pip`:

```bash
pip uninstall bytebuddhi
```

## Data Locations

| Platform | Config/Credentials | Cache |
|----------|-------------------|-------|
| **CLI (Unix)** | `~/.bytebuddhi/state/` | `~/.bytebuddhi/cache/` |
| **CLI (Windows)** | `%LOCALAPPDATA%\ByteBuddhi\state\` | `%LOCALAPPDATA%\ByteBuddhi\cache\` |
| **Desktop (Windows)** | `%APPDATA%\bytebuddhi-desktop\` | Same |
| **Desktop (macOS)** | `~/Library/Application Support/bytebuddhi-desktop/` | Same |
| **Desktop (Linux)** | `~/.config/bytebuddhi-desktop/` | Same |

> **Note:** Conversations and project data are stored on the gateway/server, not locally. Uninstalling the client does not delete server-side data.
