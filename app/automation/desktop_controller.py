"""Launch, close and arrange desktop applications on Windows.

App launching prefers the Windows ``start`` shell verb (which resolves Store
apps and PATH entries), with a curated alias table for the common apps the
user asked for. Window management uses ``pyautogui`` hotkeys.
"""

from __future__ import annotations

import os
import platform
import subprocess
from typing import Any

from app.config.logger import get_logger

logger = get_logger(__name__)

try:
    import pyautogui
except Exception:  # pragma: no cover - optional dependency.
    pyautogui = None  # type: ignore[assignment]


# Friendly name -> launch target. Values are either an executable on PATH or a
# Windows shell command (URI / Store app) understood by ``start``.
APP_ALIASES: dict[str, str] = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "edge": "msedge",
    "microsoft edge": "msedge",
    "vs code": "code",
    "vscode": "code",
    "visual studio code": "code",
    "cursor": "cursor",
    "notepad": "notepad",
    "calculator": "calc",
    "calc": "calc",
    "file explorer": "explorer",
    "explorer": "explorer",
    "files": "explorer",
    "spotify": "spotify",
    "discord": "discord",
    "whatsapp": "whatsapp",
}

# Best-effort process names for taskkill when closing apps.
CLOSE_ALIASES: dict[str, str] = {
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "edge": "msedge.exe",
    "microsoft edge": "msedge.exe",
    "vs code": "Code.exe",
    "vscode": "Code.exe",
    "visual studio code": "Code.exe",
    "cursor": "Cursor.exe",
    "notepad": "notepad.exe",
    "calculator": "Calculator.exe",
    "calc": "Calculator.exe",
    "file explorer": "explorer.exe",
    "explorer": "explorer.exe",
    "spotify": "Spotify.exe",
    "discord": "Discord.exe",
    "whatsapp": "WhatsApp.exe",
}


class DesktopController:
    """Open/close apps and manage windows."""

    @property
    def is_windows(self) -> bool:
        return platform.system() == "Windows"

    def open_application(self, parameters: dict[str, Any]) -> dict[str, Any]:
        name = str(parameters.get("name", "")).strip()
        if not name:
            return {"status": "error", "message": "No application name provided."}

        target = APP_ALIASES.get(name.lower(), name)
        try:
            if self.is_windows:
                # `start` runs through cmd; empty "" is the window-title arg.
                subprocess.Popen(["cmd", "/c", "start", "", target], shell=False)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", "-a", target])
            else:
                subprocess.Popen([target])
        except Exception as exc:
            logger.exception("Failed to open %s", name)
            return {"status": "error", "message": f"Couldn't open {name}: {exc}"}

        return {"status": "ok", "message": f"Opening {name}."}

    def close_application(self, parameters: dict[str, Any]) -> dict[str, Any]:
        name = str(parameters.get("name", "")).strip()
        if not name:
            return {"status": "error", "message": "No application name provided."}

        if self.is_windows:
            process = CLOSE_ALIASES.get(name.lower(), name if name.lower().endswith(".exe") else f"{name}.exe")
            completed = subprocess.run(
                ["taskkill", "/IM", process, "/F"], capture_output=True, text=True, check=False
            )
        else:
            completed = subprocess.run(["pkill", "-f", name], capture_output=True, text=True, check=False)

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            return {"status": "error", "message": f"Couldn't close {name}. {detail}"}
        return {"status": "ok", "message": f"Closed {name}."}

    def minimize_all(self, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        if pyautogui is None:
            return {"status": "error", "message": "pyautogui is not installed."}
        try:
            # Win+D shows the desktop (minimises everything).
            pyautogui.hotkey("win", "d")
        except Exception as exc:
            return {"status": "error", "message": f"Couldn't minimise windows: {exc}"}
        return {"status": "ok", "message": "Minimising all windows."}
