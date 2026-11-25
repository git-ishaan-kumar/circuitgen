"""File I/O service providing safe JSON netlist parsing, path resolution, and atomic saves.

Adheres to:
- Strict UTF-8 file reading and line/column JSON decode error reporting.
- Path resolution relative to CWD with filename sanitization.
- Atomic SVG saves using temporary replacement files preventing truncated writes.
- Non-destructive destination checks (directory creation & overwrite guards).
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


class FileIOService:
    """Service handling file reading, JSON parsing, and atomic local file writing."""

    MAX_JSON_BYTES: int = 1_000_000  # 1 MB maximum for pasted/loaded netlists

    @classmethod
    def parse_json_netlist(
        cls,
        text: str,
        max_bytes: int = MAX_JSON_BYTES,
    ) -> tuple[dict[str, Any] | None, str | None, tuple[int, int] | None]:
        """Parse raw text into a netlist dictionary with precise error reporting.

        Returns:
            (netlist_dict, error_message, (line, col) or None)
        """
        trimmed = text.strip()
        if not trimmed:
            return None, "JSON input is empty.", (1, 1)

        encoded = text.encode("utf-8")
        if len(encoded) > max_bytes:
            return (
                None,
                f"JSON input exceeds maximum allowed size ({max_bytes // 1024} KB).",
                None,
            )

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            msg = f"Line {exc.lineno}, column {exc.colno}: {exc.msg}."
            return None, msg, (exc.lineno, exc.colno)

        if not isinstance(data, dict):
            return (
                None,
                "Netlist JSON must be a top-level dictionary/object.",
                (1, 1),
            )

        if "components" not in data:
            return (
                None,
                "Netlist JSON missing required 'components' list.",
                (1, 1),
            )

        return data, None, None

    @classmethod
    def read_json_file(
        cls,
        path: str | Path,
    ) -> tuple[dict[str, Any] | None, str | None, tuple[int, int] | None]:
        """Read and parse a JSON netlist file with UTF-8 handling and clean errors.

        Returns:
            (netlist_dict, error_message, (line, col) or None)
        """
        try:
            target = Path(path).expanduser().resolve()
        except Exception as exc:
            return None, f"Invalid file path: {exc}", None

        try:
            if not target.exists():
                return None, f"File not found: {target}", None
            if not target.is_file():
                return None, f"Path is not a regular file: {target}", None
            content = target.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None, f"File not found: {target}", None
        except PermissionError:
            return None, f"Permission denied reading file: {target}", None
        except UnicodeDecodeError:
            return None, f"File is not valid UTF-8 text: {target}", None
        except OSError as exc:
            return None, f"Could not read file: {exc}", None

        return cls.parse_json_netlist(content)

    @classmethod
    def sanitize_filename(
        cls,
        filename: str,
        default_stem: str = "circuit",
        default_suffix: str = ".svg",
    ) -> str:
        """Sanitize an output filename to be portable and safe against path traversal."""
        # Strip path separators to prevent directory traversal
        base = Path(filename.strip()).name

        # Remove illegal filename characters across Windows/POSIX: < > : " / \ | ? *
        cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", base).strip(". ")

        if not cleaned:
            cleaned = default_stem

        # Ensure correct suffix
        if not cleaned.lower().endswith(default_suffix.lower()):
            cleaned = f"{cleaned}{default_suffix}"

        return cleaned

    @classmethod
    def resolve_output_path(
        cls,
        directory: str | Path,
        filename: str,
    ) -> Path:
        """Resolve the full destination path for an output file relative to CWD."""
        clean_name = cls.sanitize_filename(filename)
        dir_path = Path(directory).expanduser()

        if not dir_path.is_absolute():
            dir_path = (Path.cwd() / dir_path).resolve()
        else:
            dir_path = dir_path.resolve()

        return dir_path / clean_name

    @classmethod
    def check_destination(
        cls,
        destination: Path,
        confirm_overwrite: bool = True,
    ) -> str:
        """Check the status of the target save destination.

        Returns:
            "missing_directory" if target parent folder does not exist
            "needs_overwrite_confirm" if destination file exists and overwrite confirmation is on
            "ready" if target is ready for writing
        """
        if not destination.parent.exists():
            return "missing_directory"

        if destination.exists() and confirm_overwrite:
            return "needs_overwrite_confirm"

        return "ready"

    @classmethod
    def ensure_directory(cls, directory: Path) -> tuple[bool, str]:
        """Safely create target directory and any missing parents.

        Returns:
            (success, error_message)
        """
        try:
            directory.mkdir(parents=True, exist_ok=True)
            return True, ""
        except PermissionError:
            return False, f"Permission denied creating directory: {directory}"
        except OSError as exc:
            return False, f"Failed to create directory: {exc}"

    @classmethod
    def save_svg_safely(
        cls,
        svg_content: str,
        destination: Path,
        allow_overwrite: bool = True,
    ) -> tuple[bool, str]:
        return cls.save_output(svg_content, destination, allow_overwrite)

    @classmethod
    def save_output(
        cls, content: str | bytes, destination: Path, allow_overwrite: bool = True,
    ) -> tuple[bool, str]:
        """Write a complete output before replacing the destination."""
        if destination.exists() and not allow_overwrite:
            return False, f"File already exists and overwrite was not permitted: {destination}"

        parent_dir = destination.parent
        ok, err = cls.ensure_directory(parent_dir)
        if not ok:
            return False, err

        # Write to temporary file in the same directory, then atomic rename
        tmp_file: tempfile.NamedTemporaryFile | None = None
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=str(parent_dir),
                prefix=f".tmp_{destination.stem}_",
                suffix=".tmp",
                delete=False,
            ) as tmp_file:
                tmp_path = Path(tmp_file.name)
                tmp_file.write(content.encode("utf-8") if isinstance(content, str) else content)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())

            if allow_overwrite:
                os.replace(tmp_path, destination)
            else:
                os.link(tmp_path, destination)
                tmp_path.unlink()
            return True, str(destination)

        except PermissionError:
            if tmp_path and tmp_path.exists():
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            return False, f"Permission denied writing to destination: {destination}"
        except OSError as exc:
            if tmp_path and tmp_path.exists():
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            return False, f"Failed to save file: {exc}"
