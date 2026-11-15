"""The event engine's contract (BUILD_SPEC 7.3.1, D25).

Detectors propose `Detection`s; `merge` turns them into events. A detector never
writes to the database and never imports another detector, so one can be added,
changed or removed without touching the rest of the app.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from app.services.analysis import VideoContext
from app.services.llm.base import MediaResolution, VideoProvider
from app.services.playbook import Playbook
from app.services.presets import Preset


class Detection(BaseModel):
    t_start: float
    t_end: float | None = None
    type: str  # a preset event type id
    label: str = ""
    confidence: Literal["certain", "uncertain"] = "certain"
    intensity: Literal["low", "medium", "high"] | None = None
    crop_safe_9x16: bool | None = None
    detector: str  # id of the detector that produced it
    evidence: dict[str, Any] = Field(default_factory=dict)  # detector-specific details


@dataclass
class CallRecord:
    """One model call, for the `llm_call` log."""

    provider: str
    model: str
    purpose: str
    prompt: str
    tokens_in: int | None = None
    tokens_out: int | None = None
    latency_ms: int | None = None
    status: str = "ok"


@dataclass
class DetectionContext:
    proxy: Path
    duration_s: float
    preset: Preset
    video: VideoContext
    playbook: Playbook | None = None
    video_provider: VideoProvider | None = None
    fps: float | None = None
    media_resolution: MediaResolution | None = None
    on_status: Callable[[str], None] = lambda _msg: None
    on_call: Callable[[CallRecord], None] = lambda _call: None
    # Results a detector produces besides detections, keyed by detector id. The full
    # video pass leaves its basics, sections and fact proposals here.
    outputs: dict[str, Any] = field(default_factory=dict)


class Detector(Protocol):
    id: str

    def enabled_for(self, ctx: DetectionContext) -> bool:
        """False when this video lacks what the detector needs (a key, a playbook region)."""
        ...

    async def detect(self, ctx: DetectionContext) -> list[Detection]: ...
