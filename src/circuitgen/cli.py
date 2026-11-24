"""CircuitGen command-line interface entrypoint."""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from typing import Sequence


def get_version() -> str:
    """Return the package version from installed metadata or development fallback."""
    try:
        from importlib.metadata import version

        return version("circuitgen")
    except Exception:
        try:
            from circuitgen import __version__

            return __version__
        except Exception:
            return "0.1.0"


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI argument parser with subcommands."""
    version_str = get_version()
    parser = argparse.ArgumentParser(
        prog="circuitgen",
        description="CircuitGen: Circuit schematics from text descriptions or netlists.",
    )
    parser.add_argument(
        "--version",
        "-v",
        action="version",
        version=f"%(prog)s {version_str}",
        help="Show program's version number and exit.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Enable verbose debugging output and full exception tracebacks.",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        title="Subcommands",
        description="Diagnostic and configuration commands (omit all arguments to launch interactive TUI)",
    )

    # setup-path subcommand
    setup_parser = subparsers.add_parser(
        "setup-path",
        help="Diagnose and configure Windows persistent User PATH for circuitgen.",
        description="Inspect and optionally add the CircuitGen launcher directory to your persistent Windows User PATH.",
    )
    setup_parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        default=False,
        help="Do not prompt for confirmation; apply PATH update automatically.",
    )
    setup_parser.add_argument(
        "--check",
        action="store_true",
        default=False,
        help="Check whether PATH configuration is needed without making any modifications.",
    )

    # doctor subcommand
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Run read-only system and environment diagnostics.",
        description="Perform comprehensive diagnostics on Python, PATH, package resources, dependencies, and terminal.",
    )
    doctor_parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Show full exception tracebacks if diagnostics encounter errors.",
    )

    return parser


def launch_tui(debug_mode: bool = False) -> int:
    """Validate terminal capabilities and launch the Textual interactive TUI."""
    # Terminal capability check for interactive use
    is_interactive = sys.stdin.isatty() and sys.stdout.isatty()
    # Allow bypass during automated testing or explicit force flag
    testing = "PYTEST_CURRENT_TEST" in os.environ or "CIRCUITGEN_FORCE_TUI" in os.environ
    if not is_interactive and not testing:
        sys.stderr.write(
            "Error: CircuitGen interactive TUI requires an interactive terminal.\n"
            "Run 'circuitgen --help' for available CLI options or 'circuitgen doctor' for diagnostics.\n"
        )
        return 1

    term_size = shutil.get_terminal_size(fallback=(80, 24))
    if (term_size.columns < 80 or term_size.lines < 24) and not testing:
        sys.stderr.write(
            f"Notice: Terminal size ({term_size.columns}x{term_size.lines}) is smaller than the recommended 80x24.\n"
            "The interface may wrap or clip. Resizing your terminal window is recommended.\n"
        )

    try:
        from circuitgen.tui import CircuitGenApp

        app = CircuitGenApp()
        app.run()
        return 0
    except KeyboardInterrupt:
        return 130
    except (ImportError, ModuleNotFoundError) as exc:
        sys.stderr.write(
            f"Error: Missing required dependency ({exc}).\n"
            "Please run 'python -m pip install circuitgen' or 'circuitgen doctor' for diagnostics.\n"
        )
        return 1
    except Exception as exc:
        if debug_mode or os.environ.get("CIRCUITGEN_DEBUG") == "1":
            raise
        sys.stderr.write(
            f"Error launching CircuitGen: {exc}\n"
            "Run with --debug or run 'circuitgen doctor' for diagnostics.\n"
        )
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint."""
    if argv is None:
        argv = sys.argv[1:]

    # Minimum Python version enforcement (>= 3.10)
    if sys.version_info < (3, 10):
        v = sys.version_info
        sys.stderr.write(
            f"Error: CircuitGen requires Python 3.10 or newer (detected Python {v[0]}.{v[1]}.{v[2]}).\n"
        )
        return 1

    parser = build_parser()
    args = parser.parse_args(argv)

    debug_mode = getattr(args, "debug", False) or os.environ.get("CIRCUITGEN_DEBUG") == "1"

    if args.command == "setup-path":
        try:
            from circuitgen.syspath import setup_windows_path

            return setup_windows_path(yes=args.yes, check_only=args.check)
        except Exception as exc:
            if debug_mode:
                raise
            sys.stderr.write(f"Error during PATH setup: {exc}\n")
            return 1

    if args.command == "doctor":
        try:
            from circuitgen.doctor import run_doctor

            return run_doctor(debug=debug_mode)
        except Exception as exc:
            if debug_mode:
                raise
            sys.stderr.write(f"Error running diagnostics: {exc}\n")
            return 1

    # No subcommand provided: launch the interactive TUI
    return launch_tui(debug_mode=debug_mode)


if __name__ == "__main__":
    sys.exit(main())
