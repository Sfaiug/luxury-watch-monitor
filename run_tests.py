#!/usr/bin/env python3
"""
Test runner script for the watch monitor application.

This script provides various ways to run the test suite with different
configurations and reporting options.
"""

import sys
import subprocess
import argparse
from pathlib import Path


def run_command(cmd, description):
    """Run a command and handle errors."""
    print(f"\n{'='*60}")
    print(f"Running: {description}")
    print(f"Command: {' '.join(cmd)}")
    print(f"{'='*60}")
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=False)
        print(f"✅ {description} completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed with exit code {e.returncode}")
        return False
    except FileNotFoundError:
        print(f"❌ Command not found: {cmd[0]}")
        print("Please ensure pytest is installed: pip install -r requirements.txt")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Run tests for the watch monitor application",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_tests.py                    # Run all tests with coverage
  python run_tests.py --fast             # Quick test run without coverage
  python run_tests.py --unit             # Run only unit tests
  python run_tests.py --integration      # Run only integration tests
  python run_tests.py --parallel         # Run tests in parallel
  python run_tests.py --verbose          # Verbose output
  python run_tests.py --file test_models # Run specific test file
        """
    )
    
    # Test selection options
    parser.add_argument("--fast", action="store_true",
                       help="Run tests quickly without coverage reporting")
    parser.add_argument("--unit", action="store_true",
                       help="Run only unit tests")
    parser.add_argument("--integration", action="store_true", 
                       help="Run only integration tests")
    parser.add_argument("--file", type=str,
                       help="Run specific test file (e.g., test_models)")
    parser.add_argument("--test", type=str,
                       help="Run specific test function (e.g., test_watch_data_initialization)")
    
    # Execution options
    parser.add_argument("--parallel", action="store_true",
                       help="Run tests in parallel using pytest-xdist")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Verbose output")
    parser.add_argument("--quiet", "-q", action="store_true",
                       help="Quiet output")
    
    # Coverage options
    parser.add_argument("--no-cov", action="store_true",
                       help="Disable coverage reporting")
    parser.add_argument("--cov-html", action="store_true",
                       help="Generate HTML coverage report only")
    
    # Other options
    parser.add_argument("--lf", action="store_true",
                       help="Run only last failed tests")
    parser.add_argument("--exitfirst", "-x", action="store_true",
                       help="Exit on first test failure")
    parser.add_argument("--pdb", action="store_true",
                       help="Drop into PDB on test failures")
    
    args = parser.parse_args()
    
    # Build pytest command
    cmd = ["python", "-m", "pytest"]
    
    # Test selection
    if args.file:
        test_file = f"tests/test_{args.file}.py" if not args.file.startswith("test_") else f"tests/{args.file}.py"
        cmd.append(test_file)
    elif args.test:
        cmd.extend(["-k", args.test])
    elif args.unit:
        cmd.extend(["-m", "unit"])
    elif args.integration:
        cmd.extend(["-m", "integration"])
    
    # Output options
    if args.verbose:
        cmd.append("-v")
    elif args.quiet:
        cmd.append("-q")
    
    # Execution options
    if args.parallel:
        cmd.extend(["-n", "auto"])
    
    if args.lf:
        cmd.append("--lf")
    
    if args.exitfirst:
        cmd.append("-x")
    
    if args.pdb:
        cmd.append("--pdb")
    
    # Coverage options
    if args.fast or args.no_cov:
        # Remove coverage options from pytest.ini
        cmd.extend(["--no-cov"])
    elif args.cov_html:
        cmd.extend(["--cov=.", "--cov-report=html"])
    
    # Ensure reports directory exists
    Path("reports").mkdir(exist_ok=True)
    
    # Run the tests
    success = run_command(cmd, "Test execution")
    
    if success:
        print(f"\n🎉 Test run completed successfully!")
        
        # Show coverage report location if generated
        if not (args.fast or args.no_cov):
            print(f"\n📊 Coverage reports:")
            print(f"  - HTML: htmlcov/index.html")
            print(f"  - XML: coverage.xml")
            print(f"  - Test Report: reports/test_report.html")
        
        print(f"\n💡 Tips:")
        print(f"  - Use --fast for quicker test runs during development")
        print(f"  - Use --parallel to run tests faster on multi-core systems")
        print(f"  - Use --file <name> to run specific test files")
        print(f"  - Use --lf to re-run only failed tests")
        
    else:
        print(f"\n💥 Test run failed!")
        print(f"Check the output above for details on failing tests.")
        sys.exit(1)


if __name__ == "__main__":
    main()