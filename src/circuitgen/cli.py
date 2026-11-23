"""CircuitGen command-line interface entrypoint."""
from __future__ import annotations

import argparse
import sys
from typing import Sequence

from circuitgen import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="circuitgen",
        description="CircuitGen: Circuit schematics from text descriptions or netlists.",
    )
    parser.add_argument(
        "--version",
        "-v",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show program's version number and exit.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint."""
    if argv is None:
        argv = sys.argv[1:]

    parser = build_parser()

    # If flags like --help or --version are passed, parse and exit immediately without TUI
    if argv:
        parser.parse_args(argv)
        return 0

    # No arguments passed: launch the interactive TUI
    try:
        from circuitgen.tui import CircuitGenApp

        app = CircuitGenApp()
        app.run()
        return 0
    except Exception as exc:  # pragma: no cover
        sys.stderr.write(f"Error launching CircuitGen: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
