"""File system operations: folders, files, rename/move/delete, search, open.

Paths are resolved relative to the user's home directory unless absolute.
Common shortcuts ("downloads", "documents", "desktop") are recognised. Deletes
are physically possible here but the assistant requires confirmation first.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.config.logger import get_logger

logger = get_logger(__name__)


KNOWN_FOLDERS = {
    "downloads": Path.home() / "Downloads",
    "documents": Path.home() / "Documents",
    "desktop": Path.home() / "Desktop",
    "pictures": Path.home() / "Pictures",
    "music": Path.home() / "Music",
    "videos": Path.home() / "Videos",
    "home": Path.home(),
}


class FileManager:
    """Create, rename, move, delete, search and open files/folders."""

    def _resolve(self, raw: str) -> Path:
        token = str(raw).strip()
        if token.lower() in KNOWN_FOLDERS:
            return KNOWN_FOLDERS[token.lower()]
        path = Path(token).expanduser()
        if not path.is_absolute():
            path = Path.home() / path
        return path

    def create_folder(self, parameters: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve(parameters.get("path", ""))
        try:
            path.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return {"status": "error", "message": f"Couldn't create folder: {exc}"}
        return {"status": "ok", "message": f"Created folder {path.name}.", "path": str(path)}

    def create_file(self, parameters: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve(parameters.get("path", ""))
        content = str(parameters.get("content", ""))
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except Exception as exc:
            return {"status": "error", "message": f"Couldn't create file: {exc}"}
        return {"status": "ok", "message": f"Created file {path.name}.", "path": str(path)}

    def rename_path(self, parameters: dict[str, Any]) -> dict[str, Any]:
        src = self._resolve(parameters.get("path", ""))
        new_name = str(parameters.get("new_name", "")).strip()
        if not new_name:
            return {"status": "error", "message": "No new name provided."}
        if not src.exists():
            return {"status": "error", "message": f"{src} does not exist."}
        target = src.with_name(new_name)
        try:
            src.rename(target)
        except Exception as exc:
            return {"status": "error", "message": f"Couldn't rename: {exc}"}
        return {"status": "ok", "message": f"Renamed to {new_name}.", "path": str(target)}

    def move_path(self, parameters: dict[str, Any]) -> dict[str, Any]:
        src = self._resolve(parameters.get("path", ""))
        dst = self._resolve(parameters.get("destination", ""))
        if not src.exists():
            return {"status": "error", "message": f"{src} does not exist."}
        try:
            shutil.move(str(src), str(dst))
        except Exception as exc:
            return {"status": "error", "message": f"Couldn't move: {exc}"}
        return {"status": "ok", "message": f"Moved {src.name}.", "path": str(dst)}

    def delete_path(self, parameters: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve(parameters.get("path", ""))
        if not path.exists():
            return {"status": "error", "message": f"{path} does not exist."}
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        except Exception as exc:
            return {"status": "error", "message": f"Couldn't delete: {exc}"}
        return {"status": "ok", "message": f"Deleted {path.name}."}

    def search_files(self, parameters: dict[str, Any]) -> dict[str, Any]:
        query = str(parameters.get("query", "")).strip().lower()
        if not query:
            return {"status": "error", "message": "No search query provided."}
        root = self._resolve(parameters.get("root", "home"))
        if not root.exists():
            return {"status": "error", "message": f"{root} does not exist."}

        matches: list[str] = []
        try:
            for item in root.rglob("*"):
                if query in item.name.lower():
                    matches.append(str(item))
                if len(matches) >= 30:
                    break
        except Exception as exc:
            logger.warning("Search stopped early: %s", exc)

        msg = f"Found {len(matches)} match(es) for {query}." if matches else f"No matches for {query}."
        return {"status": "ok", "message": msg, "results": matches}

    def open_path(self, parameters: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve(parameters.get("path", ""))
        if not path.exists():
            return {"status": "error", "message": f"{path} does not exist."}
        try:
            if platform.system() == "Windows":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            return {"status": "error", "message": f"Couldn't open: {exc}"}
        return {"status": "ok", "message": f"Opening {path.name}."}
