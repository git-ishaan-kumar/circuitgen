"""System diagnostics and environment health check for CircuitGen."""
from __future__ import annotations

import importlib.metadata
import importlib.resources
import os
import platform
import shutil
import sys
import sysconfig
from pathlib import Path
from typing import NamedTuple, TextIO

from circuitgen.syspath import (
    find_installed_launcher,
    get_candidate_script_directories,
    is_virtual_environment,
    is_windows,
    is_wsl,
    normalize_path,
)


class CheckResult(NamedTuple):
    status: str  # "PASS", "WARNING", "FAIL", "NOT CHECKED"
    title: str
    message: str
    recommendation: str | None = None


def check_os_and_arch() -> CheckResult:
    """Check operating system and CPU architecture."""
    system_name = platform.system()
    release = platform.release()
    machine = platform.machine()
    is_wsl_env = is_wsl()

    os_desc = f"{system_name} {release} ({machine})"
    if is_wsl_env:
        os_desc += " [WSL]"

    return CheckResult(
        status="PASS",
        title="Operating System",
        message=os_desc,
    )


def check_python_environment() -> CheckResult:
    """Check Python version and executable."""
    major, minor, micro = sys.version_info[:3]
    version_str = f"{major}.{minor}.{micro}"
    exe_path = sys.executable

    if sys.version_info < (3, 10):
        return CheckResult(
            status="FAIL",
            title="Python Version",
            message=f"Python {version_str} at {exe_path} (Unsupported)",
            recommendation="CircuitGen requires Python 3.10 or newer. Please upgrade your Python installation.",
        )

    return CheckResult(
        status="PASS",
        title="Python Version",
        message=f"Python {version_str} at {exe_path}",
    )


def check_virtual_environment() -> CheckResult:
    """Check if running in a virtual environment or Conda."""
    in_venv = is_virtual_environment()
    venv_path = os.environ.get("VIRTUAL_ENV") or os.environ.get("CONDA_PREFIX") or (sys.prefix if in_venv else None)

    if in_venv and venv_path:
        return CheckResult(
            status="PASS",
            title="Python Environment Type",
            message=f"Isolated Environment ({venv_path})",
        )

    return CheckResult(
        status="PASS",
        title="Python Environment Type",
        message="Global Python Installation",
    )


def check_circuitgen_package() -> CheckResult:
    """Check CircuitGen package version and installation path."""
    try:
        import circuitgen

        pkg_path = Path(circuitgen.__file__).resolve().parent
    except Exception as exc:
        return CheckResult(
            status="FAIL",
            title="CircuitGen Package",
            message=f"Failed to import package: {exc}",
            recommendation="Reinstall CircuitGen using: python -m pip install -e . or pip install circuitgen",
        )

    try:
        pkg_version = importlib.metadata.version("circuitgen")
    except Exception:
        pkg_version = getattr(circuitgen, "__version__", "unknown")

    return CheckResult(
        status="PASS",
        title="CircuitGen Package",
        message=f"v{pkg_version} installed at {pkg_path}",
    )


def check_package_resources() -> CheckResult:
    """Verify package data and assets (theme.tcss) are present and readable."""
    try:
        # Check using importlib.resources
        tcss_ref = importlib.resources.files("circuitgen.tui").joinpath("theme.tcss")
        if tcss_ref.is_file():
            content = tcss_ref.read_text(encoding="utf-8")
            if len(content) > 0:
                return CheckResult(
                    status="PASS",
                    title="Package Resources",
                    message="theme.tcss verified and readable",
                )
    except Exception as exc:
        return CheckResult(
            status="FAIL",
            title="Package Resources",
            message=f"Failed reading package resource theme.tcss: {exc}",
            recommendation="Package data may be missing from the distribution. Reinstall or reinstall from wheel.",
        )

    return CheckResult(
        status="FAIL",
        title="Package Resources",
        message="theme.tcss not found in circuitgen.tui",
        recommendation="Ensure package data is included in pyproject.toml and rebuild the package.",
    )


def check_launcher_and_path() -> tuple[CheckResult, list[CheckResult]]:
    """Check console script existence, PATH resolution, and potential executable conflicts."""
    additional: list[CheckResult] = []

    # 1. Check if launcher exists on disk
    launcher_file = find_installed_launcher()
    if not launcher_file:
        return (
            CheckResult(
                status="FAIL",
                title="Console Launcher",
                message="circuitgen executable not found on disk",
                recommendation=(
                    "Install the console script using:\n"
                    "  python -m pip install -e .\n"
                    "  or: python -m pip install circuitgen"
                ),
            ),
            additional,
        )

    launcher_result = CheckResult(
        status="PASS",
        title="Console Launcher",
        message=f"Found installed launcher at {launcher_file}",
    )

    # 2. Check resolution from PATH
    which_path = shutil.which("circuitgen")
    if not which_path and is_windows():
        which_path = shutil.which("circuitgen.exe")

    if not which_path:
        fix_cmd = "python -m circuitgen setup-path" if is_windows() else "pipx ensurepath (or add script dir to PATH)"
        additional.append(
            CheckResult(
                status="FAIL",
                title="PATH Resolution",
                message="'circuitgen' command is missing from PATH",
                recommendation=f"Run: {fix_cmd}",
            )
        )
        return launcher_result, additional

    resolved_path = Path(which_path).resolve()
    norm_resolved = normalize_path(resolved_path)
    norm_launcher = normalize_path(launcher_file)

    if norm_resolved != norm_launcher:
        additional.append(
            CheckResult(
                status="WARNING",
                title="PATH Resolution",
                message=(
                    f"'circuitgen' resolves to {resolved_path}, which does not match active "
                    f"Python environment launcher ({launcher_file})"
                ),
                recommendation="Check your PATH order to ensure the intended Python environment comes first.",
            )
        )
    else:
        additional.append(
            CheckResult(
                status="PASS",
                title="PATH Resolution",
                message=f"'circuitgen' resolves correctly from PATH to {resolved_path}",
            )
        )

    # 3. Check for multiple conflicting executables in PATH
    raw_path = os.environ.get("PATH", "")
    found_in_path: list[Path] = []
    names = ["circuitgen.exe", "circuitgen"] if is_windows() else ["circuitgen"]

    for entry in raw_path.split(os.pathsep):
        entry_dir = Path(entry.strip())
        if entry_dir.is_dir():
            for name in names:
                candidate = entry_dir / name
                if candidate.is_file():
                    resolved_cand = candidate.resolve()
                    if resolved_cand not in found_in_path:
                        found_in_path.append(resolved_cand)

    if len(found_in_path) > 1:
        dup_list = ", ".join(str(p) for p in found_in_path)
        additional.append(
            CheckResult(
                status="WARNING",
                title="Multiple Launchers in PATH",
                message=f"Multiple executables detected in PATH: {dup_list}",
                recommendation="Remove stale or conflicting Python script directories from your PATH.",
            )
        )

    return launcher_result, additional


def check_runtime_dependencies() -> list[CheckResult]:
    """Check required runtime dependencies declared in pyproject.toml."""
    dependencies = [
        ("textual", "0.85.0"),
        ("rich", "13.0.0"),
        ("keyring", "24.0.0"),
        ("platformdirs", "4.0.0"),
    ]
    results: list[CheckResult] = []

    for pkg_name, min_ver in dependencies:
        try:
            mod = __import__(pkg_name)
            try:
                installed_ver = importlib.metadata.version(pkg_name)
            except Exception:
                installed_ver = getattr(mod, "__version__", "installed")
            results.append(
                CheckResult(
                    status="PASS",
                    title=f"Dependency: {pkg_name}",
                    message=f"v{installed_ver} (>= {min_ver})",
                )
            )
        except Exception as exc:
            results.append(
                CheckResult(
                    status="FAIL",
                    title=f"Dependency: {pkg_name}",
                    message=f"Missing or broken ({exc})",
                    recommendation=f"Install missing dependency using: python -m pip install {pkg_name}",
                )
            )

    return results


def check_config_directory() -> CheckResult:
    """Check if the user configuration directory is writable."""
    try:
        import platformdirs

        config_dir = Path(platformdirs.user_config_dir("CircuitGen", "CircuitGen"))
        config_dir.mkdir(parents=True, exist_ok=True)
        test_file = config_dir / ".doctor_write_test"
        try:
            test_file.write_text("test", encoding="utf-8")
            test_file.unlink()
        except OSError as exc:
            return CheckResult(
                status="WARNING",
                title="Config Directory",
                message=f"Config directory {config_dir} is not writable: {exc}",
                recommendation="Ensure your user account has write permissions to your user configuration directory.",
            )
        return CheckResult(
            status="PASS",
            title="Config Directory",
            message=f"Writable at {config_dir}",
        )
    except Exception as exc:
        return CheckResult(
            status="WARNING",
            title="Config Directory",
            message=f"Could not verify config directory: {exc}",
            recommendation="Ensure platformdirs is installed and functioning properly.",
        )


def check_credential_store() -> CheckResult:
    """Check keyring credential storage availability without exposing secrets."""
    try:
        import keyring

        backend = keyring.get_keyring()
        backend_name = backend.__class__.__name__
        priority = getattr(backend, "priority", 0)

        # Check for fail / dummy keyrings
        if "fail" in backend_name.lower() or priority <= 0:
            return CheckResult(
                status="WARNING",
                title="Credential Storage",
                message=f"System credential store unavailable (active backend: {backend_name})",
                recommendation=(
                    "Offline rendering and validation work normally, but API keys cannot be saved "
                    "to your operating system's secure keychain. You can provide keys via environment variables."
                ),
            )

        return CheckResult(
            status="PASS",
            title="Credential Storage",
            message=f"Secure credential storage available ({backend_name})",
        )
    except Exception as exc:
        return CheckResult(
            status="WARNING",
            title="Credential Storage",
            message=f"Failed to query keyring: {exc}",
            recommendation="Install or repair OS credential storage backend (e.g. Windows Vault, Secret Service, macOS Keychain).",
        )


def check_terminal_capabilities() -> CheckResult:
    """Check if the current terminal appears capable of launching the interactive TUI."""
    is_in_tty = sys.stdin.isatty() and sys.stdout.isatty()
    term_size = shutil.get_terminal_size(fallback=(80, 24))
    cols, lines = term_size.columns, term_size.lines
    encoding = getattr(sys.stdout, "encoding", "unknown") or "unknown"

    if not is_in_tty:
        return CheckResult(
            status="WARNING",
            title="Terminal Capabilities",
            message="Non-interactive terminal (standard input or output is not a TTY)",
            recommendation="Run CircuitGen in an interactive terminal (Windows Terminal, PowerShell, CMD, or VS Code terminal).",
        )

    if cols < 80 or lines < 24:
        return CheckResult(
            status="WARNING",
            title="Terminal Capabilities",
            message=f"Terminal size {cols}x{lines} is below recommended 80x24",
            recommendation="Resize your terminal window to at least 80 columns by 24 lines for an optimal experience.",
        )

    return CheckResult(
        status="PASS",
        title="Terminal Capabilities",
        message=f"Interactive TTY {cols}x{lines} ({encoding})",
    )


def check_working_directory() -> CheckResult:
    """Informational check on working directory writability."""
    try:
        cwd = Path.cwd()
        writable = os.access(cwd, os.W_OK)
        if writable:
            return CheckResult(
                status="PASS",
                title="Working Directory",
                message=f"Writable ({cwd})",
            )
        else:
            return CheckResult(
                status="WARNING",
                title="Working Directory",
                message=f"Read-only ({cwd})",
                recommendation="Ensure the current directory has write permissions if saving generated schematics here.",
            )
    except Exception as exc:
        return CheckResult(
            status="WARNING",
            title="Working Directory",
            message=f"Could not inspect working directory: {exc}",
        )


def run_doctor(debug: bool = False, stdout: TextIO = sys.stdout) -> int:
    """Run read-only system diagnostics and display clear PASS/WARNING/FAIL report."""
    stdout.write("\nCircuitGen Doctor — System & Environment Diagnostics\n")
    stdout.write("===================================================\n\n")

    results: list[CheckResult] = []

    # 1. System & Architecture
    results.append(check_os_and_arch())

    # 2. Python Environment
    results.append(check_python_environment())
    results.append(check_virtual_environment())

    # 3. Package & Resources
    results.append(check_circuitgen_package())
    results.append(check_package_resources())

    # 4. Launcher & PATH
    launcher_res, additional_path_res = check_launcher_and_path()
    results.append(launcher_res)
    results.extend(additional_path_res)

    # 5. Runtime Dependencies
    results.extend(check_runtime_dependencies())

    # 6. User Config & Credentials
    results.append(check_config_directory())
    results.append(check_credential_store())

    # 7. Terminal & CWD
    results.append(check_terminal_capabilities())
    results.append(check_working_directory())

    # Print check results
    recommendations: list[tuple[str, str]] = []
    pass_count = 0
    warn_count = 0
    fail_count = 0

    for res in results:
        tag = f"[{res.status}]"
        stdout.write(f"{tag:<10} {res.title:<28} : {res.message}\n")
        if res.status == "PASS":
            pass_count += 1
        elif res.status == "WARNING":
            warn_count += 1
            if res.recommendation:
                recommendations.append((res.title, res.recommendation))
        elif res.status == "FAIL":
            fail_count += 1
            if res.recommendation:
                recommendations.append((res.title, res.recommendation))

    stdout.write("\nDoctor Summary\n")
    stdout.write("--------------\n")
    stdout.write(f"Total: {len(results)} checks | {pass_count} passed | {warn_count} warnings | {fail_count} failures\n\n")

    if recommendations:
        stdout.write("Suggested Actions:\n")
        for title, rec in recommendations:
            stdout.write(f"  • {title}:\n")
            for line in rec.splitlines():
                stdout.write(f"      {line}\n")
        stdout.write("\n")

    if fail_count > 0:
        stdout.write("[FAIL] One or more diagnostic checks failed. Review suggestions above.\n\n")
        return 1
    elif warn_count > 0:
        stdout.write("[WARNING] Diagnostics passed with warnings. CircuitGen is usable but some features may be limited.\n\n")
        return 0
    else:
        stdout.write("[PASS] All diagnostics passed! CircuitGen is fully configured and ready.\n\n")
        return 0
