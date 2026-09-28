# Releases

## Version Scheme

ByteBuddhi uses [Semantic Versioning](https://semver.org/):

```
MAJOR.MINOR.PATCH
```

- **MAJOR:** Breaking API or protocol changes
- **MINOR:** New features, backward-compatible
- **PATCH:** Bug fixes, security patches

Pre-releases use suffixes: `0.2.0-rc.1`

## Release Process

1. Bump version in `pyproject.toml`
2. Run `python scripts/sync_version.py` to propagate
3. Commit and push
4. Create and push tag: `git tag v0.1.4 && git push origin v0.1.4`
5. CI validates version consistency across all files
6. CI runs full test suite including PostgreSQL + Redis integration
7. CI builds Python wheel, desktop installers for all platforms
8. CI signs artifacts (Windows Authenticode, macOS Developer ID)
9. CI notarizes macOS builds
10. CI generates checksums, SBOM, and provenance attestations
11. CI publishes to PyPI and GitHub Releases

## Version Source of Truth

```
pyproject.toml → [project].version
                    ↓
    scripts/sync_version.py propagates to:
                    ↓
    app/_version.py  (APP_VERSION)
    app/__init__.py  (__version__)
    desktop/package.json  (version)
```

Release CI validates all four locations match the git tag. Any mismatch blocks the release.

## Protocol Version

The run/event protocol is versioned independently:

```python
PROTOCOL_VERSION = 1  # in app/_version.py
```

The gateway reports both `version` and `protocol_version` in its health endpoint. Clients can detect incompatible gateways.

## Release Artifacts

Each release publishes:

| Artifact | Description |
|----------|-------------|
| `bytebuddhi-X.Y.Z-py3-none-any.whl` | Python wheel |
| `bytebuddhi-X.Y.Z.tar.gz` | Source distribution |
| `ByteBuddhi-X.Y.Z-x64.AppImage` | Linux AppImage |
| `bytebuddhi_X.Y.Z_x64.deb` | Debian package |

Windows and macOS desktop installers are frozen until signing credentials exist. They are not published unsigned.
| `SHA256SUMS` | Artifact checksums |
| `release.json` | Machine-readable manifest |
| `sbom.cdx.json` | CycloneDX SBOM |
| `install.sh` | Unix CLI installer |
| `install.ps1` | Windows CLI installer |

## Update Channels

| Channel | Receives |
|---------|----------|
| `stable` | GA releases only |
| `beta` | Pre-releases (`-rc.N`, `-beta.N`) |

Desktop users can opt into `beta` in Settings. CLI users can pass `--channel beta` to `bytebuddhi update`.

## CI Secrets Required

The current Linux release does not need signing secrets. These remain required before Windows or macOS builds are unfrozen:

| Secret | Purpose |
|--------|---------|
| `CSC_LINK` | Windows code signing certificate (Base64 PFX) |
| `CSC_KEY_PASSWORD` | Certificate password |
| `APPLE_ID` | Apple ID for notarization |
| `APPLE_APP_SPECIFIC_PASSWORD` | App-specific password |
| `APPLE_TEAM_ID` | Developer Team ID |

Never commit secret values. Use GitHub Actions secrets.
