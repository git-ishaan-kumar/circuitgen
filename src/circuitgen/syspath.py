"""Windows PATH discovery, verification, and persistent user PATH configuration."""
from __future__ import annotations

import os
import shutil
import sys
import sysconfig
from pathlib import Path
from typing import TextIO


def is_wsl() -> bool:
    """Return True if running in Windows Subsystem for Linux (WSL)."""
    if not sys.platform.startswith("linux"):
        return False
    if "WSL_DISTRO_NAME" in os.environ or "WSL_INTEROP" in os.environ:
        return True
    try:
        with open("/proc/version", "r", encoding="utf-8", errors="ignore") as f:
            content = f.read().lower()
            return "microsoft" in content or "wsl" in content
    except Exception:
        return False


def is_windows() -> bool:
    """Return True if running on native Windows (not WSL)."""
    return sys.platform == "win32" and not is_wsl()


def is_virtual_environment() -> bool:
    """Return True if running inside a virtual environment or Conda environment."""
    if getattr(sys, "base_prefix", sys.prefix) != sys.prefix:
        return True
    if "VIRTUAL_ENV" in os.environ or "CONDA_PREFIX" in os.environ:
        return True
    return False


def get_candidate_script_directories() -> list[Path]:
    """Return candidate directories that might contain installed console scripts."""
    candidates: list[Path] = []

    def _add(p: Path | str | None) -> None:
        if p:
            try:
                resolved = Path(p).resolve()
                if resolved not in candidates and resolved.is_dir():
                    candidates.append(resolved)
            except Exception:
                pass

    # 1. Standard sysconfig scripts path
    try:
        _add(sysconfig.get_path("scripts"))
    except Exception:
        pass

    # 2. User scheme scripts path (e.g. %APPDATA%\Python\Python314\Scripts)
    if sys.platform == "win32":
        try:
            _add(sysconfig.get_path("scripts", "nt_user"))
        except Exception:
            pass
    else:
        try:
            _add(sysconfig.get_path("scripts", f"{os.name}_user"))
        except Exception:
            pass

    # 3. Path relative to sys.executable
    try:
        py_dir = Path(sys.executable).resolve().parent
        _add(py_dir / "Scripts")
        _add(py_dir)
        _add(py_dir / "bin")
    except Exception:
        pass

    # 4. Windows AppData paths
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        localappdata = os.environ.get("LOCALAPPDATA")
        ver_tag = f"Python{sys.version_info.major}{sys.version_info.minor}"
        if appdata:
            _add(Path(appdata) / "Python" / ver_tag / "Scripts")
            _add(Path(appdata) / "Python" / "Scripts")
        if localappdata:
            _add(Path(localappdata) / "Programs" / "Python" / ver_tag / "Scripts")
            _add(Path(localappdata) / "pipx" / "venvs" / "circuitgen" / "Scripts")

    # 5. User home bin directories
    try:
        home = Path.home()
        _add(home / ".local" / "bin")
        _add(home / "bin")
    except Exception:
        pass

    return candidates


def find_installed_launcher(candidate_dirs: list[Path] | None = None) -> Path | None:
    """Find the actual installed circuitgen launcher executable on disk.
    
    Never guesses: only returns a Path if the executable actually exists on disk.
    """
    if candidate_dirs is None:
        candidate_dirs = get_candidate_script_directories()

    exe_names = ["circuitgen.exe", "circuitgen"] if sys.platform == "win32" else ["circuitgen"]

    # Check candidates
    for directory in candidate_dirs:
        for name in exe_names:
            target = directory / name
            if target.is_file():
                return target

    # Also check if already discoverable via PATH
    which_path = shutil.which("circuitgen")
    if which_path:
        p = Path(which_path).resolve()
        if p.is_file():
            return p

    return None


def normalize_path(path_str: str | Path) -> str:
    """Normalize a filesystem path for reliable cross-platform comparison."""
    try:
        resolved = Path(path_str).resolve()
        normed = os.path.normpath(str(resolved))
    except Exception:
        normed = os.path.normpath(str(path_str))
    if sys.platform == "win32":
        return os.path.normcase(normed)
    return normed


def get_effective_path_entries() -> list[str]:
    """Return the list of directory entries in the current process's PATH."""
    raw_path = os.environ.get("PATH", "")
    return [entry.strip() for entry in raw_path.split(os.pathsep) if entry.strip()]


def get_persistent_windows_user_path() -> tuple[str, int]:
    """Read the persistent User PATH from the Windows Registry (HKCU\\Environment\\Path).
    
    Returns (raw_value, reg_type). If not found, returns ("", winreg.REG_EXPAND_SZ).
    """
    if not is_windows():
        return "", 2  # REG_EXPAND_SZ

    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ) as key:
            val, reg_type = winreg.QueryValueEx(key, "Path")
            return str(val), int(reg_type)
    except FileNotFoundError:
        return "", winreg.REG_EXPAND_SZ
    except OSError as exc:
        raise PermissionError(f"Failed to read Windows User Environment registry: {exc}") from exc


def write_persistent_windows_user_path(new_path: str, reg_type: int) -> None:
    """Write the persistent User PATH to HKCU\\Environment\\Path and verify."""
    if not is_windows():
        raise OSError("Persistent PATH modification is only supported on native Windows.")

    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            "Environment",
            0,
            winreg.KEY_READ | winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, "Path", 0, reg_type, new_path)
    except OSError as exc:
        raise PermissionError(f"Permission denied modifying User Environment registry: {exc}") from exc

    # Verification: re-read from registry
    verified_val, _ = get_persistent_windows_user_path()
    if verified_val != new_path:
        raise RuntimeError("Verification failed: written registry value does not match expected PATH.")


def broadcast_environment_change() -> bool:
    """Notify running Windows processes that the User Environment has changed."""
    if not is_windows():
        return False
    try:
        import ctypes

        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        SMTO_ABORTIFHUNG = 0x0002
        result = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST,
            WM_SETTINGCHANGE,
            0,
            "Environment",
            SMTO_ABORTIFHUNG,
            5000,
            ctypes.byref(result),
        )
        return True
    except Exception:
        return False


def setup_windows_path(
    yes: bool = False,
    check_only: bool = False,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """Diagnose and optionally configure the Windows User PATH for CircuitGen."""
    if is_wsl():
        stdout.write(
            "CircuitGen PATH Setup:\n"
            "Detected Windows Subsystem for Linux (WSL).\n"
            "WSL manages its own Linux environment and cannot configure native Windows PATH via this tool.\n"
            "To make 'circuitgen' available in WSL:\n"
            "  1. Ensure ~/.local/bin is on your Linux PATH (in ~/.bashrc or ~/.zshrc).\n"
            "  2. Or install via pipx: pipx install circuitgen && pipx ensurepath\n"
        )
        return 0

    if not is_windows():
        stdout.write(
            f"CircuitGen PATH Setup:\n"
            f"Automated PATH setup is only applicable on native Windows (current platform: {sys.platform}).\n"
            f"On macOS and Linux, CLI commands are managed via your user binary directory (e.g. ~/.local/bin).\n"
            f"Recommended setup:\n"
            f"  pipx install circuitgen\n"
            f"  pipx ensurepath\n"
        )
        return 0

    # Native Windows execution
    stdout.write("CircuitGen Windows PATH Diagnostic & Setup\n")
    stdout.write("------------------------------------------\n")

    # Locate installed launcher
    launcher = find_installed_launcher()
    if not launcher:
        stderr.write(
            "Error: Could not find 'circuitgen.exe' in any candidate script directory.\n"
            "Please ensure CircuitGen is installed in the current Python environment:\n"
            "  python -m pip install -e .\n"
            "  or: python -m pip install circuitgen\n"
        )
        return 1

    launcher_dir = launcher.parent
    norm_launcher_dir = normalize_path(launcher_dir)
    stdout.write(f"Detected launcher : {launcher}\n")
    stdout.write(f"Target directory  : {launcher_dir}\n")

    # Read persistent user PATH
    try:
        persistent_path_raw, reg_type = get_persistent_windows_user_path()
    except Exception as exc:
        stderr.write(f"Error accessing Windows registry: {exc}\n")
        return 1

    persistent_entries = [e.strip() for e in persistent_path_raw.split(";") if e.strip()]
    normalized_persistent = [normalize_path(e) for e in persistent_entries]

    # Check effective PATH
    effective_entries = get_effective_path_entries()
    normalized_effective = [normalize_path(e) for e in effective_entries]

    already_in_persistent = norm_launcher_dir in normalized_persistent
    already_in_effective = norm_launcher_dir in normalized_effective

    if already_in_persistent:
        if already_in_effective:
            stdout.write(
                f"\n[PASS] '{launcher_dir}' is already in your persistent User PATH and active in this terminal.\n"
                "No changes are needed. You can run 'circuitgen' directly.\n"
            )
            return 0
        else:
            stdout.write(
                f"\n[PASS] '{launcher_dir}' is already configured in your persistent User PATH.\n"
                "However, this current terminal has an older PATH copy.\n"
                "Please close and restart your terminal (PowerShell, CMD, Git Bash, or VS Code) to use 'circuitgen'.\n"
            )
            return 0

    # Needs to be added
    if is_virtual_environment():
        stdout.write(
            "\n[WARNING] CircuitGen is currently running inside a virtual environment:\n"
            f"  Prefix: {sys.prefix}\n"
            "Adding a virtual environment's Scripts directory to your global persistent User PATH is\n"
            "generally not recommended because it may conflict with other Python tools or break\n"
            "if this virtual environment is deleted or relocated.\n"
            "For a globally accessible CLI tool, we recommend: pipx install circuitgen\n\n"
        )

    if check_only:
        stdout.write(
            f"[NEEDS SETUP] '{launcher_dir}' is NOT in your persistent User PATH.\n"
            "To add it permanently, run: python -m circuitgen setup-path\n"
        )
        return 1

    # Request user confirmation unless --yes was passed
    if not yes:
        stdout.write(
            f"The following directory will be appended to your persistent Windows User PATH:\n"
            f"  {launcher_dir}\n\n"
            "This will modify only your current user account's registry (HKCU\\Environment\\Path).\n"
            "System-wide PATH will not be modified, and administrator privileges are not required.\n\n"
        )
        try:
            prompt_answer = input("Do you want to proceed? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            stdout.write("\nSetup cancelled.\n")
            return 0

        if prompt_answer not in ("y", "yes"):
            stdout.write("Operation cancelled by user. No changes were made.\n")
            return 0

    # Build new PATH
    clean_target = str(launcher_dir)
    if persistent_path_raw:
        sep = ";" if not persistent_path_raw.endswith(";") else ""
        new_user_path = f"{persistent_path_raw}{sep}{clean_target}"
    else:
        new_user_path = clean_target

    # Determine registry type (preserve REG_EXPAND_SZ if '%' present or originally REG_EXPAND_SZ)
    import winreg

    final_type = (
        winreg.REG_EXPAND_SZ
        if ("%" in new_user_path or reg_type == winreg.REG_EXPAND_SZ)
        else winreg.REG_SZ
    )

    try:
        write_persistent_windows_user_path(new_user_path, final_type)
    except Exception as exc:
        stderr.write(f"\n[FAIL] Failed to update Windows User PATH: {exc}\n")
        return 1

    broadcast_environment_change()

    stdout.write(
        "\n[SUCCESS] Successfully added CircuitGen directory to your Windows User PATH!\n"
        f"Added: {clean_target}\n\n"
        "Important Notes:\n"
        "1. Existing terminal sessions (PowerShell, CMD, Git Bash, VS Code) will not see this change automatically.\n"
        "   Please close and reopen your terminal window to run 'circuitgen'.\n"
        "2. If you relocate, upgrade, or reinstall Python in the future, you may need to run this command again.\n"
    )
    return 0
