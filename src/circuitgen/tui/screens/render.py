"""Render workflow screens: R0 (mode selection), R1a (file), R1b (paste), success, and netlist viewer."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Header, Static

from circuitgen.api import from_netlist, validate
from circuitgen.tui.screens.confirm_dialog import CreateDirectoryModal, OverwriteModal
from circuitgen.tui.services.config import ConfigService
from circuitgen.tui.services.file_io import FileIOService
from circuitgen.tui.widgets.enhanced_input import EnhancedInput
from circuitgen.tui.widgets.json_editor import JsonEditor
from circuitgen.tui.widgets.path_picker import PathPickerModal
from circuitgen.tui.widgets.selectable_menu import MenuItem, SelectableMenu


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

class RenderModeScreen(Screen[None]):
    """R0 — Choose between file input and pasted JSON."""

    BINDINGS = [
        Binding("escape", "back_home", "Home", show=False),
        Binding("ctrl+q", "quit_app", "Quit", show=False, priority=True),
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
        Binding("ctrl+q", "quit_app", "Quit", show=False, priority=True),
        Binding("q", "quit_app", "Quit", show=False),
        Binding("tab", "toggle_focus", "Toggle Focus", show=False),
    ]

    def compose(self) -> ComposeResult:
        config = ConfigService.load()
        default_dir = config.default_output_dir or "./output/"

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
                    placeholder="led.svg",
                    value="led.svg",
                    id="render-filename",
                )

                yield Static("", id="render-file-status", classes="status-message")

                yield SelectableMenu(
                    [
                        MenuItem("render", "Render schematic", "Generate SVG schematic from selected netlist file"),
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
                if fn_input.value in ("led.svg", "circuit.svg", ""):
                    fn_input.value = f"{picked.stem}.svg"

        self.app.push_screen(PathPickerModal(initial_path=start_path, mode="file", filters=[".json"]), _on_picked)

    def _browse_dir(self) -> None:
        current_dir = self.query_one("#render-output-dir", EnhancedInput).value.strip() or "./output/"
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

        if not output_dir_str:
            self.set_status("! Please specify an output directory.")
            self.query_one("#render-output-dir", EnhancedInput).focus()
            return

        if not filename_str:
            self.set_status("! Please specify an output filename.")
            self.query_one("#render-filename", EnhancedInput).focus()
            return

        self.set_status("Reading netlist file...")
        data, err, _ = FileIOService.read_json_file(input_path_str)
        if err or data is None:
            self.set_status(f"× {err}")
            return

        # Validate with circuit engine
        val_res = validate(data)
        if not val_res.valid:
            err_details = "\n".join(f"- {e}" for e in val_res.errors)
            self.set_status(f"× Invalid netlist\n{err_details}")
            return

        dest = FileIOService.resolve_output_path(output_dir_str, filename_str)
        config = ConfigService.load()
        status = FileIOService.check_destination(dest, confirm_overwrite=config.overwrite_confirmation)

        if status == "missing_directory":
            def _on_dir_confirm(created: bool | None) -> None:
                if created:
                    FileIOService.ensure_directory(dest.parent)
                    self._execute_render_save(data, dest, input_path_str)
            self.app.push_screen(CreateDirectoryModal(dest.parent), _on_dir_confirm)
            return

        if status == "needs_overwrite_confirm":
            def _on_overwrite_confirm(confirmed: bool | None) -> None:
                if confirmed:
                    self._execute_render_save(data, dest, input_path_str)
            self.app.push_screen(OverwriteModal(dest), _on_overwrite_confirm)
            return

        self._execute_render_save(data, dest, input_path_str)

    def _execute_render_save(self, data: dict[str, Any], dest: Path, source_label: str) -> None:
        try:
            result = from_netlist(data)
        except Exception as exc:
            self.set_status(f"× Engine rendering failed: {exc}")
            return

        ok, msg = FileIOService.save_svg_safely(result.svg, dest, allow_overwrite=True)
        if not ok:
            self.set_status(f"× {msg}")
            return

        comps_count = len(result.model.components) if result.model else len(data.get("components", []))
        nets_count = len(result.model.nets) if result.model else len(data.get("nets", []))

        self.app.push_screen(
            RenderSuccessScreen(
                svg_path=dest,
                input_source=source_label,
                components_count=comps_count,
                nets_count=nets_count,
                netlist=data,
            )
        )

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
        Binding("ctrl+q", "quit_app", "Quit", show=False, priority=True),
        Binding("q", "quit_app", "Quit", show=False),
        Binding("tab", "toggle_focus", "Toggle Focus", show=False),
    ]

    def compose(self) -> ComposeResult:
        config = ConfigService.load()
        default_dir = config.default_output_dir or "./output/"

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
                    placeholder="circuit.svg",
                    value="circuit.svg",
                    id="render-paste-filename",
                )

                yield Static("", id="render-paste-status", classes="status-message")

                yield SelectableMenu(
                    [
                        MenuItem("render", "Render schematic", "Validate and generate SVG schematic from pasted JSON"),
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
        current_dir = self.query_one("#render-paste-output-dir", EnhancedInput).value.strip() or "./output/"
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

        if not output_dir_str:
            self.set_status("! Please specify an output directory.")
            self.query_one("#render-paste-output-dir", EnhancedInput).focus()
            return

        if not filename_str:
            self.set_status("! Please specify an output filename.")
            self.query_one("#render-paste-filename", EnhancedInput).focus()
            return

        self.set_status("Validating netlist...")
        data, err, _ = editor.validate_netlist()
        if err or data is None:
            self.set_status(f"× {err}")
            return

        val_res = validate(data)
        if not val_res.valid:
            err_details = "\n".join(f"- {e}" for e in val_res.errors)
            self.set_status(f"× Invalid netlist\n{err_details}")
            return

        dest = FileIOService.resolve_output_path(output_dir_str, filename_str)
        config = ConfigService.load()
        status = FileIOService.check_destination(dest, confirm_overwrite=config.overwrite_confirmation)

        if status == "missing_directory":
            def _on_dir_confirm(created: bool | None) -> None:
                if created:
                    FileIOService.ensure_directory(dest.parent)
                    self._execute_render_save(data, dest, "Pasted JSON")
            self.app.push_screen(CreateDirectoryModal(dest.parent), _on_dir_confirm)
            return

        if status == "needs_overwrite_confirm":
            def _on_overwrite_confirm(confirmed: bool | None) -> None:
                if confirmed:
                    self._execute_render_save(data, dest, "Pasted JSON")
            self.app.push_screen(OverwriteModal(dest), _on_overwrite_confirm)
            return

        self._execute_render_save(data, dest, "Pasted JSON")

    def _execute_render_save(self, data: dict[str, Any], dest: Path, source_label: str) -> None:
        try:
            result = from_netlist(data)
        except Exception as exc:
            self.set_status(f"× Engine rendering failed: {exc}")
            return

        ok, msg = FileIOService.save_svg_safely(result.svg, dest, allow_overwrite=True)
        if not ok:
            self.set_status(f"× {msg}")
            return

        comps_count = len(result.model.components) if result.model else len(data.get("components", []))
        nets_count = len(result.model.nets) if result.model else len(data.get("nets", []))

        self.app.push_screen(
            RenderSuccessScreen(
                svg_path=dest,
                input_source=source_label,
                components_count=comps_count,
                nets_count=nets_count,
                netlist=data,
            )
        )

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
        Binding("ctrl+q", "quit_app", "Quit", show=False, priority=True),
        Binding("q", "quit_app", "Quit", show=False),
    ]

    def __init__(
        self,
        svg_path: Path,
        input_source: str,
        components_count: int,
        nets_count: int,
        netlist: dict[str, Any],
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.svg_path = svg_path
        self.input_source = input_source
        self.components_count = components_count
        self.nets_count = nets_count
        self.netlist = netlist

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Container(id="home-container"):
            with Vertical(id="home-card"):
                with Horizontal(classes="breadcrumb-row"):
                    yield Static("CircuitGen / Render", classes="breadcrumb-left")
                    yield Static("Success", classes="breadcrumb-right")

                yield Static("─" * 62, classes="rule")
                yield Static("✓ Schematic rendered successfully", classes="setup-title")

                with Vertical(classes="summary-card"):
                    with Horizontal(classes="summary-row"):
                        yield Static("File", classes="summary-label")
                        yield Static(str(self.svg_path), classes="summary-value")
                    with Horizontal(classes="summary-row"):
                        yield Static("Input", classes="summary-label")
                        yield Static(self.input_source, classes="summary-value")
                    with Horizontal(classes="summary-row"):
                        yield Static("Components", classes="summary-label")
                        yield Static(str(self.components_count), classes="summary-value")
                    with Horizontal(classes="summary-row"):
                        yield Static("Nets", classes="summary-label")
                        yield Static(str(self.nets_count), classes="summary-value")

                yield Static("", id="render-success-status", classes="status-message")

                yield SelectableMenu(
                    [
                        MenuItem("open", "Open schematic", "Open SVG schematic in default system viewer"),
                        MenuItem("view_netlist", "View netlist", "Inspect the rendered JSON netlist"),
                        MenuItem("render_another", "Render another", "Render another circuit schematic"),
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

    def set_status(self, msg: str) -> None:
        try:
            self.query_one("#render-success-status", Static).update(msg)
        except Exception:
            pass

    def on_selectable_menu_selected(self, message: SelectableMenu.Selected) -> None:
        key = message.item.key
        if key == "open":
            ok, err = open_file_in_system_viewer(self.svg_path)
            if ok:
                self.set_status("✓ Opened schematic in system viewer.")
            else:
                self.set_status(f"! {err}")
        elif key == "view_netlist":
            self.app.push_screen(ViewNetlistScreen(netlist=self.netlist, source_file=self.svg_path.stem))
        elif key == "render_another":
            self.app.push_screen(RenderModeScreen())
        elif key == "home":
            self.action_back_home()

    def action_back_home(self) -> None:
        from circuitgen.tui.screens.home import HomeScreen
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
        Binding("ctrl+q", "quit_app", "Quit", show=False, priority=True),
        Binding("q", "quit_app", "Quit", show=False),
    ]

    def __init__(self, netlist: dict[str, Any], source_file: str = "circuit", **kwargs) -> None:
        super().__init__(**kwargs)
        self.netlist = netlist
        self.source_file = source_file

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

                yield JsonEditor(text=json_str, id="netlist-viewer-editor")
                yield Static("", id="netlist-view-status", classes="status-message")

                yield SelectableMenu(
                    [
                        MenuItem("copy", "Copy JSON to clipboard", "Copy the full netlist to system clipboard"),
                        MenuItem("back", "Back to schematic result", "Return to render success screen"),
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
