"""Detections to events: a pure function, so merge rules can be tested and changed alone."""

from dataclasses import dataclass, field

from app.services.events.base import Detection

MERGE_WINDOW_S = 3.0


@dataclass
class MergedEvent:
    t_start: float
    t_end: float
    type: str
    label: str
    confidence: str
    intensity: str
    crop_safe_9x16: bool
    detections: list[Detection] = field(default_factory=list)

    def detected_by(self) -> list[dict]:
        return [
            {"detector": d.detector, "t_start": d.t_start, "label": d.label, "evidence": d.evidence}
            for d in self.detections
        ]


def merge(detections: list[Detection], priority: list[str], window_s: float = MERGE_WINDOW_S) -> list[MergedEvent]:
    """Group detections into events.

    - Detections of one type from *different* detectors within `window_s` are one event.
    - Detections from the *same* detector are never merged: a fight can hold many
      counters a second apart, and each is its own event.
    - The event's time, end and label come from the detection whose detector is
      earliest in `priority` (unknown detectors rank last).
    - Different types at the same moment stay separate; the eye test decides.
    """
    rank = {d: i for i, d in enumerate(priority)}

    def order(d: Detection) -> tuple[int, float]:
        return rank.get(d.detector, len(rank)), d.t_start

    groups: list[list[Detection]] = []
    for detection in sorted(detections, key=order):
        candidates = [
            g for g in groups
            if g[0].type == detection.type
            and all(d.detector != detection.detector for d in g)
            and abs(g[0].t_start - detection.t_start) <= window_s
        ]
        if candidates:
            min(candidates, key=lambda g: abs(g[0].t_start - detection.t_start)).append(detection)
        else:
            groups.append([detection])

    events = []
    for group in groups:
        lead = group[0]  # highest-priority detection, by construction
        crop = [d.crop_safe_9x16 for d in group if d.crop_safe_9x16 is not None]
        events.append(MergedEvent(
            t_start=lead.t_start,
            t_end=max(lead.t_end if lead.t_end is not None else lead.t_start, lead.t_start),
            type=lead.type,
            label=lead.label or next((d.label for d in group if d.label), ""),
            confidence=lead.confidence,
            intensity=next((d.intensity for d in group if d.intensity), "medium"),
            crop_safe_9x16=all(crop) if crop else True,
            detections=sorted(group, key=order),
        ))
    return sorted(events, key=lambda e: (e.t_start, e.type))
