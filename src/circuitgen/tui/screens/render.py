"""Render workflow screens: R0 (mode selection), R1a (file), R1b (paste), success, and netlist viewer."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Header, Static

from circuitgen.api import from_netlist, validate
from circuitgen.export import OUTPUT_FORMATS
from circuitgen.tui.services.background import run_background_stage
from circuitgen.tui.screens.confirm_dialog import CreateDirectoryModal, OverwriteModal
from circuitgen.tui.services.config import ConfigService
from circuitgen.tui.services.file_io import FileIOService
from circuitgen.tui.widgets.enhanced_input import EnhancedInput
from circuitgen.tui.widgets.json_editor import JsonEditor
from circuitgen.tui.widgets.path_picker import PathPickerModal
from circuitgen.tui.widgets.selectable_menu import MenuItem, SelectableMenu
from .processing import close_processing, show_processing


def open_file_in_system_viewer(path: Path) -> tuple[bool, str]:
    """Open a file in the host operating system's default viewer without shell injection."""
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
            return True, ""
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=True)
            return True, ""
        else:
            subprocess.run(["xdg-open", str(path)], check=True)
            return True, ""
    except Exception as exc:
        return False, f"Could not open viewer; file was saved at {path} ({exc})"


# ---------------------------------------------------------------------------
# R0 — Choose Input Mode
# ---------------------------------------------------------------------------

def schematic_path(directory: str, filename: str, output_format: str) -> Path:
    suffix = f".{output_format}"
    if Path(filename).suffix.lower().lstrip(".") in OUTPUT_FORMATS:
        filename = str(Path(filename).with_suffix(suffix))
    filename = FileIOService.sanitize_filename(filename, default_suffix=suffix)
    return Path(directory).expanduser().resolve() / filename


def confirm_output(screen: Screen, targets: list[Path], overwrite: bool,
                   proceed: Callable[[set[Path]], None]) -> None:
    directory = targets[0].parent
    try:
        for parent in (directory, *directory.parents):
            if parent.exists() and not parent.is_dir():
                screen.set_status(f"A file is blocking the output folder: {parent}")
                return
        for target in targets:
            if target.is_dir():
                screen.set_status(f"The output filename is already a folder: {target}")
                return
    except OSError:
        screen.set_status("Could not access the output folder.")
        return

    def confirm(approved: set[Path]) -> None:
        existing = next((path for path in targets if path.exists() and path not in approved), None)
        if existing is not None and overwrite:
            screen.app.push_screen(
                OverwriteModal(existing),
                lambda yes: confirm(approved | {existing}) if yes else None,
            )
        else:
            proceed(approved if overwrite else set(targets))

    if not directory.exists():
        screen.app.push_screen(CreateDirectoryModal(directory), lambda yes: confirm(set()) if yes else None)
    else:
        confirm(set())


def write_outputs(schematic: str | bytes, dest: Path, data: dict[str, Any],
                  sidecar: Path | None, approved: set[Path]) -> tuple[bool, str]:
    ok, message = FileIOService.save_output(schematic, dest, dest in approved)
    if not ok:
        return False, message
    if sidecar:
        content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        ok, message = FileIOService.save_output(content, sidecar, sidecar in approved)
        if not ok:
            return True, f"Schematic saved. Could not save JSON: {message}"
    return True, ""


def save_render(
    screen: RenderFileScreen | RenderPasteScreen,
    data: dict[str, Any],
    directory: str,
    filename: str,
    source_label: str,
    *,
    input_path: Path | None = None,
) -> None:
    config = ConfigService.load()
    try:
        dest = schematic_path(directory, filename, config.output_format)
    except (OSError, ValueError):
        screen.set_status("Enter a valid output directory and filename.")
        return
    sidecar = dest.with_suffix(".json") if config.save_netlist else None
    if sidecar and input_path and sidecar.resolve() == input_path.expanduser().resolve():
        sidecar = dest.with_suffix(".netlist.json")
        if sidecar.resolve() == input_path.expanduser().resolve():
            screen.set_status("Cannot replace the source netlist.")
            return

    def save(approved: set[Path]) -> None:
        screen.run_worker(
            _render_and_save(screen, data, dest, sidecar, approved, source_label, config),
            name="offline-render",
            group="offline-render",
            exclusive=True,
            description="Render schematic",
        )

    targets = [dest, sidecar] if sidecar else [dest]
    confirm_output(screen, targets, config.overwrite_confirmation, save)


def _read_and_validate_render(path: str):
    data, error, _ = FileIOService.read_json_file(path)
    return data, error, validate(data) if data is not None else None


def _parse_and_validate_render(text: str):
    data, error, _ = FileIOService.parse_json_netlist(text)
    return data, error, validate(data) if data is not None else None


async def _render_and_save(screen, data, dest, sidecar, approved, source_label, config) -> None:
    progress = await show_processing(screen, "Rendering and saving schematic…")
    try:
        def render_and_write():
            result = from_netlist(
                data, output=None, style=config.schematic_style(), output_format=config.output_format,
            )
            ok, message = write_outputs(result.encode(), dest, data, sidecar, approved)
            return result, ok, message

        try:
            result, ok, message = await run_background_stage(render_and_write)
        except Exception as exc:
            if screen.app.is_running and screen.is_mounted:
                screen.set_status(f"Could not render schematic: {exc}")
            return
        if not screen.app.is_running or not screen.is_mounted:
            return
        if not ok:
            screen.set_status(message)
            return
    finally:
        close_processing(screen, progress)

    notices = [message] if message else []
    if config.auto_open:
        opened, message = open_file_in_system_viewer(dest)
        if not opened:
            notices.append(message)
    result_screen = RenderSuccessScreen(
        svg_path=dest,
        input_source=source_label,
        components_count=len(result.model.components),
        nets_count=len(result.model.nets),
        netlist=data,
    )
    screen.app.push_screen(result_screen)
    result_screen.call_after_refresh(lambda: result_screen.set_status(" ".join(notices)))


class RenderModeScreen(Screen[None]):
    """R0 — Choose between file input and pasted JSON."""

    BINDINGS = [
        Binding("escape", "back_home", "Home", show=False),
        Binding("q", "quit_app", "Quit", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Container(id="home-container"):
            with Vertical(id="home-card"):
                with Horizontal(classes="breadcrumb-row"):
                    yield Static("CircuitGen / Render", classes="breadcrumb-left")
                    yield Static("Choose source", classes="breadcrumb-right")

                yield Static("─" * 62, classes="rule")
                yield Static("How would you like to provide your netlist?", classes="setup-title")

                yield SelectableMenu(
                    [
                        MenuItem("file", "Open JSON file", "Select an existing netlist file (.json) from disk"),
                        MenuItem("paste", "Paste JSON", "Paste JSON text directly into a multiline editor"),
                        MenuItem("home", "Back to home", "Return to the main menu"),
                    ],
                    initial_index=0,
                    id="render-mode-menu",
                )

                yield Static("─" * 62, classes="rule")
                yield Static(
                    "↑↓ Navigate  ·  Enter Select  ·  Esc Home  ·  Ctrl+Q Quit",
                    classes="keys-reminder",
                )

    def on_mount(self) -> None:
        self.query_one("#render-mode-menu", SelectableMenu).focus()

    def on_selectable_menu_selected(self, message: SelectableMenu.Selected) -> None:
        key = message.item.key
        if key == "file":
            self.app.push_screen(RenderFileScreen())
        elif key == "paste":
            self.app.push_screen(RenderPasteScreen())
        elif key == "home":
            self.action_back_home()

    def action_back_home(self) -> None:
        self.app.pop_screen()

    def action_quit_app(self) -> None:
        self.app.exit()


# ---------------------------------------------------------------------------
# R1a — File Input Mode
# ---------------------------------------------------------------------------

class RenderFileScreen(Screen[None]):
    """R1a — Render netlist from a local JSON file."""

    BINDINGS = [
        Binding("escape", "back", "Back", show=False),
        Binding("q", "quit_app", "Quit", show=False),
        Binding("tab", "toggle_focus", "Toggle Focus", show=False),
    ]

    def compose(self) -> ComposeResult:
        config = ConfigService.load()
        default_dir = config.default_output_dir or "."

        yield Header(show_clock=False)
        with Container(id="home-container"):
            with Vertical(id="home-card"):
                with Horizontal(classes="breadcrumb-row"):
                    yield Static("CircuitGen / Render / Open file", classes="breadcrumb-left")
                    yield Static("Offline", classes="breadcrumb-right")

                yield Static("─" * 62, classes="rule")

                yield Static("Input netlist file (.json):", classes="input-field-label")
                yield EnhancedInput(
                    placeholder="./examples/led.json",
                    value="./examples/led.json",
                    id="render-input-file",
                )

                yield Static("Output directory:", classes="input-field-label")
                yield EnhancedInput(
                    placeholder=default_dir,
                    value=default_dir,
                    id="render-output-dir",
                )

                yield Static("Filename:", classes="input-field-label")
                yield EnhancedInput(
                    placeholder=f"led.{config.output_format}",
                    value=f"led.{config.output_format}",
                    id="render-filename",
                )

                yield Static("", id="render-file-status", classes="status-message")

                yield SelectableMenu(
                    [
                        MenuItem("render", "Render schematic", "Use the selected JSON file"),
                        MenuItem("browse_file", "Browse for input file", "Open file picker to select a .json netlist"),
                        MenuItem("browse_dir", "Browse for output folder", "Open folder picker to select output directory"),
                        MenuItem("back", "Back", "Return to netlist source selection"),
                    ],
                    initial_index=0,
                    id="render-file-menu",
                )

                yield Static("─" * 62, classes="rule")
                yield Static(
                    "Tab Next field  ·  Enter Select  ·  Esc Back  ·  Ctrl+Q Quit",
                    classes="keys-reminder",
                )

    def on_mount(self) -> None:
        self.query_one("#render-input-file", EnhancedInput).focus()

    def set_status(self, msg: str) -> None:
        try:
            self.query_one("#render-file-status", Static).update(msg)
        except Exception:
            pass

    def action_toggle_focus(self) -> None:
        """Cycle focus across inputs and menu."""
        f_in = self.query_one("#render-input-file", EnhancedInput)
        d_in = self.query_one("#render-output-dir", EnhancedInput)
        n_in = self.query_one("#render-filename", EnhancedInput)
        menu = self.query_one("#render-file-menu", SelectableMenu)

        if f_in.has_focus:
            d_in.focus()
        elif d_in.has_focus:
            n_in.focus()
        elif n_in.has_focus:
            menu.focus()
        else:
            f_in.focus()

    def on_selectable_menu_selected(self, message: SelectableMenu.Selected) -> None:
        key = message.item.key
        if key == "render":
            self._handle_render()
        elif key == "browse_file":
            self._browse_file()
        elif key == "browse_dir":
            self._browse_dir()
        elif key == "back":
            self.action_back()

    def _browse_file(self) -> None:
        current_input = self.query_one("#render-input-file", EnhancedInput).value.strip()
        start_path = Path(current_input).parent if current_input else Path.cwd()

        def _on_picked(picked: Path | None) -> None:
            if picked:
                self.query_one("#render-input-file", EnhancedInput).value = str(picked)
                # Auto-suggest filename matching stem
                fn_input = self.query_one("#render-filename", EnhancedInput)
                output_format = ConfigService.load().output_format
                if fn_input.value in (f"led.{output_format}", f"circuit.{output_format}", ""):
                    fn_input.value = f"{picked.stem}.{output_format}"

        self.app.push_screen(PathPickerModal(initial_path=start_path, mode="file", filters=[".json"]), _on_picked)

    def _browse_dir(self) -> None:
        current_dir = self.query_one("#render-output-dir", EnhancedInput).value.strip() or "."
        start_path = Path(current_dir)

        def _on_picked(picked: Path | None) -> None:
            if picked:
                self.query_one("#render-output-dir", EnhancedInput).value = str(picked)

        self.app.push_screen(PathPickerModal(initial_path=start_path, mode="directory"), _on_picked)

    def _handle_render(self) -> None:
        input_path_str = self.query_one("#render-input-file", EnhancedInput).value.strip()
        output_dir_str = self.query_one("#render-output-dir", EnhancedInput).value.strip()
        filename_str = self.query_one("#render-filename", EnhancedInput).value.strip()

        if not input_path_str:
            self.set_status("! Please specify an input netlist file.")
            self.query_one("#render-input-file", EnhancedInput).focus()
            return

        if not filename_str:
            self.set_status("! Please specify an output filename.")
            self.query_one("#render-filename", EnhancedInput).focus()
            return

        self._render_file(input_path_str, output_dir_str, filename_str)

    @work(exclusive=True, description="Read and validate netlist")
    async def _render_file(self, input_path: str, directory: str, filename: str) -> None:
        progress = await show_processing(self, "Reading and validating netlist…")
        try:
            data, error, result = await run_background_stage(
                lambda: _read_and_validate_render(input_path)
            )
        except Exception as exc:
            data, error, result = None, str(exc), None
        finally:
            close_processing(self, progress)

        if not self.app.is_running or not self.is_mounted:
            return
        if error or data is None:
            self.set_status(f"× {error}")
            return
        if not result.valid:
            err_details = "\n".join(f"- {issue}" for issue in result.errors)
            self.set_status(f"× Invalid netlist\n{err_details}")
            return
        save_render(self, data, directory, filename, input_path,
                    input_path=Path(input_path))

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_quit_app(self) -> None:
        self.app.exit()


# ---------------------------------------------------------------------------
# R1b — Paste JSON Mode
# ---------------------------------------------------------------------------

class RenderPasteScreen(Screen[None]):
    """R1b — Render netlist from pasted JSON text."""

    BINDINGS = [
        Binding("escape", "back", "Back", show=False),
        Binding("q", "quit_app", "Quit", show=False),
        Binding("tab", "toggle_focus", "Toggle Focus", show=False),
    ]

    def compose(self) -> ComposeResult:
        config = ConfigService.load()
        default_dir = config.default_output_dir or "."

        yield Header(show_clock=False)
        with Container(id="home-container"):
            with Vertical(id="home-card"):
                with Horizontal(classes="breadcrumb-row"):
                    yield Static("CircuitGen / Render / Paste JSON", classes="breadcrumb-left")
                    yield Static("Offline", classes="breadcrumb-right")

                yield Static("─" * 62, classes="rule")
                yield Static("Paste your JSON netlist below:", classes="input-field-label")

                yield JsonEditor(
                    text="{\n  \"components\": [\n    {\"id\": \"B1\", \"type\": \"battery\", \"value\": \"9V\"},\n    {\"id\": \"R1\", \"type\": \"resistor\", \"value\": \"330Ω\"},\n    {\"id\": \"D1\", \"type\": \"led\", \"value\": \"red\"}\n  ],\n  \"nets\": [\n    {\"name\": \"VCC\", \"pins\": [\"B1.p\", \"R1.a\"]},\n    {\"name\": \"LED_POS\", \"pins\": [\"R1.b\", \"D1.a\"]},\n    {\"name\": \"GND\", \"pins\": [\"D1.b\", \"B1.n\"]}\n  ]\n}",
                    id="render-paste-editor",
                )

                yield Static("Output directory:", classes="input-field-label")
                yield EnhancedInput(
                    placeholder=default_dir,
                    value=default_dir,
                    id="render-paste-output-dir",
                )

                yield Static("Filename:", classes="input-field-label")
                yield EnhancedInput(
                    placeholder=f"circuit.{config.output_format}",
                    value=f"circuit.{config.output_format}",
                    id="render-paste-filename",
                )

                yield Static("", id="render-paste-status", classes="status-message")

                yield SelectableMenu(
                    [
                        MenuItem("render", "Render schematic", "Use the pasted JSON"),
                        MenuItem("browse_dir", "Browse for output folder", "Open folder picker to select output directory"),
                        MenuItem("clear", "Clear editor", "Clear the JSON editor text"),
                        MenuItem("back", "Back", "Return to netlist source selection"),
                    ],
                    initial_index=0,
                    id="render-paste-menu",
                )

                yield Static("─" * 62, classes="rule")
                yield Static(
                    "Tab Next field  ·  Enter New line  ·  Esc Back  ·  Ctrl+Q Quit",
                    classes="keys-reminder",
                )

    def on_mount(self) -> None:
        self.query_one("#render-paste-editor", JsonEditor).focus()

    def set_status(self, msg: str) -> None:
        try:
            self.query_one("#render-paste-status", Static).update(msg)
        except Exception:
            pass

    def action_toggle_focus(self) -> None:
        editor = self.query_one("#render-paste-editor", JsonEditor)
        d_in = self.query_one("#render-paste-output-dir", EnhancedInput)
        n_in = self.query_one("#render-paste-filename", EnhancedInput)
        menu = self.query_one("#render-paste-menu", SelectableMenu)

        if editor.has_focus:
            d_in.focus()
        elif d_in.has_focus:
            n_in.focus()
        elif n_in.has_focus:
            menu.focus()
        else:
            editor.focus()

    def on_selectable_menu_selected(self, message: SelectableMenu.Selected) -> None:
        key = message.item.key
        if key == "render":
            self._handle_render()
        elif key == "browse_dir":
            self._browse_dir()
        elif key == "clear":
            self.query_one("#render-paste-editor", JsonEditor).text = ""
            self.set_status("Editor cleared.")
            self.query_one("#render-paste-editor", JsonEditor).focus()
        elif key == "back":
            self.action_back()

    def _browse_dir(self) -> None:
        current_dir = self.query_one("#render-paste-output-dir", EnhancedInput).value.strip() or "."
        start_path = Path(current_dir)

        def _on_picked(picked: Path | None) -> None:
            if picked:
                self.query_one("#render-paste-output-dir", EnhancedInput).value = str(picked)

        self.app.push_screen(PathPickerModal(initial_path=start_path, mode="directory"), _on_picked)

    def _handle_render(self) -> None:
        editor = self.query_one("#render-paste-editor", JsonEditor)
        output_dir_str = self.query_one("#render-paste-output-dir", EnhancedInput).value.strip()
        filename_str = self.query_one("#render-paste-filename", EnhancedInput).value.strip()

        if not editor.text.strip():
            self.set_status("! Please paste a JSON netlist.")
            editor.focus()
            return

        if not filename_str:
            self.set_status("! Please specify an output filename.")
            self.query_one("#render-paste-filename", EnhancedInput).focus()
            return

        self._render_paste(editor.text, output_dir_str, filename_str)

    @work(exclusive=True, description="Validate pasted netlist")
    async def _render_paste(self, raw_text: str, directory: str, filename: str) -> None:
        progress = await show_processing(self, "Checking JSON and connections…")
        try:
            data, error, result = await run_background_stage(
                lambda: _parse_and_validate_render(raw_text)
            )
        except Exception as exc:
            data, error, result = None, str(exc), None
        finally:
            close_processing(self, progress)

        if not self.app.is_running or not self.is_mounted:
            return
        if error or data is None:
            self.set_status(f"× {error}")
            return
        if not result.valid:
            err_details = "\n".join(f"- {issue}" for issue in result.errors)
            self.set_status(f"× Invalid netlist\n{err_details}")
            return
        save_render(self, data, directory, filename, "Pasted JSON")

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_quit_app(self) -> None:
        self.app.exit()


# ---------------------------------------------------------------------------
# Render Success Screen
# ---------------------------------------------------------------------------

class RenderSuccessScreen(Screen[None]):
    """View displayed upon successful schematic rendering."""

    BINDINGS = [
        Binding("escape", "back_home", "Home", show=False),
        Binding("q", "quit_app", "Quit", show=False),
    ]

    def __init__(
        self,
        svg_path: Path,
        input_source: str,
        components_count: int,
        nets_count: int,
        netlist: dict[str, Any],
        *,
        ai_source: tuple[str, str] | None = None,
        assumptions: tuple[str, ...] = (),
        another: Callable[[], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.svg_path = svg_path
        self.input_source = input_source
        self.components_count = components_count
        self.nets_count = nets_count
        self.netlist = netlist
        self.ai_source = ai_source
        self.assumptions = assumptions
        self.another = another

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Container(id="home-container"):
            with Vertical(id="home-card"):
                with Horizontal(classes="breadcrumb-row"):
                    workflow = "Generate" if self.ai_source else "Render"
                    yield Static(f"CircuitGen / {workflow}", classes="breadcrumb-left")
                    yield Static("Success", classes="breadcrumb-right")

                yield Static("─" * 62, classes="rule")
                title = "Schematic generated and saved" if self.ai_source else "Schematic rendered successfully"
                yield Static(f"✓ {title}", classes="setup-title")

                with Vertical(classes="summary-card"):
                    with Horizontal(classes="summary-row"):
                        yield Static("File", classes="summary-label")
                        yield Static(str(self.svg_path), classes="summary-value", markup=False)
                    source = (
                        list(zip(("Provider", "Model"), self.ai_source))
                        if self.ai_source else [("Input", self.input_source)]
                    )
                    for label, value in source:
                        with Horizontal(classes="summary-row"):
                            yield Static(label, classes="summary-label")
                            yield Static(value, classes="summary-value", markup=False)
                    with Horizontal(classes="summary-row"):
                        yield Static("Components", classes="summary-label")
                        yield Static(str(self.components_count), classes="summary-value")
                    with Horizontal(classes="summary-row"):
                        yield Static("Nets", classes="summary-label")
                        yield Static(str(self.nets_count), classes="summary-value")

                yield Static("", id="render-success-status", classes="status-message", markup=False)
                if self.assumptions:
                    yield Static("Assumptions used", classes="input-field-label")
                    for assumption in self.assumptions:
                        yield Static(f"• {assumption}", markup=False)

                yield SelectableMenu(
                    [
                        MenuItem("open", "Open schematic", "Open in the default viewer"),
                        MenuItem("view_netlist", "View netlist", "Inspect the rendered JSON netlist"),
                        MenuItem("render_another", f"{workflow} another", ""),
                        MenuItem("home", "Back to home", "Return to the main menu"),
                    ],
                    initial_index=0,
                    id="render-success-menu",
                )

                yield Static("─" * 62, classes="rule")
                yield Static(
                    "↑↓ Navigate  ·  Enter Select  ·  Esc Home  ·  Ctrl+Q Quit",
                    classes="keys-reminder",
                )

    def on_mount(self) -> None:
        self.query_one("#render-success-menu", SelectableMenu).focus()

    def show_saved_status(self, message: str, auto_open: bool) -> None:
        self.set_status(message)
        if auto_open:
            self._open_schematic(message)

    @work(exclusive=True)
    async def _open_schematic(self, message: str = "") -> None:
        ok, error = await asyncio.to_thread(open_file_in_system_viewer, self.svg_path)
        status = "Opened schematic." if ok else error
        self.set_status(" ".join(filter(None, (message, status))))

    def set_status(self, msg: str) -> None:
        try:
            self.query_one("#render-success-status", Static).update(msg)
        except Exception:
            pass

    def on_selectable_menu_selected(self, message: SelectableMenu.Selected) -> None:
        key = message.item.key
        if key == "open":
            self._open_schematic()
        elif key == "view_netlist":
            self.app.push_screen(ViewNetlistScreen(netlist=self.netlist, source_file=self.svg_path.stem))
        elif key == "render_another":
            if self.another is not None:
                self.another()
            else:
                self.app.push_screen(RenderModeScreen())
        elif key == "home":
            self.action_back_home()

    def action_back_home(self) -> None:
        from circuitgen.tui.screens.home import HomeScreen
        if self.ai_source:
            self.app.pop_screen()
        else:
            self.app.push_screen(HomeScreen())

    def action_quit_app(self) -> None:
        self.app.exit()


# ---------------------------------------------------------------------------
# View Netlist Screen (Read-Only)
# ---------------------------------------------------------------------------

class ViewNetlistScreen(Screen[None]):
    """Read-only scrollable view of the netlist JSON."""

    BINDINGS = [
        Binding("escape", "back", "Back", show=False),
        Binding("q", "quit_app", "Quit", show=False),
    ]

    def __init__(self, netlist: dict[str, Any], source_file: str = "circuit", *,
                 notice: str | None = None, back_label: str = "Back to schematic result",
                 **kwargs) -> None:
        super().__init__(**kwargs)
        self.netlist = netlist
        self.source_file = source_file
        self.notice = notice
        self.back_label = back_label

    def compose(self) -> ComposeResult:
        json_str = json.dumps(self.netlist, indent=2)

        yield Header(show_clock=False)
        with Container(id="home-container"):
            with Vertical(id="home-card"):
                with Horizontal(classes="breadcrumb-row"):
                    yield Static("CircuitGen / Netlist", classes="breadcrumb-left")
                    yield Static(self.source_file, classes="breadcrumb-right")

                yield Static("─" * 62, classes="rule")
                yield Static("Netlist Structure:", classes="input-field-label")
                if self.notice:
                    yield Static(self.notice, id="netlist-view-notice", classes="status-message")

                yield JsonEditor(text=json_str, id="netlist-viewer-editor")
                yield Static("", id="netlist-view-status", classes="status-message")

                yield SelectableMenu(
                    [
                        MenuItem("copy", "Copy JSON to clipboard", "Copy the full netlist to system clipboard"),
                        MenuItem("back", self.back_label, "Return to the previous screen"),
                    ],
                    initial_index=0,
                    id="netlist-view-menu",
                )

                yield Static("─" * 62, classes="rule")
                yield Static(
                    "↑↓ Navigate  ·  Enter Select  ·  Esc Back  ·  Ctrl+Q Quit",
                    classes="keys-reminder",
                )

    def on_mount(self) -> None:
        editor = self.query_one("#netlist-viewer-editor", JsonEditor)
        editor.read_only = True
        self.query_one("#netlist-view-menu", SelectableMenu).focus()

    def on_selectable_menu_selected(self, message: SelectableMenu.Selected) -> None:
        key = message.item.key
        if key == "copy":
            self.app.copy_to_clipboard(json.dumps(self.netlist, indent=2))
            try:
                self.query_one("#netlist-view-status", Static).update("✓ JSON copied to clipboard.")
            except Exception:
                pass
        elif key == "back":
            self.action_back()

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_quit_app(self) -> None:
        self.app.exit()
