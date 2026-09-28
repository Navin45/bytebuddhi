# Desktop

The desktop app is another ByteBuddhi gateway client. Electron owns the window, the credential vault, and external URLs. React owns the chat UI. The renderer does not execute an agent and does not talk to PostgreSQL or Redis.

```text
CLI / TUI / Desktop GUI
        |
        same REST + WebSocket protocol
        |
        FastAPI gateway
        |
        Run coordinator
        |
        Workers
        |
        AgentRuntime
```

## Run it

From the repository root, with the gateway already available:

```bash
cd desktop
pnpm install
pnpm dev
```

The default gateway origin is `http://127.0.0.1:8765`. Settings can point at a remote origin. A remote origin never starts a local gateway. "Start the local gateway when this app opens" runs `uv run bytebuddhi gateway start` only for `127.0.0.1` or `localhost`. Closing the window closes sockets. It does not cancel the run and it does not stop the gateway.

Sign in with Google or GitHub. The system browser opens the existing `/api/v1/auth/{provider}/login?client=cli` flow. Paste the one-time code. The access token stays in the main process and is encrypted with Electron `safeStorage`.

## Contracts

Backend models are the source of truth. Generate the checked-in TypeScript contracts with:

```bash
cd desktop
pnpm generate:contracts
```

That runs `uv run python ../scripts/export_desktop_contracts.py`. It does not use the network. Normal `pnpm build` does not regenerate contracts.

## Checks

```bash
cd desktop
pnpm lint
pnpm typecheck
pnpm test
pnpm build
pnpm test:e2e
```

`pnpm test:e2e` builds the app and runs Playwright Electron scenarios against an in-process fake gateway. No model provider is required.

## Packaging and Distribution

ByteBuddhi Desktop is packaged with `electron-builder`:

```bash
cd desktop

# Build current platform
pnpm pack

# Target specific platforms
pnpm pack:win     # Windows NSIS installer (.exe)
pnpm pack:mac     # macOS DMG & ZIP (.dmg, .zip)
pnpm pack:linux   # Linux AppImage & deb (.AppImage, .deb)
```

Packaged outputs are placed in `desktop/release/<version>/`.

### Target Artifacts

| Platform | Architecture | Formats | Output Name |
|---|---|---|---|
| Windows | x64 | NSIS Installer | `ByteBuddhi-Setup-<version>.exe` |
| macOS | arm64, x64 | DMG, ZIP | `ByteBuddhi-<version>-<arch>.dmg`, `.zip` |
| Linux | x64 | AppImage, deb | `ByteBuddhi-<version>-<arch>.AppImage`, `bytebuddhi_<version>_<arch>.deb` |

### Code Signing and Notarization

Windows and macOS desktop builds are frozen until signing credentials exist. Current GitHub releases publish the Linux packages only. When those builds resume, production releases are signed in GitHub Actions:

- **Windows:** Authenticode code signing using `CSC_LINK` (PFX certificate) and `CSC_KEY_PASSWORD`.
- **macOS:** Hardened runtime enabled with entitlements (`build/entitlements.mac.plist`). Signed with Developer ID Application certificate and notarized using `notarytool` via `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD`, and `APPLE_TEAM_ID`.
- **Security Hardening:** Packaged production builds run with `nodeIntegration = false`, `contextIsolation = true`, `sandbox = true`, and `webSecurity = true`.

## Auto-Update

Desktop updates are delivered via `electron-updater` using GitHub Releases:

1. **Check:** Automatically or manually in **Settings → About → Check for updates**.
2. **Download:** The update payload is verified by hash and signature before staging.
3. **Safety Guard:** Updates cannot download or restart while an agent run is active (`hasActiveRun = true`).
4. **Install:** On user confirmation, the application restarts with the new version atomically applied.
