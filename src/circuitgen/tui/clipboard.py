"""Cross-platform system clipboard interface with in-memory fallback.

Provides seamless clipboard integration across Windows (ctypes Win32 API),
macOS (pbcopy/pbpaste), and Linux/Unix (wl-clipboard, xclip, xsel), with
graceful in-memory fallback.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time

_IN_MEMORY_CLIPBOARD: str = ""


# ---------------------------------------------------------------------------
# Windows Win32 ctypes implementation
# ---------------------------------------------------------------------------

def _get_windows_clipboard() -> str | None:
    """Read text from Windows clipboard using ctypes without external dependencies."""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        CF_UNICODETEXT = 13

        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.CloseClipboard.argtypes = []
        user32.CloseClipboard.restype = wintypes.BOOL
        user32.GetClipboardData.argtypes = [wintypes.UINT]
        user32.GetClipboardData.restype = wintypes.HANDLE

        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = wintypes.LPVOID
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.restype = wintypes.BOOL

        for _ in range(3):
            if user32.OpenClipboard(None):
                break
            time.sleep(0.005)
        else:
            return None

        try:
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return None
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                return None
            try:
                val = ctypes.c_wchar_p(ptr).value
                return val if val is not None else ""
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()
    except Exception:
        return None


def _set_windows_clipboard(text: str) -> bool:
    """Write text to Windows clipboard using ctypes without external dependencies."""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        CF_UNICODETEXT = 13
        GMEM_MOVEABLE = 0x0002

        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.CloseClipboard.argtypes = []
        user32.CloseClipboard.restype = wintypes.BOOL
        user32.EmptyClipboard.argtypes = []
        user32.EmptyClipboard.restype = wintypes.BOOL
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        user32.SetClipboardData.restype = wintypes.HANDLE

        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = wintypes.LPVOID
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.restype = wintypes.BOOL

        for _ in range(3):
            if user32.OpenClipboard(None):
                break
            time.sleep(0.005)
        else:
            return False

        try:
            user32.EmptyClipboard()
            data = text.encode("utf-16-le") + b"\x00\x00"
            h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
            if not h_mem:
                return False
            ptr = kernel32.GlobalLock(h_mem)
            if not ptr:
                return False
            ctypes.memmove(ptr, data, len(data))
            kernel32.GlobalUnlock(h_mem)
            user32.SetClipboardData(CF_UNICODETEXT, h_mem)
            return True
        finally:
            user32.CloseClipboard()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# macOS implementation
# ---------------------------------------------------------------------------

def _get_darwin_clipboard() -> str | None:
    """Read text from macOS clipboard using pbpaste."""
    try:
        proc = subprocess.run(
            ["pbpaste"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=True,
            timeout=1.0,
        )
        return proc.stdout
    except Exception:
        return None


def _set_darwin_clipboard(text: str) -> bool:
    """Write text to macOS clipboard using pbcopy."""
    try:
        subprocess.run(
            ["pbcopy"],
            input=text,
            text=True,
            check=True,
            timeout=1.0,
        )
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Linux / POSIX implementation
# ---------------------------------------------------------------------------

def _get_linux_clipboard() -> str | None:
    """Read text from Linux clipboard using wl-paste, xclip, or xsel."""
    try:
        if shutil.which("wl-paste"):
            proc = subprocess.run(
                ["wl-paste", "--no-newline"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=True,
                timeout=1.0,
            )
            return proc.stdout
        if shutil.which("xclip"):
            proc = subprocess.run(
                ["xclip", "-selection", "clipboard", "-o"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=True,
                timeout=1.0,
            )
            return proc.stdout
        if shutil.which("xsel"):
            proc = subprocess.run(
                ["xsel", "--clipboard", "--output"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=True,
                timeout=1.0,
            )
            return proc.stdout
    except Exception:
        return None
    return None


def _set_linux_clipboard(text: str) -> bool:
    """Write text to Linux clipboard using wl-copy, xclip, or xsel."""
    try:
        if shutil.which("wl-copy"):
            subprocess.run(
                ["wl-copy"],
                input=text,
                text=True,
                check=True,
                timeout=1.0,
            )
            return True
        if shutil.which("xclip"):
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=text,
                text=True,
                check=True,
                timeout=1.0,
            )
            return True
        if shutil.which("xsel"):
            subprocess.run(
                ["xsel", "--clipboard", "--input"],
                input=text,
                text=True,
                check=True,
                timeout=1.0,
            )
            return True
    except Exception:
        return False
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_system_clipboard() -> str:
    """Retrieve text from the host OS system clipboard, falling back to memory."""
    os_text: str | None = None
    if sys.platform == "win32":
        os_text = _get_windows_clipboard()
    elif sys.platform == "darwin":
        os_text = _get_darwin_clipboard()
    elif sys.platform.startswith("linux") or "bsd" in sys.platform:
        os_text = _get_linux_clipboard()

    if os_text is not None:
        return os_text
    return _IN_MEMORY_CLIPBOARD


def set_system_clipboard(text: str) -> None:
    """Save text to both in-memory cache and host OS system clipboard."""
    global _IN_MEMORY_CLIPBOARD
    _IN_MEMORY_CLIPBOARD = text

    if sys.platform == "win32":
        _set_windows_clipboard(text)
    elif sys.platform == "darwin":
        _set_darwin_clipboard(text)
    elif sys.platform.startswith("linux") or "bsd" in sys.platform:
        _set_linux_clipboard(text)
