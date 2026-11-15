"""Local import folder. The folder is mounted read-only; this code never writes to it."""

import asyncio
from collections.abc import Callable
from pathlib import Path

from app.services.importers.base import VIDEO_EXTENSIONS, ImportItem, ImportRefError

_CHUNK = 8 * 1024 * 1024


class LocalImportSource:
    id = "local"

    def __init__(self, root: Path) -> None:
        self.root = root

    def resolve(self, ref: str) -> Path:
        """Return the file for a ref, refusing anything that escapes the import folder."""
        root = self.root.resolve()
        candidate = (root / ref).resolve()
        if not candidate.is_relative_to(root) or candidate == root:
            raise ImportRefError(f"`{ref}` is outside the import folder")
        if not candidate.is_file():
            raise ImportRefError(f"`{ref}` was not found in the import folder")
        if candidate.suffix.lower() not in VIDEO_EXTENSIONS:
            raise ImportRefError(f"`{ref}` is not a video file")
        return candidate

    def _scan(self) -> list[ImportItem]:
        if not self.root.is_dir():
            return []
        items = []
        for path in self.root.rglob("*"):
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
                stat = path.stat()
                items.append(
                    ImportItem(
                        ref=path.relative_to(self.root).as_posix(),
                        name=path.name,
                        size_bytes=stat.st_size,
                        modified_at=stat.st_mtime,
                    )
                )
        return sorted(items, key=lambda i: i.modified_at, reverse=True)

    async def list(self) -> list[ImportItem]:
        return await asyncio.to_thread(self._scan)

    def _copy(self, src: Path, dest: Path, on_progress: Callable[[float], None] | None) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        total = src.stat().st_size or 1
        partial = dest.with_name(dest.name + ".part")
        done = 0
        with src.open("rb") as reader, partial.open("wb") as writer:
            while chunk := reader.read(_CHUNK):
                writer.write(chunk)
                done += len(chunk)
                if on_progress:
                    on_progress(done / total)
        partial.replace(dest)

    async def fetch(self, ref: str, dest: Path, on_progress: Callable[[float], None] | None = None) -> None:
        src = self.resolve(ref)
        if dest.is_file() and dest.stat().st_size == src.stat().st_size:
            return  # already copied; import steps are idempotent
        await asyncio.to_thread(self._copy, src, dest, on_progress)
