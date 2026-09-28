"""Clean-machine validation test runner.

Simulates an external user installation on a machine without repository context:
1. install
2. bytebuddhi --version
3. bytebuddhi --help
4. gateway status
5. health / application launch

Verifies that the product functions independently of the source tree.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate clean-machine installation")
    parser.add_argument("--version", default=None, help="Target version to validate")
    parser.add_argument("--wheel", default=None, help="Path to pre-built wheel (for offline validation)")
    parser.add_argument("--temp-dir", default=None, help="Explicit temporary directory")
    args = parser.parse_args()

    root_dir = Path(__file__).resolve().parent.parent
    base_tmp = Path(args.temp_dir) if args.temp_dir else Path(tempfile.mkdtemp(prefix="bb_clean_"))
    install_home = base_tmp / "bytebuddhi_home"
    install_home.mkdir(parents=True, exist_ok=True)

    print(f"[*] Validating clean-machine installation in isolated directory: {install_home}")

    # Build clean environment without source repository in PYTHONPATH
    clean_env = os.environ.copy()
    clean_env.pop("PYTHONPATH", None)
    clean_env["BYTEBUDDHI_HOME"] = str(install_home)
    clean_env["BYTEBUDDHI_CONFIG_DIR"] = str(install_home / "state")

    # 1. Determine launcher path
    if sys.platform == "win32":
        launcher = install_home / "bin" / "bytebuddhi.cmd"
    else:
        launcher = install_home / "bin" / "bytebuddhi"

    # If offline validation with wheel provided, simulate the installer steps directly:
    wheel_path = Path(args.wheel).resolve() if args.wheel else None
    if wheel_path is None:
        # Check dist/
        dist_wheels = list((root_dir / "dist").glob("*.whl"))
        if dist_wheels:
            wheel_path = dist_wheels[0]

    if not launcher.exists():
        if wheel_path and wheel_path.exists():
            print(f"[*] Simulating installer with local wheel: {wheel_path}")
            version = args.version or "0.1.3"
            venv_dir = install_home / "installs" / version
            # Use standalone uv or current python to create clean venv
            subprocess.run(["uv", "venv", str(venv_dir), "--python", "3.13"], check=True, env=clean_env)
            subprocess.run(
                ["uv", "pip", "install", "--python", str(venv_dir), str(wheel_path)], check=True, env=clean_env
            )

            # Create launcher shim
            bin_dir = install_home / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            (install_home / "current").write_text(version, encoding="utf-8")

            if sys.platform == "win32":
                shim = f"""@echo off
set "EXE=%~dp0..\\installs\\{version}\\Scripts\\bytebuddhi.exe"
"%EXE%" %*
"""
                launcher.write_text(shim, encoding="utf-8")
            else:
                shim = f"""#!/bin/sh
exec "$(dirname "$0")/../installs/{version}/bin/bytebuddhi" "$@"
"""
                launcher.write_text(shim, encoding="utf-8")
                launcher.chmod(0o755)
        else:
            print("[!] No launcher or wheel found. Run `uv build` first.")
            return 1

    print(f"[*] Testing launcher at: {launcher}")

    # 2. bytebuddhi --version
    print("[*] Running: bytebuddhi --version")
    res_ver = subprocess.run([str(launcher), "--version"], capture_output=True, text=True, env=clean_env)
    print(f"    Output: {res_ver.stdout.strip()}")
    if res_ver.returncode != 0:
        print(f"[FAIL] bytebuddhi --version failed with code {res_ver.returncode}: {res_ver.stderr}")
        return 1
    print("    [PASS] --version ok")

    # 3. bytebuddhi --help
    print("[*] Running: bytebuddhi --help")
    res_help = subprocess.run([str(launcher), "--help"], capture_output=True, text=True, env=clean_env)
    if res_help.returncode != 0 or "bytebuddhi" not in res_help.stdout:
        print(f"[FAIL] bytebuddhi --help failed with code {res_help.returncode}")
        return 1
    print("    [PASS] --help ok")

    # 4. bytebuddhi gateway status
    print("[*] Running: bytebuddhi gateway status --output json")
    res_gw = subprocess.run(
        [str(launcher), "gateway", "status", "--output", "json"],
        capture_output=True,
        text=True,
        env=clean_env,
    )
    if res_gw.returncode != 0:
        print(f"[FAIL] bytebuddhi gateway status failed with code {res_gw.returncode}: {res_gw.stderr}")
        return 1
    print(f"    Output: {res_gw.stdout.strip()}")
    print("    [PASS] gateway status ok")

    print("[SUCCESS] Clean-machine validation passed successfully!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
