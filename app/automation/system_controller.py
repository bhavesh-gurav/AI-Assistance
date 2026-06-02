"""System-level controls: power, volume and brightness.

Dangerous power actions (shutdown / restart) are gated by the assistant's
confirmation flow; this module only carries them out once approved.
"""

from __future__ import annotations

import ctypes
import platform
import subprocess
from typing import Any

from app.config.logger import get_logger

logger = get_logger(__name__)

try:
    import pyautogui
except Exception:  # pragma: no cover - optional dependency.
    pyautogui = None  # type: ignore[assignment]


# Actions that must be confirmed before running.
DANGEROUS_POWER = {"shutdown", "restart"}


class SystemController:
    """Power, volume and brightness control for Windows (with *nix fallbacks)."""

    @property
    def is_windows(self) -> bool:
        return platform.system() == "Windows"

    # -- power --------------------------------------------------------------
    def power(self, parameters: dict[str, Any]) -> dict[str, Any]:
        command = str(parameters.get("command", "")).lower().strip()
        if command not in {"shutdown", "restart", "lock", "sleep"}:
            return {"status": "error", "message": "Unknown power command."}

        try:
            if command == "lock":
                return self._lock()
            if self.is_windows:
                return self._windows_power(command)
            return self._unix_power(command)
        except Exception as exc:
            logger.exception("Power command failed: %s", command)
            return {"status": "error", "message": f"Power command failed: {exc}"}

    def _lock(self) -> dict[str, Any]:
        if self.is_windows:
            ctypes.windll.user32.LockWorkStation()  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["loginctl", "lock-session"])
        return {"status": "ok", "message": "Locking your screen."}

    def _windows_power(self, command: str) -> dict[str, Any]:
        mapping = {
            "shutdown": ["shutdown", "/s", "/t", "0"],
            "restart": ["shutdown", "/r", "/t", "0"],
            "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
        }
        subprocess.Popen(mapping[command])
        verb = {"shutdown": "Shutting down", "restart": "Restarting", "sleep": "Going to sleep"}[command]
        return {"status": "ok", "message": f"{verb} now."}

    def _unix_power(self, command: str) -> dict[str, Any]:
        mapping = {
            "shutdown": ["systemctl", "poweroff"],
            "restart": ["systemctl", "reboot"],
            "sleep": ["systemctl", "suspend"],
        }
        subprocess.Popen(mapping[command])
        return {"status": "ok", "message": f"{command.capitalize()} now."}

    # -- volume -------------------------------------------------------------
    def volume(self, parameters: dict[str, Any]) -> dict[str, Any]:
        command = str(parameters.get("command", "")).lower().strip()
        amount = int(parameters.get("amount", 5) or 5)
        if pyautogui is None:
            return {"status": "error", "message": "pyautogui is not installed for volume control."}

        try:
            if command == "up":
                for _ in range(max(1, amount)):
                    pyautogui.press("volumeup")
                return {"status": "ok", "message": "Volume up."}
            if command == "down":
                for _ in range(max(1, amount)):
                    pyautogui.press("volumedown")
                return {"status": "ok", "message": "Volume down."}
            if command in {"mute", "unmute"}:
                pyautogui.press("volumemute")  # this key toggles
                return {"status": "ok", "message": "Muted." if command == "mute" else "Unmuted."}
        except Exception as exc:
            return {"status": "error", "message": f"Volume control failed: {exc}"}
        return {"status": "error", "message": "Unknown volume command."}

    # -- brightness ---------------------------------------------------------
    def brightness(self, parameters: dict[str, Any]) -> dict[str, Any]:
        try:
            level = int(parameters.get("level", 50))
        except (TypeError, ValueError):
            return {"status": "error", "message": "Brightness level must be a number 0-100."}
        level = max(0, min(100, level))

        try:
            import screen_brightness_control as sbc  # optional dependency

            sbc.set_brightness(level)
            return {"status": "ok", "message": f"Brightness set to {level} percent."}
        except ImportError:
            # Fall back to WMI via PowerShell on Windows.
            if self.is_windows:
                ps = (
                    "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods)"
                    f".WmiSetBrightness(1,{level})"
                )
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps],
                    capture_output=True, text=True, check=False,
                )
                if result.returncode == 0:
                    return {"status": "ok", "message": f"Brightness set to {level} percent."}
                return {"status": "error", "message": "Brightness control not supported on this display."}
            return {"status": "error", "message": "Install screen-brightness-control for brightness."}
        except Exception as exc:
            return {"status": "error", "message": f"Brightness control failed: {exc}"}
