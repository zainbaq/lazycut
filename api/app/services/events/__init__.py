"""Event engine: detectors -> merge -> events (BUILD_SPEC 7.3.1, D25).

Nothing outside this package needs to know which detectors ran.
"""

import asyncio
from dataclasses import dataclass

from app.services.events.base import Detection, DetectionContext, Detector
from app.services.events.detectors.gemini import GeminiDetector
from app.services.events.merge import MergedEvent, merge

# id -> factory. Adding a detector is a new module plus one line here.
REGISTRY: dict[str, type] = {
    GeminiDetector.id: GeminiDetector,
}


class UnknownDetector(ValueError):
    pass


def build_detectors(ids: list[str]) -> list[Detector]:
    unknown = [i for i in ids if i not in REGISTRY]
    if unknown:
        raise UnknownDetector(f"unknown event detector(s) in EVENT_DETECTORS: {', '.join(unknown)}")
    return [REGISTRY[i]() for i in ids]


@dataclass
class EngineResult:
    events: list[MergedEvent]
    detections: list[Detection]
    ran: list[str]  # detectors that ran
    skipped: list[str]  # detectors not configured for this video


async def run_engine(ctx: DetectionContext, detectors: list[Detector]) -> EngineResult:
    """Run every enabled detector at once, then merge. A failing detector fails the run."""
    active = [d for d in detectors if d.enabled_for(ctx)]
    skipped = [d.id for d in detectors if d not in active]
    found = await asyncio.gather(*(d.detect(ctx) for d in active))
    detections = [det for batch in found for det in batch]
    events = merge(detections, [d.id for d in detectors])
    return EngineResult(events=events, detections=detections, ran=[d.id for d in active], skipped=skipped)


__all__ = [
    "REGISTRY", "Detection", "DetectionContext", "Detector", "EngineResult", "MergedEvent",
    "UnknownDetector", "build_detectors", "merge", "run_engine",
]
