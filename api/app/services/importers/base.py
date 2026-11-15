"""Import source interface. v1 ships the local folder; Google Drive is planned."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

VIDEO_EXTENSIONS = frozenset({".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".ts", ".flv", ".wmv"})


@dataclass(frozen=True)
class ImportItem:
    ref: str
    name: str
    size_bytes: int
    modified_at: float


class ImportRefError(ValueError):
    """The ref does not name a video file inside the import source."""


class ImportSource(Protocol):
    id: str

    async def list(self) -> list[ImportItem]: ...

    async def fetch(self, ref: str, dest: Path, on_progress: Callable[[float], None] | None = None) -> None: ...
