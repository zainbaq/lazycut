"""Provider interfaces. Gemini only watches video; Claude does all text reasoning (D24)."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel

MediaResolution = Literal["low", "medium", "high"]
Processing = Literal["static", "agentic"]


@dataclass
class LLMResult[T: BaseModel]:
    parsed: T
    raw_text: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    latency_s: float = 0.0


class LLMError(Exception):
    """A call failed for good (after retries)."""


class LLMParseError(LLMError):
    """The model answered, but the answer did not match the schema."""

    def __init__(self, message: str, raw_text: str) -> None:
        super().__init__(message)
        self.raw_text = raw_text


class VideoProvider(Protocol):
    async def analyze_video[T: BaseModel](
        self,
        path: Path,
        prompt: str,
        schema: type[T],
        fps: float | None = None,
        media_resolution: MediaResolution | None = None,
        processing: Processing = "static",
    ) -> LLMResult[T]:
        """Analyze a local video file that is already the right window."""
        ...


class TextProvider(Protocol):
    async def generate_json[T: BaseModel](
        self, prompt: str, schema: type[T], search: bool = False
    ) -> LLMResult[T]: ...
