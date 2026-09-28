# Updating ByteBuddhi

## CLI Update

Check for updates:

```bash
bytebuddhi update --check
```

Install the latest version:

```bash
bytebuddhi update
```

Sample output:

```
Updating ByteBuddhi 0.1.3 → 0.1.4 …
  ↓ Downloading release …
  ✓ Verified SHA-256
  ↓ Installing …
  ✓ Installed
  ✓ Smoke test passed
  ✓ Activated 0.1.4

ByteBuddhi 0.1.4 is ready.
```

## CLI Rollback

If an update causes issues, revert to the previous version:

```bash
bytebuddhi update --rollback
```

The managed install keeps at least one previous version. Rollback is instant — it simply switches the active version pointer.

## CLI Update Channels

By default, only stable releases are installed. To opt into pre-releases:

```bash
bytebuddhi update --channel beta
```

## Desktop Auto-Update

The desktop application checks for updates automatically (without auto-downloading).

The update flow:

1. **Update available** notification appears
2. User chooses **Download**
3. Download progress shown
4. **Ready to restart** — user chooses when
5. Application restarts with the new version

Updates are never applied while:
- An agent run is actively executing
- The user has unsaved content in the composer
- An OAuth sign-in flow is in progress

## Desktop Update Channels

In **Settings → About**, users can switch between `stable` and `beta` channels.

## How Updates Work

### CLI

```
bytebuddhi update
    ↓
fetch release.json from GitHub Releases
    ↓
compare current version with latest
    ↓
download wheel artifact
    ↓
verify SHA-256 checksum
    ↓
install into new versioned directory
    ↓
smoke test (bytebuddhi --version)
    ↓
atomically activate new version
    ↓
keep previous version for rollback
```

If any step fails, the current version remains active.

### Desktop

Uses `electron-updater` with GitHub Releases as the provider:

1. Checks `latest.yml` / `latest-mac.yml` from the release
2. Downloads platform-specific artifact
3. Verifies code signature (Windows: Authenticode, macOS: Developer ID)
4. Installs on next restart

## Troubleshooting

### Update check fails

Ensure outbound HTTPS to `github.com` is not blocked.

```bash
bytebuddhi update --check --output json
```

### Update installs but old version runs

Ensure the launcher shim is on your PATH:

```bash
which bytebuddhi
# Should point to ~/.bytebuddhi/bin/bytebuddhi
```

### Desktop update stuck

Restart the application. If the update is corrupted, reinstall from [GitHub Releases](https://github.com/Navin45/bytebuddhi/releases/latest).
