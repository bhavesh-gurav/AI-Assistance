"""Automation package: desktop, system, browser, cursor and file controllers."""

from app.automation.browser_controller import BrowserController
from app.automation.cursor_controller import CursorController
from app.automation.desktop_controller import DesktopController
from app.automation.file_manager import FileManager
from app.automation.system_controller import SystemController

__all__ = [
    "BrowserController",
    "CursorController",
    "DesktopController",
    "FileManager",
    "SystemController",
]
