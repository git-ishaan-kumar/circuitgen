"""Tests for Phase 6 file I/O service, JSON editor, path picker, and save guard modals."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input

from circuitgen.tui.screens.confirm_dialog import CreateDirectoryModal, OverwriteModal
from circuitgen.tui.services.file_io import FileIOService
from circuitgen.tui.widgets.json_editor import JsonEditor
from circuitgen.tui.widgets.path_picker import PathPickerModal
from circuitgen.tui.widgets.selectable_menu import SelectableMenu


SAMPLE_VALID_NETLIST = """{
  "components": [
    {"id": "B1", "type": "battery", "value": "9V"},
    {"id": "R1", "type": "resistor", "value": "330Ω"},
    {"id": "D1", "type": "led", "value": "red"}
  ],
  "nets": [
    {"name": "VCC", "pins": ["B1.p", "R1.a"]},
    {"name": "LED_POS", "pins": ["R1.b", "D1.a"]},
    {"name": "GND", "pins": ["D1.b", "B1.n"]}
  ]
}"""

SAMPLE_MALFORMED_JSON = """{
  "components": [
    {"id": "B1", "type": "battery", "value": "9V"}
    {"id": "R1", "type": "resistor", "value": "330Ω"}
  ]
}"""


# ---------------------------------------------------------------------------
# FileIOService unit tests
# ---------------------------------------------------------------------------

def test_parse_json_netlist_valid():
    """Test parsing a valid JSON netlist dictionary."""
    data, err, loc = FileIOService.parse_json_netlist(SAMPLE_VALID_NETLIST)
    assert err is None
    assert loc is None
    assert isinstance(data, dict)
    assert len(data["components"]) == 3
    assert len(data["nets"]) == 3


def test_parse_json_netlist_malformed():
    """Test that malformed JSON yields exact line and column numbers."""
    data, err, loc = FileIOService.parse_json_netlist(SAMPLE_MALFORMED_JSON)
    assert data is None
    assert err is not None
    assert "Line 4, column" in err
    assert loc is not None
    assert loc[0] == 4  # line 4 missing comma


def test_parse_json_netlist_empty_and_oversized():
    """Test handling of empty string and oversized payloads."""
    # Empty string
    data, err, loc = FileIOService.parse_json_netlist("   ")
    assert data is None
    assert "empty" in err.lower()

    # Oversized payload
    large_text = "{" + '"a": "b",' * 100_000 + '"end": 1}'
    data, err, loc = FileIOService.parse_json_netlist(large_text, max_bytes=1024)
    assert data is None
    assert "exceeds maximum allowed size" in err


def test_parse_json_netlist_non_dict_and_missing_components():
    """Test validation rules for top-level dictionary and required components key."""
    # List instead of dict
    data, err, loc = FileIOService.parse_json_netlist('["not", "a", "dict"]')
    assert data is None
    assert "top-level dictionary" in err

    # Dict without components
    data, err, loc = FileIOService.parse_json_netlist('{"nets": []}')
    assert data is None
    assert "missing required 'components'" in err


def test_read_json_file_success(tmp_path: Path):
    """Test reading a valid UTF-8 JSON file from disk."""
    json_file = tmp_path / "valid_circuit.json"
    json_file.write_text(SAMPLE_VALID_NETLIST, encoding="utf-8")

    data, err, loc = FileIOService.read_json_file(json_file)
    assert err is None
    assert data is not None
    assert len(data["components"]) == 3


def test_read_json_file_missing_and_invalid_utf8(tmp_path: Path):
    """Test handling of missing files and invalid UTF-8 files."""
    # Missing file
    data, err, loc = FileIOService.read_json_file(tmp_path / "nonexistent.json")
    assert data is None
    assert "File not found" in err

    # Non-UTF8 file
    bad_file = tmp_path / "bad_bytes.json"
    bad_file.write_bytes(b"\x80\x81\x82\xff")
    data, err, loc = FileIOService.read_json_file(bad_file)
    assert data is None
    assert "UTF-8" in err


def test_sanitize_filename_and_resolve_output_path(tmp_path: Path):
    """Test filename sanitization against traversal and illegal characters."""
    # Directory traversal prevention
    assert FileIOService.sanitize_filename("../../etc/passwd.txt") == "passwd.txt.svg"

    # Illegal character removal
    assert FileIOService.sanitize_filename('my:cool*circuit<1>.svg') == "mycoolcircuit1.svg"

    # Missing suffix
    assert FileIOService.sanitize_filename("led_diagram") == "led_diagram.svg"

    # Empty filename fallback
    assert FileIOService.sanitize_filename("  ???  ") == "circuit.svg"

    # Path resolution relative to CWD and absolute
    rel_resolved = FileIOService.resolve_output_path("./output/circuits", "led.svg")
    assert rel_resolved.name == "led.svg"
    assert rel_resolved.is_absolute()

    abs_dir = tmp_path / "my_outputs"
    abs_resolved = FileIOService.resolve_output_path(abs_dir, "test.svg")
    assert abs_resolved == abs_dir / "test.svg"


def test_check_destination_statuses(tmp_path: Path):
    """Test check_destination status outcomes."""
    existing_file = tmp_path / "existing.svg"
    existing_file.write_text("<svg></svg>", encoding="utf-8")

    # Destination exists and confirm_overwrite is True
    assert FileIOService.check_destination(existing_file, confirm_overwrite=True) == "needs_overwrite_confirm"

    # Destination exists and confirm_overwrite is False
    assert FileIOService.check_destination(existing_file, confirm_overwrite=False) == "ready"

    # Missing parent directory
    missing_parent_file = tmp_path / "nonexistent_dir" / "new.svg"
    assert FileIOService.check_destination(missing_parent_file) == "missing_directory"

    # Ready for writing in existing directory
    ready_file = tmp_path / "new_circuit.svg"
    assert FileIOService.check_destination(ready_file) == "ready"


def test_save_svg_safely_atomic(tmp_path: Path):
    """Test atomic saving creates complete file without leaving temp files."""
    dest = tmp_path / "sub" / "output.svg"
    svg_content = "<svg viewBox='0 0 100 100'><rect width='100' height='100'/></svg>"

    ok, msg = FileIOService.save_svg_safely(svg_content, dest, allow_overwrite=True)
    assert ok is True
    assert dest.exists()
    assert dest.read_text(encoding="utf-8") == svg_content

    # Ensure no lingering temporary files
    temp_files = list(dest.parent.glob(".tmp_*"))
    assert len(temp_files) == 0


def test_save_svg_safely_overwrite_guard(tmp_path: Path):
    """Test that save_svg_safely rejects overwrite when allow_overwrite is False."""
    dest = tmp_path / "existing.svg"
    dest.write_text("initial content", encoding="utf-8")

    ok, msg = FileIOService.save_svg_safely("new content", dest, allow_overwrite=False)
    assert ok is False
    assert "File already exists" in msg
    assert dest.read_text(encoding="utf-8") == "initial content"


# ---------------------------------------------------------------------------
# UI widget & modal tests
# ---------------------------------------------------------------------------

class JsonEditorTestApp(App[None]):
    """App harness to test JsonEditor widget."""

    def compose(self) -> ComposeResult:
        yield JsonEditor(text="line 1", id="test-editor")
        yield Input(id="next-input")


def test_json_editor_tab_and_enter():
    """Test that JsonEditor inserts newline on Enter and transfers focus on Tab."""
    async def _run():
        app = JsonEditorTestApp()
        async with app.run_test() as pilot:
            editor = app.query_one("#test-editor", JsonEditor)
            next_inp = app.query_one("#next-input", Input)

            editor.focus()
            editor.cursor_location = (0, 6)  # end of line 1
            await pilot.press("enter")
            await pilot.press("a")
            assert "line 1\na" in editor.text

            # Press Tab to advance focus to next input
            await pilot.press("tab")
            assert next_inp.has_focus

    asyncio.run(_run())


def test_json_editor_validate_netlist_method():
    """Test the validate_netlist convenience method on JsonEditor."""
    editor = JsonEditor(text=SAMPLE_VALID_NETLIST)
    data, err, loc = editor.validate_netlist()
    assert err is None
    assert data is not None

    editor.text = "invalid json"
    data, err, loc = editor.validate_netlist()
    assert err is not None
    assert data is None


class ModalHarnessApp(App[None]):
    """App harness to test OverwriteModal and CreateDirectoryModal."""

    result: bool | None = None

    def show_overwrite(self, path: Path):
        def _cb(res: bool | None):
            self.result = res
        self.push_screen(OverwriteModal(path), _cb)

    def show_create_dir(self, path: Path):
        def _cb(res: bool | None):
            self.result = res
        self.push_screen(CreateDirectoryModal(path), _cb)


def test_overwrite_modal_cancel_and_confirm(tmp_path: Path):
    """Test OverwriteModal default cancel and confirm actions."""
    async def _run():
        app = ModalHarnessApp()
        async with app.run_test() as pilot:
            target = tmp_path / "test.svg"

            # 1. Test cancel (default option is Cancel)
            app.show_overwrite(target)
            await pilot.pause()
            menu = app.screen.query_one(SelectableMenu)
            assert menu.cursor_index == 0  # cancel
            await pilot.press("enter")
            await pilot.pause()
            assert app.result is False

            # 2. Test confirm overwrite
            app.show_overwrite(target)
            await pilot.pause()
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.pause()
            assert app.result is True

    asyncio.run(_run())


def test_create_directory_modal_confirm_and_cancel(tmp_path: Path):
    """Test CreateDirectoryModal confirm and cancel actions."""
    async def _run():
        app = ModalHarnessApp()
        async with app.run_test() as pilot:
            target_dir = tmp_path / "new_folder"

            # 1. Test confirm create (default option is Create)
            app.show_create_dir(target_dir)
            await pilot.pause()
            menu = app.screen.query_one(SelectableMenu)
            assert menu.cursor_index == 0  # create
            await pilot.press("enter")
            await pilot.pause()
            assert app.result is True

            # 2. Test cancel
            app.show_create_dir(target_dir)
            await pilot.pause()
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.pause()
            assert app.result is False

    asyncio.run(_run())


class PathPickerHarnessApp(App[None]):
    """App harness to test PathPickerModal."""

    picked_path: Path | None = None

    def show_picker(self, path: Path, mode: str = "file", filters=None):
        def _cb(res: Path | None):
            self.picked_path = res
        self.push_screen(PathPickerModal(initial_path=path, mode=mode, filters=filters), _cb)


def test_path_picker_modal_file_mode(tmp_path: Path):
    """Test PathPickerModal in file mode picking a .json file."""
    # Prepare files
    sub_dir = tmp_path / "circuits"
    sub_dir.mkdir()
    target_json = sub_dir / "my_circuit.json"
    target_json.write_text("{}", encoding="utf-8")
    other_file = sub_dir / "notes.txt"
    other_file.write_text("notes", encoding="utf-8")

    async def _run():
        app = PathPickerHarnessApp()
        async with app.run_test() as pilot:
            app.show_picker(tmp_path, mode="file", filters=[".json"])
            await pilot.pause()

            # Navigate into sub_dir
            menu = app.screen.query_one(SelectableMenu)
            # Find index of circuits/
            circuits_idx = next(i for i, item in enumerate(menu.items) if item.key == "DIR:circuits")
            menu.cursor_index = circuits_idx
            await pilot.press("enter")
            await pilot.pause()

            # Now inside circuits, my_circuit.json should be present, notes.txt filtered out
            menu = app.screen.query_one(SelectableMenu)
            keys = [item.key for item in menu.items]
            assert "FILE:my_circuit.json" in keys
            assert "FILE:notes.txt" not in keys

            # Select my_circuit.json
            json_idx = keys.index("FILE:my_circuit.json")
            menu.cursor_index = json_idx
            await pilot.press("enter")
            await pilot.pause()

            assert app.picked_path == target_json.resolve()

    asyncio.run(_run())


def test_path_picker_modal_directory_mode(tmp_path: Path):
    """Test PathPickerModal in directory mode picking a folder."""
    out_dir = tmp_path / "export_output"
    out_dir.mkdir()

    async def _run():
        app = PathPickerHarnessApp()
        async with app.run_test() as pilot:
            app.show_picker(out_dir, mode="directory")
            await pilot.pause()

            menu = app.screen.query_one(SelectableMenu)
            assert menu.items[0].key == "SELECT_THIS_DIR"
            menu.cursor_index = 0
            await pilot.press("enter")
            await pilot.pause()

            assert app.picked_path == out_dir.resolve()

    asyncio.run(_run())


def test_path_picker_modal_cancel(tmp_path: Path):
    """Test that Esc in PathPickerModal cancels and returns None."""
    async def _run():
        app = PathPickerHarnessApp()
        async with app.run_test() as pilot:
            app.show_picker(tmp_path, mode="file")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

            assert app.picked_path is None

    asyncio.run(_run())


def test_json_editor_ctrl_a_select_all():
    """Test that Ctrl+A selects all text in JsonEditor."""
    class EditorHarnessApp(App[None]):
        def compose(self) -> ComposeResult:
            yield JsonEditor(text="line 1\nline 2\nline 3", id="test-editor")

    async def _run():
        app = EditorHarnessApp()
        async with app.run_test() as pilot:
            editor = app.query_one("#test-editor", JsonEditor)
            editor.focus()
            await pilot.press("ctrl+a")
            assert editor.selected_text == "line 1\nline 2\nline 3"

    asyncio.run(_run())


def test_path_picker_modal_scroll_many_items(tmp_path: Path):
    """Test that PathPickerModal correctly navigates and scrolls through 25+ files without clipping."""
    # Create 25 files
    for i in range(25):
        (tmp_path / f"circuit_{i:02d}.json").write_text("{}", encoding="utf-8")

    async def _run():
        app = PathPickerHarnessApp()
        async with app.run_test() as pilot:
            app.show_picker(tmp_path, mode="file", filters=[".json"])
            await pilot.pause()

            menu = app.screen.query_one(SelectableMenu)
            # Total items: 1 parent dir + 25 files = 26 items
            assert len(menu.items) == 26

            # Navigate down 20 times
            for _ in range(20):
                await pilot.press("down")

            assert menu.cursor_index == 20
            # Viewport should have shifted down smoothly
            assert menu.viewport_start > 0
            assert menu.viewport_start <= menu.cursor_index < menu.viewport_start + menu.max_visible

            # Press Enter on the 20th item
            await pilot.press("enter")
            await pilot.pause()

            # Successfully selected the 20th item
            assert app.picked_path is not None
            assert app.picked_path.exists()

    asyncio.run(_run())

