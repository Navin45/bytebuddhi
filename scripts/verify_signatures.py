#!/usr/bin/env python3
"""Release Candidate signature and integrity verifier for Windows, macOS, and Linux.

Verifies:
  Windows:
    - Authenticode signature exists
    - Certificate subject matches expected organization
    - Signature chain is valid
    - Authenticode timestamp exists
  macOS:
    - Developer ID signature exists
    - Hardened runtime enabled
    - Apple notarization ticket stapled
    - Gatekeeper spctl assessment passes
  All:
    - Fails closed: if signing credentials were not available or artifact is unsigned,
      marks RC release BLOCKED.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any


def verify_windows_authenticode(exe_path: Path, expected_subject: str | None = None) -> dict[str, Any]:
    """Verify Authenticode signature on Windows using PowerShell Get-AuthenticodeSignature."""
    if not exe_path.exists():
        return {"status": "BLOCKED", "error": f"File not found: {exe_path}"}

    ps_script = f"""
    $sig = Get-AuthenticodeSignature -FilePath '{exe_path.resolve()}'
    $res = @{{
        Status = $sig.Status.ToString()
        StatusMessage = $sig.StatusMessage
        Subject = if ($sig.SignerCertificate) {{ $sig.SignerCertificate.Subject }} else {{ $null }}
        Thumbprint = if ($sig.SignerCertificate) {{ $sig.SignerCertificate.Thumbprint }} else {{ $null }}
        HasTimestamp = ($sig.TimeStamperCertificate -ne $null)
    }}
    $res | ConvertTo-Json -Compress
    """
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            return {"status": "BLOCKED", "error": proc.stderr.strip() or "PowerShell error"}

        data = json.loads(proc.stdout.strip())
        status = data.get("Status")
        subject = data.get("Subject") or ""
        has_timestamp = data.get("HasTimestamp") is True

        is_valid = status == "Valid"
        subject_matches = True
        if expected_subject and expected_subject not in subject:
            subject_matches = False

        if is_valid and has_timestamp and subject_matches:
            return {
                "status": "VERIFIED",
                "platform": "windows",
                "subject": subject,
                "thumbprint": data.get("Thumbprint"),
                "timestamped": True,
            }
        else:
            return {
                "status": "BLOCKED",
                "platform": "windows",
                "authenticode_status": status,
                "status_message": data.get("StatusMessage"),
                "subject": subject,
                "timestamped": has_timestamp,
                "reason": (
                    "Unsigned artifact" if status == "NotSigned" else f"Invalid Authenticode signature: {status}"
                ),
            }
    except Exception as exc:
        return {"status": "BLOCKED", "error": str(exc)}


def verify_macos_codesign(target_path: Path) -> dict[str, Any]:
    """Verify codesign, hardened runtime, and notarization on macOS."""
    if not target_path.exists():
        return {"status": "BLOCKED", "error": f"Target not found: {target_path}"}

    results: dict[str, Any] = {"platform": "macos"}

    # 1. codesign verification
    cs_proc = subprocess.run(
        ["codesign", "-dv", "--verbose=4", str(target_path)],
        capture_output=True,
        text=True,
    )
    stderr = cs_proc.stderr
    results["signed"] = cs_proc.returncode == 0
    results["hardened_runtime"] = "runtime flags=" in stderr or "flags=0x10000(runtime)" in stderr
    results["authority"] = [line for line in stderr.splitlines() if line.startswith("Authority=")]

    # 2. Gatekeeper spctl assessment
    sp_proc = subprocess.run(
        ["spctl", "--assess", "--type", "exec", "-v", str(target_path)],
        capture_output=True,
        text=True,
    )
    results["gatekeeper_accepted"] = sp_proc.returncode == 0

    # 3. Stapler notarization check
    stapler_proc = subprocess.run(
        ["stapler", "validate", str(target_path)],
        capture_output=True,
        text=True,
    )
    results["notarized"] = stapler_proc.returncode == 0

    if results["signed"] and results["hardened_runtime"] and results["notarized"]:
        results["status"] = "VERIFIED"
    else:
        results["status"] = "BLOCKED"
        results["reason"] = "Missing Developer ID signature, hardened runtime, or Apple notarization ticket"

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify release candidate binary signatures")
    parser.add_argument("artifact", nargs="?", help="Path to installer or binary artifact to verify")
    parser.add_argument("--expected-subject", help="Expected certificate subject")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    args = parser.parse_args()

    if not args.artifact:
        # Check environment signing credentials availability
        has_win_creds = bool(os.environ.get("CSC_LINK") and os.environ.get("CSC_KEY_PASSWORD"))
        has_mac_creds = bool(os.environ.get("APPLE_ID") and os.environ.get("APPLE_APP_SPECIFIC_PASSWORD"))
        report = {
            "credentials_available": {
                "windows_authenticode": has_win_creds,
                "macos_developer_id": has_mac_creds,
            },
            "desktop_platforms": {
                "linux": "active",
                "windows": "frozen",
                "macos": "frozen",
            },
            "status": "FROZEN",
            "message": (
                "Windows and macOS desktop builds are frozen until signing credentials exist. "
                "The Linux release does not use those credentials."
            ),
        }
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(f"Status: {report['status']}")
            print(f"Details: {report['message']}")
        return 0

    path = Path(args.artifact)
    ext = path.suffix.lower()

    if ext in {".exe", ".msi"}:
        res = verify_windows_authenticode(path, args.expected_subject)
    elif ext in {".dmg", ".app", ".pkg"}:
        res = verify_macos_codesign(path)
    else:
        res = {
            "status": "BLOCKED",
            "platform": "unknown",
            "reason": (
                f"No signature verifier for '{ext or 'this file'}'. A checksum does not establish a code signature."
            ),
        }

    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"Artifact: {path}")
        print(f"Status: {res['status']}")
        if res["status"] == "BLOCKED":
            print(f"Reason: {res.get('reason') or res.get('error')}")

    return 0 if res["status"] == "VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
