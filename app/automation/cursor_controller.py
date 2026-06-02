"""Drive the Cursor editor: open it, create files and inject generated code.

Two complementary strategies are used:

1. **File + CLI** (preferred, reliable): write the code to a real file and open
   it with the ``cursor`` CLI (``cursor <path>``). No fragile UI typing.
2. **Clipboard paste** (fallback / "type into active editor"): focus Cursor,
   open a new tab, and paste from the clipboard. Pasting beats character typing
   for speed and correctness with symbols/indentation.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from app.config.logger import get_logger
from app.config.settings import settings

logger = get_logger(__name__)

try:
    import pyautogui
except Exception:  # pragma: no cover
    pyautogui = None  # type: ignore[assignment]

try:
    import pyperclip
except Exception:  # pragma: no cover
    pyperclip = None  # type: ignore[assignment]


# Default file extension per language for generated files.
LANG_EXTENSIONS = {
    "csharp": ".cs",
    "c#": ".cs",
    "dotnet": ".cs",
    "angular": ".ts",
    "typescript": ".ts",
    "javascript": ".js",
    "python": ".py",
    "sql": ".sql",
    "html": ".html",
    "css": ".css",
}


class CursorController:
    """Open Cursor and write generated code into it."""

    def __init__(self) -> None:
        self._cli = shutil.which("cursor")

    # -- launching ----------------------------------------------------------
    def open(self) -> dict[str, Any]:
        try:
            if self._cli:
                subprocess.Popen([self._cli])
            else:
                subprocess.Popen(["cmd", "/c", "start", "", "cursor"], shell=False)
        except Exception as exc:
            return {"status": "error", "message": f"Couldn't open Cursor: {exc}"}
        return {"status": "ok", "message": "Opening Cursor."}

    def open_file(self, path: Path) -> bool:
        """Open an existing file in Cursor. Returns True on success."""
        try:
            if self._cli:
                subprocess.Popen([self._cli, str(path)])
                return True
            subprocess.Popen(["cmd", "/c", "start", "", "cursor", str(path)], shell=False)
            return True
        except Exception:
            logger.exception("Failed to open file in Cursor")
            return False

    # -- writing code -------------------------------------------------------
    def write_code(
        self,
        code: str,
        *,
        language: str = "python",
        filename: str | None = None,
        save_file: bool = True,
        type_into_editor: bool = True,
    ) -> dict[str, Any]:
        """Save code to a file and/or inject it into Cursor's editor."""
        ext = LANG_EXTENSIONS.get(language.lower(), ".txt")
        name = filename or f"generated{ext}"
        if not Path(name).suffix:
            name += ext

        saved_path: Path | None = None
        if save_file:
            saved_path = Path(settings.generated_dir) / name
            saved_path.parent.mkdir(parents=True, exist_ok=True)
            saved_path.write_text(code, encoding="utf-8")
            # Open the saved file directly in Cursor (most reliable path).
            if self.open_file(saved_path):
                msg = f"Wrote {name} and opened it in Cursor."
                return {"status": "ok", "message": msg, "path": str(saved_path)}

        # Fallback: paste into a fresh editor tab.
        if type_into_editor:
            pasted = self._paste_into_cursor(code)
            if pasted:
                return {"status": "ok", "message": "Typed the code into Cursor."}

        # Last resort: at least copy to clipboard for the user to paste.
        if pyperclip is not None:
            pyperclip.copy(code)
            return {
                "status": "ok",
                "message": "Copied the code to your clipboard. Paste it into Cursor with Ctrl+V.",
                "path": str(saved_path) if saved_path else None,
            }
        return {"status": "error", "message": "Couldn't deliver code to Cursor (no clipboard/automation available)."}

    # -- internals ----------------------------------------------------------
    def _focus_cursor(self) -> bool:
        try:
            from pywinauto import Desktop  # imported lazily; heavy import

            windows = Desktop(backend="uia").windows()
            for win in windows:
                title = (win.window_text() or "").lower()
                if "cursor" in title:
                    win.set_focus()
                    return True
        except Exception as exc:
            logger.debug("pywinauto focus failed: %s", exc)
        return False

    def _paste_into_cursor(self, code: str) -> bool:
        if pyautogui is None or pyperclip is None:
            return False
        try:
            self.open()
            time.sleep(2.0)  # give Cursor a moment to come to the foreground
            self._focus_cursor()
            pyperclip.copy(code)
            pyautogui.hotkey("ctrl", "n")  # new file
            time.sleep(0.4)
            pyautogui.hotkey("ctrl", "v")  # paste
            return True
        except Exception:
            logger.exception("Failed to paste into Cursor")
            return False
