"""CircuitGen command-line interface.

Every drawing command reads a netlist from a path or from ``-`` (standard
input), writes its result to stdout unless ``-o`` is given, and reports what it
did on stderr so that ``circuitgen render n.json > out.svg`` keeps stdout clean.

Exit codes: 0 success, 1 the netlist was read but is not a usable circuit,
2 the arguments are wrong or the input could not be read.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from circuitgen import __version__
from circuitgen.colors import normalize_color
from circuitgen.engine import CircuitError
from circuitgen.routing import RoutingError

EXIT_OK = 0
EXIT_REJECTED = 1
EXIT_USAGE = 2

STDIN_NAME = "standard input"
STDOUT_NAME = "standard output"

EPILOG = """\
examples:
  circuitgen render examples/wheatstone.json -o wheatstone.svg
  circuitgen render - < netlist.json > schematic.svg
  circuitgen validate examples/controller.json
  circuitgen erc examples/erc_issues.json --fail-on-warning
  circuitgen symbols ne555 -o ne555.svg

With no command, circuitgen opens its interactive terminal app."""


class CommandError(Exception):
    """A command stopped early; carries the exit code to report."""

    def __init__(self, message: str, code: int = EXIT_REJECTED) -> None:
        super().__init__(message)
        self.code = code


# SHARED HELPERS

def _read_text(source: str) -> str:
    if source == "-":
        return sys.stdin.read()
    try:
        return Path(source).read_text(encoding="utf-8")
    except OSError as error:
        raise CommandError(f"cannot read {source}: {error.strerror or error}",
                           EXIT_USAGE) from error


def _load_netlist(source: str) -> dict[str, Any]:
    """Read a netlist document from a path or standard input."""
    label = STDIN_NAME if source == "-" else source
    try:
        document = json.loads(_read_text(source))
    except ValueError as error:
        raise CommandError(f"{label} is not valid JSON: {error}") from error
    if not isinstance(document, dict):
        raise CommandError(f"{label} must contain a JSON object") from None
    return document


def _write_result(artwork: str, output: str | None) -> str | None:
    """Write artwork to a file or stdout; returns the path written, if any."""
    if output in (None, "-"):
        sys.stdout.write(artwork)
        return None
    destination = Path(output)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(artwork, encoding="utf-8")
    except OSError as error:
        raise CommandError(f"cannot write {output}: {error.strerror or error}",
                           EXIT_USAGE) from error
    return str(destination)


def _color_argument(value: str) -> str:
    try:
        return normalize_color(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


# COMMANDS

def _render(arguments: argparse.Namespace) -> int:
    from circuitgen import from_netlist

    netlist = _load_netlist(arguments.netlist)
    try:
        result = from_netlist(netlist, optimize=arguments.optimize, color=arguments.color)
    except (CircuitError, RoutingError) as error:
        raise CommandError(str(error)) from error
    target = _write_result(result.svg, arguments.output)
    if not arguments.quiet:
        model = result.model
        summary = (f"{len(model.components)} components, {len(model.nets)} nets"
                   if model is not None else "netlist")
        destination = target if target is not None else STDOUT_NAME
        sys.stderr.write(f"rendered {summary} -> {destination} "
                         f"({len(result.svg)} bytes)\n")
    return EXIT_OK


def _validate(arguments: argparse.Namespace) -> int:
    from circuitgen import validate as check_netlist

    netlist = _load_netlist(arguments.netlist)
    result = check_netlist(netlist)
    model = result.model
    if arguments.json:
        report: dict[str, Any] = {"valid": result.valid, "errors": result.errors}
        if model is not None:
            report["components"] = len(model.components)
            report["nets"] = len(model.nets)
        print(json.dumps(report, indent=2))
    elif result.valid and model is not None:
        print(f"OK: {len(model.components)} components, {len(model.nets)} nets")
    else:
        for message in result.errors:
            print(f"error: {message}")
    return EXIT_OK if result.valid else EXIT_REJECTED


def _erc(arguments: argparse.Namespace) -> int:
    from circuitgen.erc import run

    return run(arguments.netlist, as_json=arguments.json,
               fail_on_warning=arguments.fail_on_warning)


def _symbols(arguments: argparse.Namespace) -> int:
    from circuitgen.symbols import BUILTIN_SYMBOLS, make_symbol_svg

    if arguments.kind is None:
        if arguments.json:
            print(json.dumps([{"kind": kind, "pins": list(symbol.pin_names)}
                              for kind, symbol in sorted(BUILTIN_SYMBOLS.items())],
                             indent=2))
        else:
            for kind, symbol in sorted(BUILTIN_SYMBOLS.items()):
                print(f"{kind:14s} {' '.join(symbol.pin_names)}")
        return EXIT_OK
    pins = [pin.strip() for pin in arguments.pins.split(",")] if arguments.pins else None
    try:
        artwork = make_symbol_svg(arguments.kind, arguments.value, "U1", pins,
                                  arguments.rotation, arguments.mirror)
    except ValueError as error:
        raise CommandError(f"{arguments.kind}: {error}", EXIT_USAGE) from error
    target = _write_result(artwork, arguments.output)
    if target is not None and not arguments.quiet:
        sys.stderr.write(f"wrote {arguments.kind} symbol -> {target}\n")
    return EXIT_OK


# PARSER

def _add_render(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "render", help="draw a netlist as an SVG schematic",
        description="Draw a netlist as an SVG schematic.",
        epilog="Without -o the SVG is written to stdout; the summary goes to stderr.",
    )
    parser.add_argument("netlist", metavar="NETLIST", help="netlist JSON file, or - for stdin")
    parser.add_argument("--output", "-o", metavar="PATH", help="write the SVG here instead of stdout")
    parser.add_argument("--color", type=_color_argument, default="#000000", metavar="HEX",
                        help="ink color as #rrggbb (default: #000000)")
    parser.add_argument("--optimize", action="store_true",
                        help="try verified compact placements for routed drawings")
    parser.add_argument("--quiet", "-q", action="store_true", help="do not report the summary")
    parser.set_defaults(handler=_render)


def _add_validate(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "validate", help="check a netlist without drawing it",
        description="Check that a netlist is structurally valid and fully connected. "
                    "Drawing problems are reported by render.",
    )
    parser.add_argument("netlist", metavar="NETLIST", help="netlist JSON file, or - for stdin")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    parser.set_defaults(handler=_validate)


def _add_erc(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "erc", help="run electrical rule checks on a netlist",
        description="Run conservative electrical rule checks "
                    "(floating pins, shorts, supply conflicts).",
    )
    parser.add_argument("netlist", metavar="NETLIST", help="netlist JSON file, or - for stdin")
    parser.add_argument("--json", action="store_true", help="print a structured JSON report")
    parser.add_argument("--fail-on-warning", action="store_true",
                        help="exit non-zero when warnings are present")
    parser.set_defaults(handler=_erc)


def _add_symbols(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "symbols", help="list built-in symbols or draw one",
        description="List built-in component symbols, or draw one of them as an SVG.",
    )
    parser.add_argument("kind", metavar="KIND", nargs="?",
                        help="component type to draw; omit to list every built-in type")
    parser.add_argument("--pins", metavar="NAMES",
                        help="comma-separated pin names for a custom symbol")
    parser.add_argument("--value", default="", metavar="TEXT", help="value label")
    parser.add_argument("--rotation", type=int, default=0, choices=(0, 90, 180, 270),
                        help="rotation in degrees (default: 0)")
    parser.add_argument("--mirror", action="store_true", help="mirror horizontally")
    parser.add_argument("--output", "-o", metavar="PATH", help="write the SVG here instead of stdout")
    parser.add_argument("--quiet", "-q", action="store_true", help="do not report the summary")
    parser.add_argument("--json", action="store_true",
                        help="list built-in symbols as JSON (ignored when drawing)")
    parser.set_defaults(handler=_symbols)


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="circuitgen",
        description="CircuitGen: Circuit schematics from text or netlists.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        "-v",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show program's version number and exit.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND", title="commands")
    _add_render(subparsers)
    _add_validate(subparsers)
    _add_erc(subparsers)
    _add_symbols(subparsers)
    return parser


# ENTRYPOINT

def _launch_app() -> int:
    """Open the interactive terminal app, which needs a real terminal."""
    if not sys.stdin.isatty():
        sys.stderr.write(
            "CircuitGen's interactive app needs a terminal.\n"
            "Use a command instead: circuitgen render|validate|erc|symbols (see --help).\n"
        )
        return EXIT_USAGE
    try:
        from circuitgen.tui import CircuitGenApp

        app = CircuitGenApp()
        app.run()
        return EXIT_OK
    except Exception as exc:  # pragma: no cover
        sys.stderr.write(f"Error launching CircuitGen: {exc}\n")
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint: dispatch a command, or open the app with no arguments."""
    if argv is None:
        argv = sys.argv[1:]
    parser = build_parser()

    # Flags such as --help and --version exit from parse_args, like any argparse app.
    if not argv:
        return _launch_app()
    arguments = parser.parse_args(argv)
    handler = getattr(arguments, "handler", None)
    if handler is None:
        parser.print_help(sys.stderr)
        return EXIT_USAGE
    try:
        return handler(arguments)
    except CommandError as error:
        sys.stderr.write(f"circuitgen {getattr(arguments, 'command', '')}: {error}\n")
        return error.code
    except BrokenPipeError:
        # The reader closed the pipe (e.g. `... | head`); exit without a traceback.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
