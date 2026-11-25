"""Terminal folder and file picker modal dialog."""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from .selectable_menu import MenuItem, SelectableMenu


class PathPickerModal(ModalScreen[Path | None]):
    """Modal dialog for browsing the filesystem and picking a file or directory."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True, priority=True),
        Binding("backspace", "go_parent", "Parent folder", show=False),
        Binding("pageup", "page_up", "Page Up", show=False),
        Binding("pagedown", "page_down", "Page Down", show=False),
    ]

    def __init__(
        self,
        initial_path: Path | str | None = None,
        mode: str = "file",  # "file" or "directory"
        filters: Sequence[str] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        if initial_path:
            p = Path(initial_path).expanduser()
            if p.is_file():
                self.current_path = p.parent.resolve()
            elif p.is_dir():
                self.current_path = p.resolve()
            else:
                self.current_path = Path.cwd().resolve()
        else:
            self.current_path = Path.cwd().resolve()

        self.mode = mode
        self.filters = [f.lower() for f in filters] if filters else None

    def compose(self) -> ComposeResult:
        with Vertical(id="path-picker-dialog"):
            title = "Browse Folders" if self.mode == "directory" else "Select File"
            yield Static(title, classes="modal-title")
            yield Static(f"Location: {self.current_path}", id="picker-current-path", classes="modal-warning")
            yield Static("", id="picker-status-msg", classes="status-message")

            items = self._build_menu_items()
            yield SelectableMenu(
                items=items,
                initial_index=0,
                max_visible=8,
                id="picker-menu",
            )
            yield Static(
                "↑↓ Navigate  ·  Enter Open/Select  ·  Backspace Parent  ·  Esc Cancel",
                classes="keys-reminder",
            )

    def on_mount(self) -> None:
        try:
            self.query_one(SelectableMenu).focus()
        except Exception:
            pass

    def _build_menu_items(self) -> list[MenuItem]:
        """Build items list for the current directory."""
        items: list[MenuItem] = []

        if self.mode == "directory":
            dir_name = self.current_path.name or str(self.current_path)
            items.append(
                MenuItem(
                    "SELECT_THIS_DIR",
                    f"✔ Select this folder ({dir_name})",
                    f"Use '{self.current_path}' as destination",
                )
            )

        # Parent directory navigation if not at filesystem root
        if self.current_path.parent != self.current_path:
            items.append(
                MenuItem(
                    "PARENT_DIR",
                    "📁 .. (Parent folder)",
                    "Navigate up one directory level",
                )
            )

        try:
            entries = list(self.current_path.iterdir())
        except (PermissionError, OSError) as exc:
            self._set_status(f"! Cannot read directory: {exc}")
            return items if items else [MenuItem("EMPTY", "(No accessible items)", "")]

        dirs: list[Path] = []
        files: list[Path] = []

        for entry in entries:
            # Skip hidden files/directories starting with '.'
            if entry.name.startswith("."):
                continue
            try:
                if entry.is_dir():
                    dirs.append(entry)
                elif self.mode == "file" and entry.is_file():
                    if not self.filters or entry.suffix.lower() in self.filters:
                        files.append(entry)
            except (PermissionError, OSError):
                continue

        dirs.sort(key=lambda p: p.name.lower())
        files.sort(key=lambda p: p.name.lower())

        for d in dirs:
            items.append(MenuItem(f"DIR:{d.name}", f"📁 {d.name}/", "Open folder"))

        for f in files:
            size_str = ""
            try:
                size_bytes = f.stat().st_size
                if size_bytes < 1024:
                    size_str = f"{size_bytes} B"
                else:
                    size_str = f"{size_bytes / 1024:.1f} KB"
            except OSError:
                pass
            items.append(MenuItem(f"FILE:{f.name}", f"📄 {f.name}", size_str))

        if not items:
            items.append(MenuItem("EMPTY", "(Empty directory)", ""))

        return items

    def _refresh(self) -> None:
        """Update path label and menu items."""
        try:
            self.query_one("#picker-current-path", Static).update(f"Location: {self.current_path}")
            self.query_one("#picker-status-msg", Static).update("")
            menu = self.query_one(SelectableMenu)
            items = self._build_menu_items()
            menu.set_items(items, initial_index=0)
            menu.focus()
        except Exception:
            pass

    def _set_status(self, msg: str) -> None:
        try:
            self.query_one("#picker-status-msg", Static).update(msg)
        except Exception:
            pass

    def action_page_up(self) -> None:
        try:
            self.query_one(SelectableMenu).action_page_up()
        except Exception:
            pass

    def action_page_down(self) -> None:
        try:
            self.query_one(SelectableMenu).action_page_down()
        except Exception:
            pass

    def on_selectable_menu_selected(self, message: SelectableMenu.Selected) -> None:
        key = message.item.key

        if key == "SELECT_THIS_DIR":
            self.dismiss(self.current_path)
            return

        if key == "PARENT_DIR":
            self.action_go_parent()
            return

        if key.startswith("DIR:"):
            dirname = key[4:]
            target = self.current_path / dirname
            try:
                # Test readability
                list(target.iterdir())
                self.current_path = target.resolve()
                self._refresh()
            except (PermissionError, OSError) as exc:
                self._set_status(f"! Permission denied: {exc}")
            return

        if key.startswith("FILE:"):
            filename = key[5:]
            self.dismiss((self.current_path / filename).resolve())
            return

    def action_go_parent(self) -> None:
        """Navigate to parent folder if not at root."""
        if self.current_path.parent != self.current_path:
            self.current_path = self.current_path.parent.resolve()
            self._refresh()

    def action_cancel(self) -> None:
        self.dismiss(None)
