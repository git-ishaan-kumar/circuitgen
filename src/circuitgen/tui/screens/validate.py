"""Validate workflow screens: V0 (mode selection), V1a (file), V1b (paste), results, and details."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Header, Static

from circuitgen.engine import CircuitError, validate_model
from circuitgen.erc import check_model
from circuitgen.tui.services.file_io import FileIOService
from circuitgen.tui.widgets.enhanced_input import EnhancedInput
from circuitgen.tui.widgets.json_editor import JsonEditor
from circuitgen.tui.widgets.path_picker import PathPickerModal
from circuitgen.tui.widgets.selectable_menu import MenuItem, SelectableMenu


SAFETY_NOTE = "Validation does not guarantee electrical safety."


@dataclass(frozen=True)
class NetlistCheck:
    components_count: int
    nets_count: int
    errors: list[str]
    warnings: list[str]
    checks_note: str = ""
    incomplete: bool = False

    @property
    def is_valid(self) -> bool:
        return not self.errors and not self.incomplete


def perform_validation(data: dict[str, Any]) -> NetlistCheck:
    try:
        model = validate_model(data)
    except (CircuitError, ValueError, TypeError, KeyError) as exc:
        comps = len(data.get("components", [])) if isinstance(data.get("components"), list) else 0
        nets = len(data.get("nets", [])) if isinstance(data.get("nets"), list) else 0
        return NetlistCheck(comps, nets, [str(exc)], [], "Electrical checks were skipped.")

    counts = len(model.components), len(model.nets)
    try:
        report = check_model(model)
    except Exception:
        return NetlistCheck(
            *counts, [], [], "Electrical checks could not finish.", incomplete=True
        )
    return NetlistCheck(
        *counts,
        [issue.message for issue in report.errors],
        [issue.message for issue in report.warnings],
    )


# ---------------------------------------------------------------------------
# V0 — Choose Input Mode
# ---------------------------------------------------------------------------

class ValidateModeScreen(Screen[None]):
    """V0 — Choose between file input and pasted JSON for validation."""

    BINDINGS = [
        Binding("escape", "back_home", "Home", show=False),
        Binding("q", "quit_app", "Quit", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Container(id="home-container"):
            with Vertical(id="home-card"):
                with Horizontal(classes="breadcrumb-row"):
                    yield Static("CircuitGen / Validate", classes="breadcrumb-left")
                    yield Static("Choose source", classes="breadcrumb-right")

                yield Static("─" * 62, classes="rule")
                yield Static("Choose a netlist source", classes="setup-title")

                yield SelectableMenu(
                    [
                        MenuItem("file", "Open JSON file", ""),
                        MenuItem("paste", "Paste JSON", ""),
                        MenuItem("home", "Back to home", ""),
                    ],
                    initial_index=0,
                    id="validate-mode-menu",
                )

                yield Static("─" * 62, classes="rule")
                yield Static(
                    "↑↓ Navigate  ·  Enter Select  ·  Esc Home  ·  Ctrl+Q Quit",
                    classes="keys-reminder",
                )

    def on_mount(self) -> None:
        self.query_one("#validate-mode-menu", SelectableMenu).focus()

    def on_selectable_menu_selected(self, message: SelectableMenu.Selected) -> None:
        key = message.item.key
        if key == "file":
            self.app.push_screen(ValidateFileScreen())
        elif key == "paste":
            self.app.push_screen(ValidatePasteScreen())
        elif key == "home":
            self.action_back_home()

    def action_back_home(self) -> None:
        self.app.pop_screen()

    def action_quit_app(self) -> None:
        self.app.exit()


# ---------------------------------------------------------------------------
# V1a — File Input Mode
# ---------------------------------------------------------------------------

class ValidateFileScreen(Screen[None]):
    """V1a — Validate a netlist file from disk."""

    BINDINGS = [
        Binding("escape", "back", "Back", show=False),
        Binding("q", "quit_app", "Quit", show=False),
        Binding("tab", "toggle_focus", "Toggle Focus", show=False),
    ]

    def __init__(self, initial_path: str = "./examples/led.json", **kwargs) -> None:
        super().__init__(**kwargs)
        self.initial_path = initial_path

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Container(id="home-container"):
            with Vertical(id="home-card"):
                with Horizontal(classes="breadcrumb-row"):
                    yield Static("CircuitGen / Validate / Open file", classes="breadcrumb-left")
                    yield Static("Offline", classes="breadcrumb-right")

                yield Static("─" * 62, classes="rule")

                yield Static("JSON file", classes="input-field-label")
                yield EnhancedInput(
                    placeholder="./examples/led.json",
                    value=self.initial_path,
                    id="validate-input-file",
                )

                yield Static("", id="validate-file-status", classes="status-message")

                yield SelectableMenu(
                    [
                        MenuItem("validate", "Validate netlist", ""),
                        MenuItem("browse", "Browse", ""),
                        MenuItem("back", "Back", ""),
                    ],
                    initial_index=0,
                    id="validate-file-menu",
                )

                yield Static("─" * 62, classes="rule")
                yield Static(
                    "Tab Next field  ·  Enter Select  ·  Esc Back  ·  Ctrl+Q Quit",
                    classes="keys-reminder",
                )

    def on_mount(self) -> None:
        self.query_one("#validate-input-file", EnhancedInput).focus()

    def set_status(self, msg: str) -> None:
        try:
            self.query_one("#validate-file-status", Static).update(msg)
        except Exception:
            pass

    def action_toggle_focus(self) -> None:
        inp = self.query_one("#validate-input-file", EnhancedInput)
        menu = self.query_one("#validate-file-menu", SelectableMenu)
        if inp.has_focus:
            menu.focus()
        else:
            inp.focus()

    def on_selectable_menu_selected(self, message: SelectableMenu.Selected) -> None:
        key = message.item.key
        if key == "validate":
            self._handle_validate()
        elif key == "browse":
            self._browse_file()
        elif key == "back":
            self.action_back()

    def _browse_file(self) -> None:
        current_input = self.query_one("#validate-input-file", EnhancedInput).value.strip()
        start_path = Path(current_input).parent if current_input else Path.cwd()

        def _on_picked(picked: Path | None) -> None:
            if picked:
                self.query_one("#validate-input-file", EnhancedInput).value = str(picked)

        self.app.push_screen(PathPickerModal(initial_path=start_path, mode="file", filters=[".json"]), _on_picked)

    def _handle_validate(self) -> None:
        input_path_str = self.query_one("#validate-input-file", EnhancedInput).value.strip()
        if not input_path_str:
            self.set_status("! Choose a JSON file.")
            self.query_one("#validate-input-file", EnhancedInput).focus()
            return

        data, err, _ = FileIOService.read_json_file(input_path_str)
        if err or data is None:
            self.set_status(f"× {err}")
            return

        self.app.push_screen(
            ValidateResultScreen(
                perform_validation(data),
                source_type="file",
                source_val=input_path_str,
            )
        )

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_quit_app(self) -> None:
        self.app.exit()


# ---------------------------------------------------------------------------
# V1b — Paste JSON Mode
# ---------------------------------------------------------------------------

class ValidatePasteScreen(Screen[None]):
    """V1b — Validate netlist from pasted JSON text."""

    BINDINGS = [
        Binding("escape", "back", "Back", show=False),
        Binding("q", "quit_app", "Quit", show=False),
        Binding("tab", "toggle_focus", "Toggle Focus", show=False),
    ]

    DEFAULT_NETLIST = (
        "{\n"
        '  "components": [\n'
        '    {"id": "B1", "type": "battery", "value": "9V"},\n'
        '    {"id": "R1", "type": "resistor", "value": "330Ω"},\n'
        '    {"id": "D1", "type": "led", "value": "red"}\n'
        "  ],\n"
        '  "nets": [\n'
        '    {"name": "VCC", "pins": ["B1.p", "R1.a"]},\n'
        '    {"name": "LED_POS", "pins": ["R1.b", "D1.a"]},\n'
        '    {"name": "GND", "pins": ["D1.b", "B1.n"]}\n'
        "  ]\n"
        "}"
    )

    def __init__(self, initial_text: str | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.initial_text = initial_text if initial_text is not None else self.DEFAULT_NETLIST

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Container(id="home-container"):
            with Vertical(id="home-card"):
                with Horizontal(classes="breadcrumb-row"):
                    yield Static("CircuitGen / Validate / Paste JSON", classes="breadcrumb-left")
                    yield Static("Offline", classes="breadcrumb-right")

                yield Static("─" * 62, classes="rule")
                yield Static("Paste a JSON netlist", classes="input-field-label")

                yield JsonEditor(
                    text=self.initial_text,
                    id="validate-paste-editor",
                )

                yield Static("", id="validate-paste-status", classes="status-message")

                yield SelectableMenu(
                    [
                        MenuItem("validate", "Validate netlist", ""),
                        MenuItem("clear", "Clear editor", ""),
                        MenuItem("back", "Back", ""),
                    ],
                    initial_index=0,
                    id="validate-paste-menu",
                )

                yield Static("─" * 62, classes="rule")
                yield Static(
                    "Tab Next field  ·  Enter New line  ·  Esc Back  ·  Ctrl+Q Quit",
                    classes="keys-reminder",
                )

    def on_mount(self) -> None:
        self.query_one("#validate-paste-editor", JsonEditor).focus()

    def set_status(self, msg: str) -> None:
        try:
            self.query_one("#validate-paste-status", Static).update(msg)
        except Exception:
            pass

    def action_toggle_focus(self) -> None:
        editor = self.query_one("#validate-paste-editor", JsonEditor)
        menu = self.query_one("#validate-paste-menu", SelectableMenu)
        if editor.has_focus:
            menu.focus()
        else:
            editor.focus()

    def on_selectable_menu_selected(self, message: SelectableMenu.Selected) -> None:
        key = message.item.key
        if key == "validate":
            self._handle_validate()
        elif key == "clear":
            self.query_one("#validate-paste-editor", JsonEditor).text = ""
            self.set_status("Editor cleared.")
            self.query_one("#validate-paste-editor", JsonEditor).focus()
        elif key == "back":
            self.action_back()

    def _handle_validate(self) -> None:
        editor = self.query_one("#validate-paste-editor", JsonEditor)
        raw_text = editor.text.strip()
        if not raw_text:
            self.set_status("! Paste a JSON netlist.")
            editor.focus()
            return

        data, err, _ = editor.validate_netlist()
        if err or data is None:
            self.set_status(f"× {err}")
            return

        self.app.push_screen(
            ValidateResultScreen(
                perform_validation(data),
                source_type="paste",
                source_val=editor.text,
            )
        )

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_quit_app(self) -> None:
        self.app.exit()


# ---------------------------------------------------------------------------
# Validation Result Screen (Passed / Failed)
# ---------------------------------------------------------------------------

class ValidateResultScreen(Screen[None]):
    """Validation summary screen displaying passed counts or exact error list."""

    BINDINGS = [
        Binding("escape", "back_home", "Home", show=False),
        Binding("q", "quit_app", "Quit", show=False),
    ]

    def __init__(
        self,
        check: NetlistCheck,
        source_type: str,  # "file" or "paste"
        source_val: str,   # file path or pasted text
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.check = check
        self.source_type = source_type
        self.source_val = source_val

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Container(id="home-container"):
            with Vertical(id="home-card"):
                with Horizontal(classes="breadcrumb-row"):
                    yield Static("CircuitGen / Validate", classes="breadcrumb-left")
                    yield Static("Result", classes="breadcrumb-right")

                yield Static("─" * 62, classes="rule")

                check = self.check
                if check.is_valid:
                    yield Static("✓ Validation passed", classes="setup-title")
                    with Vertical(classes="summary-card"):
                        with Horizontal(classes="summary-row"):
                            yield Static("Components", classes="summary-label")
                            yield Static(str(check.components_count), classes="summary-value")
                        with Horizontal(classes="summary-row"):
                            yield Static("Nets", classes="summary-label")
                            yield Static(str(check.nets_count), classes="summary-value")
                        with Horizontal(classes="summary-row"):
                            yield Static("Errors", classes="summary-label")
                            yield Static("0", classes="summary-value")
                        if check.warnings:
                            with Horizontal(classes="summary-row"):
                                yield Static("Warnings", classes="summary-label")
                                yield Static(str(len(check.warnings)), classes="warning-text")

                    menu_items = [
                        MenuItem("validate_another", "Validate another", ""),
                        MenuItem("home", "Back to home", ""),
                    ]
                else:
                    title = "Validation incomplete" if check.incomplete else "Validation failed"
                    yield Static(f"× {title}", classes="validation-failed-title")
                    if check.errors:
                        with Vertical(classes="error-card"):
                            for error in check.errors[:5]:
                                yield Static(Text(error), classes="error-text")
                            if len(check.errors) > 5:
                                yield Static(f"{len(check.errors) - 5} more errors in details.", classes="disclaimer-note")
                    if check.checks_note:
                        yield Static(check.checks_note, classes="warning-text")

                    edit_label = "Edit JSON" if self.source_type == "paste" else "Change file"

                    menu_items = [
                        MenuItem("details", "View details", ""),
                        MenuItem("edit", edit_label, ""),
                        MenuItem("validate_another", "Validate another", ""),
                        MenuItem("home", "Back to home", ""),
                    ]

                yield Static(SAFETY_NOTE, classes="disclaimer-note")

                yield SelectableMenu(
                    items=menu_items,
                    initial_index=0,
                    id="validate-result-menu",
                )

                yield Static("─" * 62, classes="rule")
                yield Static(
                    "↑↓ Navigate  ·  Enter Select  ·  Esc Home  ·  Ctrl+Q Quit",
                    classes="keys-reminder",
                )

    def on_mount(self) -> None:
        self.query_one("#validate-result-menu", SelectableMenu).focus()

    def on_selectable_menu_selected(self, message: SelectableMenu.Selected) -> None:
        key = message.item.key
        if key == "details":
            self.app.push_screen(ValidateDetailsScreen(self.check))
        elif key == "edit":
            if self.source_type == "paste":
                self.app.push_screen(ValidatePasteScreen(initial_text=self.source_val))
            else:
                self.app.push_screen(ValidateFileScreen(initial_path=self.source_val))
        elif key == "validate_another":
            self.app.push_screen(ValidateModeScreen())
        elif key == "home":
            self.action_back_home()

    def action_back_home(self) -> None:
        from circuitgen.tui.screens.home import HomeScreen
        self.app.push_screen(HomeScreen())

    def action_quit_app(self) -> None:
        self.app.exit()


# ---------------------------------------------------------------------------
# Detailed Error Report Screen
# ---------------------------------------------------------------------------

class ValidateDetailsScreen(Screen[None]):
    """Detailed diagnostic report view for validation errors and warnings."""

    BINDINGS = [
        Binding("escape", "back", "Back", show=False),
        Binding("q", "quit_app", "Quit", show=False),
    ]

    def __init__(self, check: NetlistCheck, **kwargs) -> None:
        super().__init__(**kwargs)
        self.check = check

    def _issue_sections(self) -> list[tuple[str, str, list[str]]]:
        return [
            ("Errors", "error", self.check.errors),
            ("Warnings", "warning", self.check.warnings),
        ]

    def _build_report_text(self) -> str:
        lines = ["CircuitGen validation"]
        for title, _, issues in self._issue_sections():
            if issues:
                lines.extend(("", f"{title} ({len(issues)})"))
                lines.extend(f"  {index}. {issue}" for index, issue in enumerate(issues, 1))
        if self.check.checks_note:
            lines.extend(("", self.check.checks_note))
        lines.extend(("", SAFETY_NOTE))
        return "\n".join(lines)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Container(id="home-container"):
            with Vertical(id="home-card"):
                with Horizontal(classes="breadcrumb-row"):
                    yield Static("CircuitGen / Validate / Details", classes="breadcrumb-left")

                yield Static("─" * 62, classes="rule")

                with Vertical(id="diag-report-container"):
                    for title, style, issues in self._issue_sections():
                        if issues:
                            yield Static(f"{title} ({len(issues)})", classes=f"diag-section-header diag-{style}-row")
                            for index, issue in enumerate(issues, 1):
                                yield Static(Text(f"{index}. {issue}"), classes=f"diag-{style}-row")
                    if self.check.checks_note:
                        yield Static(self.check.checks_note, classes="warning-text")
                    yield Static(SAFETY_NOTE, classes="disclaimer-note")

                yield Static("", id="validate-details-status", classes="status-message")

                yield SelectableMenu(
                    [
                        MenuItem("copy", "Copy report", ""),
                        MenuItem("back", "Back to summary", ""),
                    ],
                    initial_index=0,
                    id="validate-details-menu",
                )

                yield Static("─" * 62, classes="rule")
                yield Static(
                    "↑↓ Navigate  ·  Enter Select  ·  Esc Back  ·  Ctrl+Q Quit",
                    classes="keys-reminder",
                )

    def on_mount(self) -> None:
        self.query_one("#validate-details-menu", SelectableMenu).focus()

    def on_selectable_menu_selected(self, message: SelectableMenu.Selected) -> None:
        key = message.item.key
        if key == "copy":
            self.app.copy_to_clipboard(self._build_report_text())
            try:
                self.query_one("#validate-details-status", Static).update("✓ Report copied.")
            except Exception:
                pass
        elif key == "back":
            self.action_back()

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_quit_app(self) -> None:
        self.app.exit()
