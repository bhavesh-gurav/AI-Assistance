from __future__ import annotations

from pathlib import Path


class FileManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir.resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def write_file(self, filename: str, content: str) -> Path:
        path = self._safe_path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def read_file(self, filename: str) -> str:
        return self._safe_path(filename).read_text(encoding="utf-8")

    def _safe_path(self, filename: str) -> Path:
        requested = Path(filename).expanduser()
        if requested.is_absolute():
            path = requested.resolve()
        else:
            path = (self.base_dir / requested).resolve()

        if self.base_dir not in path.parents and path != self.base_dir:
            raise ValueError(f"Refusing to write outside output directory: {path}")
        return path
