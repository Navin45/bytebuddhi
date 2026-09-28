# ByteBuddhi Production Release Checklist

Every item in this checklist is objectively verifiable. A release must **NOT** be marked production-ready or promoted from Release Candidate (RC) to Stable if any checklist item fails.

---

## 1. Code Quality & Standards

- [ ] **Version Consistency:** All source files (`pyproject.toml`, `app/_version.py`, `desktop/package.json`) match the release tag exactly.  
  *Verification:* `uv run python scripts/sync_version.py --check-tag v<version>` exits with code `0`.
- [ ] **Linter Quality Gate:** Python code adheres strictly to PEP 8, import sorting, and syntax standards.  
  *Verification:* `uv run ruff check .` reports zero errors.
- [ ] **Formatter Quality Gate:** All Python files are deterministically formatted.  
  *Verification:* `uv run ruff format --check .` reports zero files needing reformatting.
- [ ] **Static Type Safety:** Python codebase satisfies strict type constraints.  
  *Verification:* `uv run mypy app/` reports 0 issues across all source files.
- [ ] **Desktop Lint & Typecheck:** Electron and React desktop codebase satisfies ESLint and TypeScript compilation.  
  *Verification:* `pnpm --prefix desktop lint` and `pnpm --prefix desktop typecheck` exit with code `0`.

---

## 2. Test Verification

- [ ] **Unit Test Suite:** All unit test suites pass completely.  
  *Verification:* `uv run pytest tests/ -q -m "not live_llm"` exits with code `0`.
- [ ] **Desktop Test Suite:** Desktop unit and integration test suites pass completely.  
  *Verification:* `pnpm --prefix desktop test` passes all tests.
- [ ] **Approval Workflow End-to-End:** Dangerous tool execution requires server-authoritative approval; approval resolution resumes execution; rejection terminates/aborts execution cleanly; unauthorized users cannot approve runs.  
  *Verification:* `uv run pytest tests/integration/test_approval_workflow.py` passes 6/6 tests.
- [ ] **Playwright Browser Security Suite:** SSRF, URL redirects, and cross-origin resource access are blocked by policy.  
  *Verification:* `uv run pytest tests/integration/web/test_playwright_browser_security.py` exits with code `0`.

---

## 3. Database (PostgreSQL + pgvector)

- [ ] **Alembic Migrations:** Database schema migrations apply cleanly from empty database to head.  
  *Verification:* `uv run alembic upgrade head` completes with exit code `0`.
- [ ] **Migration Rollback Safety:** Database schema downgrades roll back cleanly without data corruption.  
  *Verification:* `uv run python scripts/rollback_migration.py base` and re-upgrade `uv run alembic upgrade head` succeed.
- [ ] **Vector Extension Support:** PostgreSQL supports `pgvector` extension and vector similarity operations.  
  *Verification:* `SELECT 1 FROM pg_extension WHERE extname = 'vector'` returns 1.

---

## 4. Redis Coordination & Event Bus

- [ ] **Distributed Leases & Reaping:** Redis worker lease acquisition, heartbeats, and stale worker recovery operate as expected.  
  *Verification:* `BYTEBUDDHI_REQUIRE_DISTRIBUTED=1 uv run pytest tests/integration/test_distributed_execution.py` passes all worker lease tests.
- [ ] **Pub/Sub Fanout & Cancellation:** Run events and cancellation signals propagate through Redis channels with sequence guarantees.  
  *Verification:* Event sequencing and cancellation tests in `test_distributed_execution.py` pass without skipping.
- [ ] **Fail-Closed Distributed Invariant:** If Redis or PostgreSQL services are offline during release tests, the pipeline fails immediately.  
  *Verification:* `BYTEBUDDHI_REQUIRE_DISTRIBUTED=1` is set in CI release workflow.

---

## 5. Code Signing & Notarization

- [ ] **Windows and macOS frozen:** The current release does not publish `.exe` or `.dmg` artifacts. An unsigned installer is not a substitute.  
  *Verification:* `release-files/` contains no `.exe` or `.dmg`. `uv run python scripts/verify_signatures.py` outputs `status: FROZEN`.
- [ ] **Signed desktop later:** When Windows or macOS builds resume, `verify_signatures.py` on those artifacts must return `VERIFIED` before they are published.

---

## 6. Packaging & Manifests

- [ ] **Python Artifacts:** Wheel (`.whl`) and Source Distribution (`.tar.gz`) built and inspected.  
  *Verification:* `uv build` generates valid files in `dist/`.
- [ ] **Consolidated Checksums:** Every release artifact has a corresponding SHA-256 entry.  
  *Verification:* `sha256sum -c release-files/SHA256SUMS` validates all entries.
- [ ] **Release Manifest:** `release.json` includes version, git commit, protocol version, update channels, and artifact descriptors.  
  *Verification:* `python scripts/release_manifest.py` generates compliant manifest.
- [ ] **Software Bill of Materials (SBOM):** CycloneDX 1.5 SBOM generated with all production dependencies.  
  *Verification:* `python scripts/generate_sbom.py --version <version> --output dist/sbom.cdx.json` succeeds.
- [ ] **Build Provenance Attestation:** GitHub Actions OIDC build provenance attestation created.  
  *Verification:* `actions/attest-build-provenance` step succeeds in release workflow.

---

## 7. Security & Credential Isolation

- [ ] **Native OS Keyring:** Credentials stored using DPAPI (Windows), Keychain (macOS), or isolated encrypted storage (Linux).  
  *Verification:* `uv run pytest tests/unit/interfaces/cli/test_credentials_keyring.py` passes all tests.
- [ ] **No Token Leakage in Repr/Logs:** Credentials and tokens are redacted from string representations and exceptions.  
  *Verification:* `test_credential_repr_never_leaks_tokens` passes.
- [ ] **Deterministic Support Bundle Redaction:** Diagnostics export scrubs bearer tokens, JWTs, API keys, passwords, and user prompts from all files.  
  *Verification:* `uv run pytest tests/unit/interfaces/cli/test_support_bundle_redaction.py` passes.
- [ ] **Renderer Sandbox:** Electron renderer contextIsolation is enabled, nodeIntegration disabled, and navigation guarded.  
  *Verification:* `tests/unit/security.test.ts` passes.

---

## 8. Installation Verification

- [ ] **Windows Clean Installation:** Self-contained installation via `install.ps1` completes on a machine without pre-existing Python.  
  *Verification:* `scripts/install.ps1` installs runtime into `~/.bytebuddhi` and creates functional `bytebuddhi.cmd` launcher.
- [ ] **Linux/macOS Clean Installation:** Installation via `install.sh` completes in clean environment.  
  *Verification:* `scripts/install.sh` creates isolated virtualenv and functional launcher shim.
- [ ] **Diagnostics Smoke Check:** Clean install responds to standard operational commands:  
  *Verification:* `bytebuddhi --version`, `bytebuddhi --help`, and `bytebuddhi doctor --json` succeed.

---

## 9. Update & Active Run Safety

- [ ] **Atomic Upgrade:** Upgrading from prior version preserves configuration, credentials, and logs.  
  *Verification:* `test_installed_upgrade_preserves_state_and_config` in `test_update_rollback_hardening.py` passes.
- [ ] **Active Run Postponement:** If an agent run is active, update download and install actions are postponed and active run is never interrupted.  
  *Verification:* `tests/unit/update.test.ts` blocks update when `hasActiveRun` is `true`.
- [ ] **Failure Containment:** If download is corrupted or SHA-256 mismatches, the existing installation remains untouched.  
  *Verification:* `test_corrupted_checksum_fails_closed_and_keeps_previous_version` passes.

---

## 10. Rollback Capability

- [ ] **Automatic Smoke-Test Rollback:** If a newly installed version fails the startup smoke test, it automatically reverts to the previous version.  
  *Verification:* `test_startup_smoke_test_failure_triggers_automatic_rollback` passes.
- [ ] **Manual Rollback Command:** User can execute `bytebuddhi update --rollback` to revert to previous known-good version.  
  *Verification:* `test_manual_rollback_to_known_good_preserves_state` passes.

---

## 11. Documentation & Operations

- [ ] **Release Runbook:** Operational procedures documented for new engineers.  
  *Verification:* `docs/release-runbook.md` exists and contains all required phases.
- [ ] **Clean-Machine Documentation:** Step-by-step consumer validation guides available.  
  *Verification:* `docs/clean_machine_validation.md` and `docs/installation.md` are up to date.
- [ ] **Provenance Verification Guide:** Instructions for verifying Sigstore / GitHub attestation provenance.  
  *Verification:* `docs/provenance_verification.md` is complete and verified.
