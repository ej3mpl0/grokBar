"""Persistent settings + Windows startup (Startup-folder shortcut, not registry)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import winreg
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger("grok_bar.settings")

APP_NAME = "GrokBar"
RUN_VALUE_NAME = "GrokBar"  # legacy registry name — cleaned up if present
SHORTCUT_NAME = "GrokBar.lnk"


@dataclass
class Settings:
    start_with_windows: bool = False
    refresh_seconds: int = 120

    @classmethod
    def from_dict(cls, data: dict) -> Settings:
        return cls(
            start_with_windows=bool(data.get("start_with_windows", False)),
            refresh_seconds=max(30, int(data.get("refresh_seconds", 120))),
        )


def settings_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return settings_dir() / "settings.json"


def load_settings() -> Settings:
    path = settings_path()
    if not path.exists():
        return Settings()
    try:
        with path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, dict):
            return Settings()
        return Settings.from_dict(raw)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        log.warning("Failed to load settings: %s", exc)
        return Settings()


def save_settings(settings: Settings) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(asdict(settings), fh, indent=2)


def startup_folder() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def startup_shortcut_path() -> Path:
    return startup_folder() / SHORTCUT_NAME


def launch_target() -> tuple[str, str, str]:
    """
    Return (target_path, working_directory, arguments) for the Startup shortcut.
    """
    if getattr(sys, "frozen", False):
        exe = sys.executable
        return exe, str(Path(exe).parent), ""

    python = sys.executable
    if os.name == "nt" and python.lower().endswith("python.exe"):
        candidate = python[:-10] + "pythonw.exe"
        if Path(candidate).exists():
            python = candidate

    # -m grok_bar needs package on PYTHONPATH; work from repo/install parent.
    work = str(Path(__file__).resolve().parent.parent)
    return python, work, "-m grok_bar"


def _legacy_registry_enabled() -> bool:
    if os.name != "nt":
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_READ,
        ) as key:
            try:
                winreg.QueryValueEx(key, RUN_VALUE_NAME)
                return True
            except FileNotFoundError:
                return False
    except OSError:
        return False


def _remove_legacy_registry() -> None:
    """Drop the old Run-key entry (AV often flags that as persistence)."""
    if os.name != "nt":
        return
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            try:
                winreg.DeleteValue(key, RUN_VALUE_NAME)
                log.info("Removed legacy registry startup key")
            except FileNotFoundError:
                pass
    except OSError as exc:
        log.debug("Could not remove legacy registry key: %s", exc)


def is_startup_enabled() -> bool:
    """True if Startup-folder shortcut exists (or legacy registry, pre-migration)."""
    if os.name != "nt":
        return False
    if startup_shortcut_path().is_file():
        return True
    return _legacy_registry_enabled()


def _create_shortcut(lnk_path: Path, target: str, workdir: str, args: str) -> None:
    """
    Create a .lnk via Windows Script Host (cscript).

    Prefer this over HKCU\\...\\Run — antivirus treats registry autoruns
    from unsigned PyInstaller binaries as high-risk persistence.
    """
    lnk_path.parent.mkdir(parents=True, exist_ok=True)
    # Escape for VBScript string literals
    def vbs_escape(s: str) -> str:
        return s.replace('"', '""')

    vbs = (
        'Set sh = CreateObject("WScript.Shell")\r\n'
        f'Set sc = sh.CreateShortcut("{vbs_escape(str(lnk_path))}")\r\n'
        f'sc.TargetPath = "{vbs_escape(target)}"\r\n'
        f'sc.WorkingDirectory = "{vbs_escape(workdir)}"\r\n'
        f'sc.Arguments = "{vbs_escape(args)}"\r\n'
        f'sc.Description = "{vbs_escape(APP_NAME)}"\r\n'
        f'sc.IconLocation = "{vbs_escape(target)},0"\r\n'
        "sc.Save\r\n"
    )
    script = settings_dir() / "_mk_startup.vbs"
    try:
        script.write_text(vbs, encoding="utf-8")
        # cscript is a normal Windows host; no elevation needed for user Startup.
        result = subprocess.run(
            ["cscript", "//nologo", str(script)],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to create startup shortcut: {result.stderr or result.stdout}"
            )
        if not lnk_path.is_file():
            raise RuntimeError("Startup shortcut was not created.")
        log.info("Startup shortcut created: %s -> %s %s", lnk_path, target, args)
    finally:
        try:
            script.unlink(missing_ok=True)
        except OSError:
            pass


def set_startup_enabled(enabled: bool) -> None:
    """Enable/disable launch at Windows sign-in via Startup folder shortcut."""
    if os.name != "nt":
        raise RuntimeError("Start with Windows is only supported on Windows.")

    # Always clean the old registry method (stops AV false positives on re-toggle).
    _remove_legacy_registry()

    lnk = startup_shortcut_path()
    if enabled:
        target, workdir, args = launch_target()
        if not Path(target).exists():
            raise FileNotFoundError(f"Launch target not found: {target}")
        _create_shortcut(lnk, target, workdir, args)
    else:
        try:
            lnk.unlink(missing_ok=True)
            log.info("Startup shortcut removed: %s", lnk)
        except OSError as exc:
            raise RuntimeError(f"Could not remove startup shortcut: {exc}") from exc


def apply_startup_setting(settings: Settings) -> Settings:
    """
    Keep Startup shortcut and settings.json in sync.

    Migrates away from legacy registry Run keys automatically.
    """
    try:
        # One-shot migration: registry-only install → shortcut, or strip registry.
        if _legacy_registry_enabled():
            log.info("Migrating startup from registry Run key to Startup folder")
            if settings.start_with_windows:
                set_startup_enabled(True)  # also deletes registry
            else:
                _remove_legacy_registry()

        currently = is_startup_enabled()
        if settings.start_with_windows and not currently:
            set_startup_enabled(True)
        elif not settings.start_with_windows and currently:
            set_startup_enabled(False)
        settings.start_with_windows = is_startup_enabled()
    except (OSError, RuntimeError) as exc:
        log.warning("Startup sync failed: %s", exc)
        settings.start_with_windows = is_startup_enabled()
    return settings
