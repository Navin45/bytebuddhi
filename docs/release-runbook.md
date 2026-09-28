# ByteBuddhi Release Runbook

This document defines the authoritative, step-by-step procedure for releasing ByteBuddhi release candidates (RCs) and stable production releases. Any engineer on the team must be able to reproduce or audit a release using this runbook.

---

## 1. Release Authority and Governance

- **Authoritative Publisher:** GitHub Actions is the **only** entity authorized to publish release artifacts, push PyPI packages, or sign release binaries.
- **Developer Workstation Scope:** Developer machines may:
  1. Bump versions across source-of-truth files.
  2. Commit changes to the main branch or release branches.
  3. Create and push signed Git tags (`v*`).
  Developer machines must **never** publish or sign production binaries directly.
- **Protected Tags:** Only tags matching `v[0-9]+.[0-9]+.[0-9]+*` on `Navin45/bytebuddhi` trigger the release workflow. Pull requests cannot publish artifacts.
- **Repository ruleset (required once):** In GitHub, create a ruleset targeting `refs/tags/v*`. Restrict tag creation and deletion to repository administrators, and require the `release` environment on the publish job to have a required reviewer before a stable promotion. The workflow also refuses to run unless `github.repository` is `Navin45/bytebuddhi` and `github.ref_type` is `tag`.
- **Fail-Closed Rule:** The release pipeline aborts and marks the release **BLOCKED** if any quality gate, test suite, service health check, required artifact, checksum, SBOM, or attestation fails. Partial releases are strictly prohibited.
- **Desktop freeze:** Current releases publish the Linux AppImage and deb package only. Windows and macOS builds stay frozen until `CSC_LINK`, `CSC_KEY_PASSWORD`, `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD`, and `APPLE_TEAM_ID` exist. Unsigned Windows or macOS installers are not published.

---

## 2. Version Bump and Preflight

### 2.1 Decide Target Version
- **Release Candidate:** `0.1.4-rc.1`, `0.1.4-rc.2`, etc.
- **Production Stable:** `0.1.4`, `0.1.5`, etc.

### 2.2 Synchronize Version Across Source Files
Run the version synchronizer to atomically update `pyproject.toml`, `app/_version.py`, and `desktop/package.json`:

```bash
uv run python scripts/sync_version.py 0.1.4-rc.1
```

Verify that all files agree:

```bash
uv run python scripts/sync_version.py --check-tag v0.1.4-rc.1
```

### 2.3 Run Local Preflight Quality Gate

```bash
# Backend lint, format, typecheck, tests
uv run ruff check .
uv run ruff format --check .
uv run mypy app/
uv run pytest tests/ -q -m "not live_llm"

# Desktop lint, typecheck, tests
pnpm --prefix desktop lint
pnpm --prefix desktop typecheck
pnpm --prefix desktop test
```

---

## 3. Creating and Pushing the Release Tag

Commit all synced version changes locally:

```bash
git add pyproject.toml app/_version.py desktop/package.json
git commit -m "chore(release): bump version to 0.1.4-rc.1"
```

Create an annotated git tag and push it to origin:

```bash
git tag -a v0.1.4-rc.1 -m "ByteBuddhi Release Candidate 0.1.4-rc.1"
git push origin main
git push origin v0.1.4-rc.1
```

---

## 4. CI Release Pipeline Execution

The push of tag `v0.1.4-rc.1` automatically triggers `.github/workflows/release.yml`.

### 4.1 Automated Jobs Executed in Protected CI

1. **Preflight Job:**
   - Validates that the git tag strictly matches all repository version definitions.
   - Determines channel (`beta` for RC prereleases; `stable` for final releases).
2. **Integration Job (Fail-Closed PostgreSQL + Redis):**
   - Spins up PostgreSQL 16 (`pgvector/pgvector:pg16`) and Redis 7 service containers.
   - Runs Alembic database migrations: `uv run alembic upgrade head`.
   - Sets `BYTEBUDDHI_REQUIRE_DISTRIBUTED=1`. PostgreSQL, Redis, or a missing lease schema fails the job. Distributed tests are not allowed to skip.
   - Executes the test suite except live-provider and Playwright tests. Playwright runs in the security job with `BYTEBUDDHI_REQUIRE_PLAYWRIGHT=1`.
3. **Security Suite:**
   - Launches headless Playwright Chromium to test SSRF, safe external redirects, and renderer security.
4. **Dependency Audit:**
   - Executes `pip audit` across all dependencies.
5. **Python Build & Attestation:**
   - Compiles pure wheel and source distribution (`uv build`).
   - Generates SHA-256 checksums and CycloneDX SBOM (`dist/sbom.cdx.json`).
   - Attests build provenance using GitHub OIDC (`actions/attest-build-provenance`).
   - Publishes to PyPI via Trusted Publishing only if signing credentials and quality gates pass.
6. **Desktop Build & Code Signing:**
   - Builds the Linux AppImage and deb package (`x64`). Windows and macOS desktop builds are frozen and are not packaged.
   - Windows signing (`CSC_LINK`, `CSC_KEY_PASSWORD`) and macOS notarization (`APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD`, `APPLE_TEAM_ID`) resume only after those credentials exist.
   - Attestation failure fails the Linux desktop job.
   - A desktop beta channel follows the `rc` update feed (`rc.yml`). A stable channel follows `latest.yml` and does not install prereleases. Version `0.1.4-rc.1` stays a GitHub prerelease because the builder infers that from the version.
7. **Publish Job:**
   - Downloads all platform artifacts.
   - Generates consolidated `SHA256SUMS`.
   - Generates complete `release.json` manifest with platform, arch, url, and sha256.
   - Attaches `install.sh` and `install.ps1`.
   - Publishes GitHub Release marked as `prerelease: true` (for RC) or `prerelease: false` (for stable).

---

## 5. Artifact Verification Procedure

After CI completes, download the generated artifacts and verify them locally:

```bash
# Verify checksums
sha256sum -c SHA256SUMS

# Verify binary signatures
python scripts/verify_signatures.py release-files/ByteBuddhi-Setup-0.1.4-rc.1.exe
python scripts/verify_signatures.py release-files/ByteBuddhi-0.1.4-rc.1-arm64.dmg

# Verify release manifest integrity
python -c "
import json
data = json.load(open('release-files/release.json'))
assert data['version'] == '0.1.4-rc.1'
assert len(data['artifacts']) > 0
print('Manifest valid!')
"
```

---

## 6. Clean-Machine Validation Testing

Before promoting any RC to beta testers or stable users, run the installer on clean target machines:

### 6.1 Windows x64 Clean Test
```powershell
# In PowerShell (no repo or python requirement):
irm https://github.com/Navin45/bytebuddhi/releases/download/v0.1.4-rc.1/install.ps1 | iex
bytebuddhi --version
bytebuddhi --help
bytebuddhi doctor --json
```

### 6.2 Linux / macOS Clean Test
```bash
# In Bash:
curl -fsSL https://github.com/Navin45/bytebuddhi/releases/download/v0.1.4-rc.1/install.sh | bash
bytebuddhi --version
bytebuddhi --help
bytebuddhi doctor --json
```

---

## 7. Rollback and Downgrade Procedure

### 7.1 CLI Rollback
If a released CLI version exhibits runtime defects, users or administrators can roll back immediately to the previous known-good version without losing local configurations, credentials, or logs:

```bash
bytebuddhi update --rollback
```

Verify that the rollback restored the active version:
```bash
bytebuddhi --version
```

### 7.2 Desktop Rollback
If a desktop release fails:
1. Revoke or mark the release as broken on GitHub Releases.
2. In `settings.json`, set `releaseChannel: "stable"`.
3. Re-install the previous stable installer from the official release page. User settings (`userData/settings.json`) and credentials (`userData/credentials.bin`) remain intact.

---

## 8. Incident Response and Emergency Revocation

In the event of a critical security defect, leaked credential, or broken release:

1. **Immediate Revocation:**
   - Mark the GitHub Release as `Draft` or delete the release tag.
   - Yank the affected version from PyPI: `uv run pip-yank bytebuddhi <version>` (or through pypi.org UI).
2. **Channel Isolation:**
   - Ensure the `release.json` at `releases/latest/download/release.json` points to the last known-secure version.
3. **Post-Mortem & Fix:**
   - Branch from the hotfix base, resolve the defect, and tag a patch release (e.g. `v0.1.4-rc.2` or `v0.1.5`).
