#!/usr/bin/env python3
"""Run tests for ByteBuddhi.

This script runs the test suite using pytest with appropriate
configuration and reporting.
"""

import subprocess
import sys
from pathlib import Path


def main():
    """Run the test suite."""
    print("="*60)
    print("Running ByteBuddhi Test Suite")
    print("="*60)
    
    # Check if tests directory exists
    if not Path("tests").exists():
        print("\n tests/ directory not found!")
        print("Creating tests directory structure...")
        Path("tests").mkdir(exist_ok=True)
        Path("tests/__init__.py").touch()
        print("Tests directory created. Add your test files to tests/")
        sys.exit(0)
    
    # Build pytest command
    cmd = [
        "pytest",
        "tests/",
        "-v",                    # Verbose output
        "--tb=short",            # Short traceback format
        "--cov=app",             # Coverage for app directory
        "--cov-report=term-missing",  # Show missing lines
        "--cov-report=html",     # Generate HTML coverage report
    ]
    
    try:
        result = subprocess.run(cmd, check=False)
        
        print("\n" + "="*60)
        if result.returncode == 0:
            print("All tests passed!")
            print("="*60)
            print("\nCoverage report generated: htmlcov/index.html")
        else:
            print("Some tests failed!")
            print("="*60)
            print("\nCheck the output above for details.")
        
        sys.exit(result.returncode)
        
    except FileNotFoundError:
        print("\n pytest not found!")
        print("Install test dependencies with:")
        print("  pip install pytest pytest-cov pytest-asyncio")
        sys.exit(1)


if __name__ == "__main__":
    main()
