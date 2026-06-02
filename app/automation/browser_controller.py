"""Web actions: open URLs and run searches on popular sites."""

from __future__ import annotations

import urllib.parse
import webbrowser
from typing import Any

from app.config.logger import get_logger

logger = get_logger(__name__)


# engine -> (display name, search URL template with {q})
SEARCH_ENGINES: dict[str, tuple[str, str]] = {
    "google": ("Google", "https://www.google.com/search?q={q}"),
    "youtube": ("YouTube", "https://www.youtube.com/results?search_query={q}"),
    "github": ("GitHub", "https://github.com/search?q={q}"),
    "stackoverflow": ("Stack Overflow", "https://stackoverflow.com/search?q={q}"),
}

# Bare site shortcuts when no query is given.
SITE_HOMES: dict[str, str] = {
    "google": "https://www.google.com",
    "youtube": "https://www.youtube.com",
    "github": "https://github.com",
    "stackoverflow": "https://stackoverflow.com",
}


class BrowserController:
    """Opens URLs and performs site searches in the default browser."""

    def open_url(self, parameters: dict[str, Any]) -> dict[str, Any]:
        url = str(parameters.get("url", "")).strip()
        if not url:
            return {"status": "error", "message": "No URL provided."}
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        webbrowser.open(url)
        return {"status": "ok", "message": f"Opening {url}."}

    def web_search(self, parameters: dict[str, Any]) -> dict[str, Any]:
        engine = str(parameters.get("engine", "google")).lower().strip()
        query = str(parameters.get("query", "")).strip()

        if engine not in SEARCH_ENGINES:
            engine = "google"

        if not query:
            webbrowser.open(SITE_HOMES[engine])
            return {"status": "ok", "message": f"Opening {SEARCH_ENGINES[engine][0]}."}

        display, template = SEARCH_ENGINES[engine]
        url = template.format(q=urllib.parse.quote_plus(query))
        webbrowser.open(url)
        return {"status": "ok", "message": f"Searching {display} for {query}."}
