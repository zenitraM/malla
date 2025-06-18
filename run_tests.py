#!/usr/bin/env python3
"""
Test runner for the Meshtastic Mesh Health Web UI.

This script provides convenient commands for running different types of tests
and generating coverage reports.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


def run_command(cmd, capture_output=False):
    """Run a shell command and return the result."""
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=capture_output, text=True)
    if result.returncode != 0:
        print(f"Command failed with return code {result.returncode}")
        if capture_output:
            print("STDOUT:", result.stdout)
            print("STDERR:", result.stderr)
        sys.exit(1)
    return result


def install_test_dependencies():
    """Install test dependencies."""
    print("Installing test dependencies...")
    run_command([sys.executable, "-m", "pip", "install", "-e", ".[test]"])


def run_unit_tests(verbose=False, coverage=False, parallel=None):
    """Run unit tests."""
    cmd = [sys.executable, "-m", "pytest", "tests/unit/", "-m", "unit"]

    if verbose:
        cmd.append("-v")

    if coverage:
        cmd.extend(["--cov=.", "--cov-report=html", "--cov-report=term"])

    if parallel is not None:
        if parallel == 0:
            # Disable parallel execution
            cmd.append("-n=0")
        elif parallel > 0:
            # Use specific number of workers
            cmd.append(f"-n={parallel}")
        # If parallel is None, use default from pytest.ini (auto)

    run_command(cmd)


def run_integration_tests(verbose=False, coverage=False, parallel=None):
    """Run integration tests."""
    cmd = [sys.executable, "-m", "pytest", "tests/integration/", "-m", "integration"]

    if verbose:
        cmd.append("-v")

    if coverage:
        cmd.extend(["--cov=.", "--cov-report=html", "--cov-report=term"])

    if parallel is not None:
        if parallel == 0:
            # Disable parallel execution
            cmd.append("-n=0")
        elif parallel > 0:
            # Use specific number of workers
            cmd.append(f"-n={parallel}")
        # If parallel is None, use default from pytest.ini (auto)

    run_command(cmd)


def run_api_tests(verbose=False, coverage=False, parallel=None):
    """Run API-specific tests."""
    cmd = [sys.executable, "-m", "pytest", "tests/", "-m", "api"]

    if verbose:
        cmd.append("-v")

    if coverage:
        cmd.extend(["--cov=.", "--cov-report=html", "--cov-report=term"])

    if parallel is not None:
        if parallel == 0:
            # Disable parallel execution
            cmd.append("-n=0")
        elif parallel > 0:
            # Use specific number of workers
            cmd.append(f"-n={parallel}")
        # If parallel is None, use default from pytest.ini (auto)

    run_command(cmd)


def run_all_tests(verbose=False, coverage=False, parallel=None):
    """Run all tests."""
    cmd = [sys.executable, "-m", "pytest", "tests/"]

    if verbose:
        cmd.append("-v")

    if coverage:
        cmd.extend(["--cov=.", "--cov-report=html", "--cov-report=term"])

    if parallel is not None:
        if parallel == 0:
            # Disable parallel execution
            cmd.append("-n=0")
        elif parallel > 0:
            # Use specific number of workers
            cmd.append(f"-n={parallel}")
        # If parallel is None, use default from pytest.ini (auto)

    run_command(cmd)


def run_slow_tests(verbose=False, parallel=None):
    """Run slow tests (marked with @pytest.mark.slow)."""
    cmd = [sys.executable, "-m", "pytest", "tests/", "-m", "slow"]

    if verbose:
        cmd.append("-v")

    if parallel is not None:
        if parallel == 0:
            # Disable parallel execution
            cmd.append("-n=0")
        elif parallel > 0:
            # Use specific number of workers
            cmd.append(f"-n={parallel}")
        # If parallel is None, use default from pytest.ini (auto)

    run_command(cmd)


def check_test_environment():
    """Check if the test environment is properly set up."""
    print("Checking test environment...")

    # Check if pytest is installed
    try:
        import pytest

        print(f"✓ pytest installed (version {pytest.__version__})")
    except ImportError:
        print("✗ pytest not installed")
        return False

    # Check if pytest-xdist is installed
    try:
        import xdist

        print(f"✓ pytest-xdist installed (version {xdist.__version__})")
    except ImportError:
        print("⚠ pytest-xdist not installed (parallel testing disabled)")
        # This is not a failure, just a warning

    # Check if test files exist
    test_dir = Path("tests")
    if not test_dir.exists():
        print("✗ tests directory not found")
        return False

    print("✓ tests directory found")

    # Check for test configuration
    conftest_file = test_dir / "conftest.py"
    if conftest_file.exists():
        print("✓ conftest.py found")
    else:
        print("✗ conftest.py not found")
        return False

    return True


def generate_coverage_report():
    """Generate a detailed coverage report."""
    print("Generating coverage report...")
    run_command(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/",
            "--cov=.",
            "--cov-report=html",
            "--cov-report=term-missing",
            "--cov-report=xml",
        ]
    )

    print("\nCoverage report generated:")
    print("- HTML report: htmlcov/index.html")
    print("- XML report: coverage.xml")


def main():
    """Main test runner function."""
    parser = argparse.ArgumentParser(description="Test runner for Mesh Health Web UI")
    parser.add_argument(
        "--install", action="store_true", help="Install test dependencies"
    )
    parser.add_argument("--check", action="store_true", help="Check test environment")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument(
        "--coverage", action="store_true", help="Generate coverage report"
    )
    parser.add_argument(
        "-n",
        "--parallel",
        type=int,
        metavar="N",
        help="Number of parallel workers (0=disable, default=auto)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Test commands")

    # Unit tests
    unit_parser = subparsers.add_parser("unit", help="Run unit tests")
    unit_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose output"
    )
    unit_parser.add_argument(
        "--coverage", action="store_true", help="Generate coverage report"
    )
    unit_parser.add_argument(
        "-n",
        "--parallel",
        type=int,
        metavar="N",
        help="Number of parallel workers (0=disable, default=auto)",
    )

    # Integration tests
    integration_parser = subparsers.add_parser(
        "integration", help="Run integration tests"
    )
    integration_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose output"
    )
    integration_parser.add_argument(
        "--coverage", action="store_true", help="Generate coverage report"
    )
    integration_parser.add_argument(
        "-n",
        "--parallel",
        type=int,
        metavar="N",
        help="Number of parallel workers (0=disable, default=auto)",
    )

    # API tests
    api_parser = subparsers.add_parser("api", help="Run API tests")
    api_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose output"
    )
    api_parser.add_argument(
        "--coverage", action="store_true", help="Generate coverage report"
    )
    api_parser.add_argument(
        "-n",
        "--parallel",
        type=int,
        metavar="N",
        help="Number of parallel workers (0=disable, default=auto)",
    )

    # All tests
    all_parser = subparsers.add_parser("all", help="Run all tests")
    all_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose output"
    )
    all_parser.add_argument(
        "--coverage", action="store_true", help="Generate coverage report"
    )
    all_parser.add_argument(
        "-n",
        "--parallel",
        type=int,
        metavar="N",
        help="Number of parallel workers (0=disable, default=auto)",
    )

    # Slow tests
    slow_parser = subparsers.add_parser("slow", help="Run slow tests")
    slow_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose output"
    )
    slow_parser.add_argument(
        "-n",
        "--parallel",
        type=int,
        metavar="N",
        help="Number of parallel workers (0=disable, default=auto)",
    )

    # Coverage report
    subparsers.add_parser("coverage", help="Generate coverage report")

    args = parser.parse_args()

    if args.install:
        install_test_dependencies()
        return

    if args.check:
        if check_test_environment():
            print("✓ Test environment is ready")
        else:
            print("✗ Test environment needs setup")
            sys.exit(1)
        return

    if not args.command:
        # Default: run all tests
        args.command = "all"
        args.verbose = args.verbose
        args.coverage = args.coverage
        # Use global parallel setting if available
        if not hasattr(args, "parallel"):
            args.parallel = getattr(args, "parallel", None)

    # Change to project directory
    project_dir = Path(__file__).parent
    os.chdir(project_dir)

    # Run the appropriate test command
    if args.command == "unit":
        run_unit_tests(args.verbose, args.coverage, getattr(args, "parallel", None))
    elif args.command == "integration":
        run_integration_tests(
            args.verbose, args.coverage, getattr(args, "parallel", None)
        )
    elif args.command == "api":
        run_api_tests(args.verbose, args.coverage, getattr(args, "parallel", None))
    elif args.command == "all":
        run_all_tests(args.verbose, args.coverage, getattr(args, "parallel", None))
    elif args.command == "slow":
        run_slow_tests(args.verbose, getattr(args, "parallel", None))
    elif args.command == "coverage":
        generate_coverage_report()
    else:
        print(f"Unknown command: {args.command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
