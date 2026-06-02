from __future__ import annotations

import asyncio
import os
import platform
import shlex
import subprocess
import webbrowser
from pathlib import Path
from typing import Any, Callable

from utils.file_manager import FileManager
from utils.logger import get_logger


logger = get_logger(__name__)


class CommandExecutor:
    def __init__(self, file_manager: FileManager) -> None:
        self.file_manager = file_manager
        self._actions: dict[str, Callable[[dict[str, Any]], Any]] = {
            "open_application": self.open_application,
            "close_application": self.close_application,
            "open_file": self.open_file,
            "search_file": self.search_file,
            "create_file": self.create_file,
            "delete_file": self.delete_file,
            "execute_shell_command": self.execute_shell_command,
            "control_system": self.control_system,
            "open_url": self.open_url,
        }

    async def execute(self, action: str, parameters: dict[str, Any]) -> dict[str, Any]:
        handler = self._actions.get(action)
        if handler is None:
            return {"status": "error", "message": f"Unsupported action: {action}"}

        try:
            result = await asyncio.to_thread(handler, parameters)
            if isinstance(result, dict):
                return result
            return {"status": "ok", "message": str(result)}
        except Exception as exc:
            logger.exception("Command failed: %s", action)
            return {"status": "error", "action": action, "message": str(exc)}

    def open_application(self, parameters: dict[str, Any]) -> dict[str, Any]:
        name = str(parameters.get("name", "")).strip()
        if not name:
            raise ValueError("Application name is required.")

        normalized = self._normalize_app_name(name)
        if platform.system() == "Windows":
            subprocess.Popen(["cmd", "/c", "start", "", normalized], shell=False)
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", "-a", normalized])
        else:
            subprocess.Popen([normalized])

        return {"status": "ok", "action": "open_application", "message": f"Opened {name}"}

    def close_application(self, parameters: dict[str, Any]) -> dict[str, Any]:
        name = str(parameters.get("name", "")).strip()
        if not name:
            raise ValueError("Application name is required.")

        if platform.system() == "Windows":
            process_name = name if name.lower().endswith(".exe") else f"{name}.exe"
            completed = subprocess.run(
                ["taskkill", "/IM", process_name, "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
        else:
            completed = subprocess.run(
                ["pkill", "-f", name],
                capture_output=True,
                text=True,
                check=False,
            )

        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())

        return {"status": "ok", "action": "close_application", "message": f"Closed {name}"}

    def open_file(self, parameters: dict[str, Any]) -> dict[str, Any]:
        path = Path(str(parameters.get("path", ""))).expanduser()
        if not path.exists():
            raise FileNotFoundError(path)

        if platform.system() == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

        return {"status": "ok", "action": "open_file", "message": f"Opened {path}"}

    def search_file(self, parameters: dict[str, Any]) -> dict[str, Any]:
        query = str(parameters.get("query", "")).strip()
        root = Path(str(parameters.get("root", Path.home()))).expanduser()
        if not query:
            raise ValueError("Search query is required.")
        if not root.exists():
            raise FileNotFoundError(root)

        matches = []
        for path in root.rglob("*"):
            if query.lower() in path.name.lower():
                matches.append(str(path))
            if len(matches) >= 25:
                break

        return {
            "status": "ok",
            "action": "search_file",
            "message": f"Found {len(matches)} result(s).",
            "results": matches,
        }

    def create_file(self, parameters: dict[str, Any]) -> dict[str, Any]:
        filename = str(parameters.get("filename") or parameters.get("path") or "").strip()
        content = str(parameters.get("content", ""))
        if not filename:
            raise ValueError("filename or path is required.")

        path = self.file_manager.write_file(filename, content)
        return {
            "status": "ok",
            "action": "create_file",
            "message": f"Created {path}",
            "path": str(path),
        }

    def delete_file(self, parameters: dict[str, Any]) -> dict[str, Any]:
        if not parameters.get("confirmed"):
            return {
                "status": "needs_confirmation",
                "action": "delete_file",
                "message": "Deletion requires confirmation. Repeat with confirmed=true.",
            }

        path = Path(str(parameters.get("path", ""))).expanduser()
        if not path.exists():
            raise FileNotFoundError(path)
        if path.is_dir():
            raise IsADirectoryError("delete_file only deletes files, not folders.")

        path.unlink()
        return {"status": "ok", "action": "delete_file", "message": f"Deleted {path}"}

    def execute_shell_command(self, parameters: dict[str, Any]) -> dict[str, Any]:
        command = str(parameters.get("command", "")).strip()
        if not command:
            raise ValueError("Shell command is required.")
        if self._looks_risky(command) and not parameters.get("confirmed"):
            return {
                "status": "needs_confirmation",
                "action": "execute_shell_command",
                "message": "This command may be risky. Repeat with confirmed=true to run it.",
                "command": command,
            }

        completed = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=int(parameters.get("timeout_seconds", 60)),
        )
        return {
            "status": "ok" if completed.returncode == 0 else "error",
            "action": "execute_shell_command",
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
        }

    def control_system(self, parameters: dict[str, Any]) -> dict[str, Any]:
        command = str(parameters.get("command", "")).lower().strip()
        if command not in {"shutdown", "restart", "sleep"}:
            raise ValueError("command must be shutdown, restart, or sleep.")
        if not parameters.get("confirmed"):
            return {
                "status": "needs_confirmation",
                "action": "control_system",
                "message": f"{command} requires confirmation. Repeat with confirmed=true.",
            }

        system = platform.system()
        if system == "Windows":
            commands = {
                "shutdown": ["shutdown", "/s", "/t", "0"],
                "restart": ["shutdown", "/r", "/t", "0"],
                "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
            }
        elif system == "Darwin":
            commands = {
                "shutdown": ["osascript", "-e", 'tell app "System Events" to shut down'],
                "restart": ["osascript", "-e", 'tell app "System Events" to restart'],
                "sleep": ["pmset", "sleepnow"],
            }
        else:
            commands = {
                "shutdown": ["systemctl", "poweroff"],
                "restart": ["systemctl", "reboot"],
                "sleep": ["systemctl", "suspend"],
            }

        subprocess.Popen(commands[command])
        return {"status": "ok", "action": "control_system", "message": f"Started {command}"}

    def open_url(self, parameters: dict[str, Any]) -> dict[str, Any]:
        url = str(parameters.get("url", "")).strip()
        if not url:
            raise ValueError("URL is required.")
        webbrowser.open(url)
        return {"status": "ok", "action": "open_url", "message": f"Opened {url}"}

    def _normalize_app_name(self, name: str) -> str:
        aliases = {
            "chrome": "chrome",
            "krom": "chrome",
            "google chrome": "chrome",
            "edge": "msedge",
            "vs code": "code",
            "vscode": "code",
            "visual studio code": "code",
            "notepad": "notepad",
            "calculator": "calc",
        }
        return aliases.get(name.lower(), name)

    def _looks_risky(self, command: str) -> bool:
        lowered = command.lower()
        risky_tokens = [
            " del ",
            " erase ",
            " format ",
            " rmdir ",
            " remove-item ",
            " rm ",
            "shutdown",
            "restart-computer",
            "taskkill",
        ]
        padded = f" {lowered} "
        return any(token in padded for token in risky_tokens) or ">" in command
