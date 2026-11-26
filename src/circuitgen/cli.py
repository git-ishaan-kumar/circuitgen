"""CircuitGen command-line interface entrypoint."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Sequence


def get_version() -> str:
    """Return the version of the code being run."""
    try:
        from circuitgen import __version__

        return __version__
    except Exception:
        pass
    try:
        from importlib.metadata import version

        return version("circuitgen")
    except Exception:
        return "0.2.0"


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI argument parser with subcommands."""
    version_str = get_version()
    parser = argparse.ArgumentParser(
        prog="circuit",
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
    parser.add_argument("--no-color", action="store_true", help="Use plain text output.")

    subparsers = parser.add_subparsers(
        dest="command",
        title="Subcommands",
        description="Diagnostic and configuration commands (omit all arguments to launch interactive TUI)",
    )

    # setup-path subcommand
    setup_parser = subparsers.add_parser(
        "setup-path",
        help="Diagnose and configure Windows persistent User PATH for circuit.",
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

    generate_parser = subparsers.add_parser("generate", help="Make a schematic from a description.")
    generate_parser.add_argument("description", nargs="?", help="Circuit description.")
    generate_parser.add_argument("--stdin", action="store_true", help="Read the description from standard input.")
    generate_parser.add_argument("-o", "--output", help="Output file (default: circuit.<format> in this folder).")
    generate_parser.add_argument("--provider", help="AI provider ID; defaults to Settings.")
    generate_parser.add_argument("--model", help="Exact model ID; defaults to Settings.")
    generate_parser.add_argument("--force", action="store_true", help="Replace an existing output file.")
    generate_parser.add_argument("--no-color", action="store_true", help="Use plain text output.")

    render_parser = subparsers.add_parser("render", help="Make a schematic from a JSON netlist.")
    render_parser.add_argument("input", nargs="?", help="JSON netlist file.")
    render_parser.add_argument("--stdin", action="store_true", help="Read JSON from standard input.")
    render_parser.add_argument("-o", "--output", help="Output file (default: circuit.<format> in this folder).")
    render_parser.add_argument("--force", action="store_true", help="Replace an existing output file.")
    render_parser.add_argument("--no-color", action="store_true", help="Use plain text output.")

    validate_parser = subparsers.add_parser("validate", help="Check a JSON netlist.")
    validate_parser.add_argument("input", nargs="?", help="JSON netlist file.")
    validate_parser.add_argument("--stdin", action="store_true", help="Read JSON from standard input.")
    validate_parser.add_argument("--no-color", action="store_true", help="Use plain text output.")

    config_parser = subparsers.add_parser("config", help="Open Settings or show saved preferences.")
    config_parser.add_argument("--show", action="store_true", help="Show preferences without API keys.")
    config_parser.add_argument("--no-color", action="store_true", help="Use plain text output.")
    help_parser = subparsers.add_parser("help", help="Show command help.")
    help_parser.add_argument("topic", nargs="?", choices=("generate", "render", "validate", "config"))
    help_parser.add_argument("--no-color", action="store_true", help="Use plain text output.")

    return parser


def launch_tui(debug_mode: bool = False, start_screen: str = "home",
               no_color: bool = False) -> int:
    """Validate terminal capabilities and launch the Textual interactive TUI."""
    # Terminal capability check for interactive use
    is_interactive = sys.stdin.isatty() and sys.stdout.isatty()
    # Allow bypass during automated testing or explicit force flag
    testing = "PYTEST_CURRENT_TEST" in os.environ or "CIRCUITGEN_FORCE_TUI" in os.environ
    if not is_interactive and not testing:
        sys.stderr.write(
            "Error: CircuitGen interactive TUI requires an interactive terminal.\n"
            "Run 'circuit --help' for available CLI options or 'circuit doctor' for diagnostics.\n"
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

        options = {}
        if start_screen != "home":
            options["start_screen"] = start_screen
        if no_color:
            options["force_no_color"] = True
        app = CircuitGenApp(**options)
        app.run()
        return 0
    except KeyboardInterrupt:
        return 130
    except (ImportError, ModuleNotFoundError) as exc:
        sys.stderr.write(
            f"Error: Missing required dependency ({exc}).\n"
            "Please run 'python -m pip install circuitgen' or 'circuit doctor' for diagnostics.\n"
        )
        return 1
    except Exception as exc:
        if debug_mode or os.environ.get("CIRCUITGEN_DEBUG") == "1":
            raise
        sys.stderr.write(
            f"Error launching CircuitGen: {exc}\n"
            "Run with --debug or run 'circuit doctor' for diagnostics.\n"
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

    if args.command == "help":
        if args.topic:
            build_parser()._subparsers._group_actions[0].choices[args.topic].print_help()
        else:
            parser.print_help()
        return 0

    if args.command in ("generate", "render", "validate"):
        return _run_direct(args, parser)

    if args.command == "config":
        if args.show or not (sys.stdin.isatty() and sys.stdout.isatty()):
            from circuitgen.tui.services.config import ConfigService
            config = ConfigService.load()
            data = {key: value for key, value in config.to_dict().items() if "key" not in key.lower()}
            sys.stdout.write(json.dumps(data, indent=2) + "\n")
            return 0
        return launch_tui(debug_mode=debug_mode, start_screen="settings", no_color=args.no_color)

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
    return launch_tui(debug_mode=debug_mode, no_color=args.no_color)


def _run_direct(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from circuitgen import CircuitError, from_netlist, validate
    from circuitgen.ai import generate_netlist
    from circuitgen.tui.services.config import ConfigService
    from circuitgen.tui.services.file_io import FileIOService

    if args.command == "generate":
        if bool(args.description) == bool(args.stdin):
            parser.error("generate needs a description or --stdin")
    elif bool(args.input) == bool(args.stdin):
        parser.error(f"{args.command} needs a JSON file or --stdin")
    try:
        if args.command == "generate":
            description = sys.stdin.read() if args.stdin else args.description
            if not description.strip():
                raise ValueError("Enter a circuit description.")
            config = ConfigService.load()
            provider = args.provider or config.default_provider
            model = args.model or (config.explicit_model if provider == config.default_provider
                                   and config.model_mode == "manual" else None)
        else:
            text = sys.stdin.read() if args.stdin else Path(args.input).read_text(encoding="utf-8")
            if len(text.encode("utf-8")) > FileIOService.MAX_JSON_BYTES:
                raise ValueError("Netlist is too large.")
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at line {exc.lineno}, column {exc.colno}.") from None
            if not isinstance(data, dict):
                raise ValueError("Netlist JSON must be an object.")
            if args.command == "validate":
                result = validate(data)
                if result.valid:
                    sys.stdout.write("Netlist is valid.\n")
                    return 0
                for error in result.errors:
                    sys.stderr.write(f"Error: {error}\n")
                return 1

        config = ConfigService.load()
        destination = Path(args.output or f"circuit.{config.output_format}").expanduser().resolve()
        if destination.exists() and not args.force:
            raise ValueError(f"File already exists: {destination}. Use --force to replace it.")
        if destination.suffix.lower() not in (".svg", ".png", ".pdf"):
            raise ValueError("Output filename must end in .svg, .png, or .pdf.")
        if args.command == "generate":
            actual_model = []
            netlist = generate_netlist(description, provider=provider, model=model,
                                       retry_transient=config.retry_transient,
                                       allow_model_fallback=config.fallback_policy == "auto",
                                       clarify=config.essential_clarifications,
                                       timeout=config.request_timeout, on_model=actual_model.append)
            result = from_netlist(netlist, output=None, style=config.schematic_style(),
                                  output_format=destination.suffix[1:])
        else:
            result = from_netlist(data, output=None, style=config.schematic_style(),
                                  output_format=destination.suffix[1:])
        ok, message = FileIOService.save_output(result.encode(), destination, args.force)
        if not ok:
            raise OSError(message)
        sys.stdout.write(f"Saved {destination}\n")
        if args.command == "generate" and actual_model:
            sys.stdout.write(f"Model: {actual_model[0]}\n")
        return 0
    except (CircuitError, OSError, UnicodeError, ValueError) as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
