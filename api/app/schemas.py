"""Analysis schemas.

Two shapes exist on purpose:

* the *request* model, built per preset and sent to the LLM as a JSON schema.
  Its event types and fact keys are enums from the preset, and its timestamps
  are either clock strings (`M:SS.s`) or numbers, depending on the time format;
* the *stored* model (`Analysis`), with float seconds and plain strings.
"""

from typing import Any, Literal

from pydantic import BaseModel, create_model

from app.services.presets import Preset
from app.services.timecode import parse_time

TimeFormat = Literal["clock", "seconds"]
Intensity = Literal["low", "medium", "high"]
Confidence = Literal["certain", "uncertain"]
Position = Literal[
    "top-left", "top", "top-right", "left", "center", "right",
    "bottom-left", "bottom", "bottom-right",
]


class OnScreenText(BaseModel):
    text: str
    position: Position
    persistent: bool


class Basics(BaseModel):
    subject_name_on_screen: str | None
    on_screen_text: list[OnScreenText]
    audio_notes: str


class Event(BaseModel):
    t_start: float
    t_end: float
    type: str
    label: str
    intensity: Intensity
    crop_safe_9x16: bool
    confidence: Confidence


class Segment(BaseModel):
    kind: Literal["peak", "section"]
    t_start: float
    t_end: float
    label: str


class FactProposal(BaseModel):
    key: str
    value: str
    evidence_ts: list[float]
    confidence: Confidence


class FirstSecond(BaseModel):
    t: int
    description: str
    intensity: Intensity


class Analysis(BaseModel):
    basics: Basics
    events: list[Event]
    segments: list[Segment]
    fact_proposals: list[FactProposal]
    first_seconds: list[FirstSecond]
    first_frame: str
    last_frame: str


def build_request_model(preset: Preset, time_format: TimeFormat = "clock") -> type[BaseModel]:
    """Build the LLM-facing model for one preset."""
    time_type: Any = str if time_format == "clock" else float
    event_type: Any = Literal[tuple(preset.event_type_ids())]
    fact_key: Any = Literal[tuple(f.key for f in preset.facts)] if preset.facts else str

    event = create_model(
        "EventOut",
        t_start=(time_type, ...),
        t_end=(time_type, ...),
        type=(event_type, ...),
        label=(str, ...),
        intensity=(Intensity, ...),
        crop_safe_9x16=(bool, ...),
        confidence=(Confidence, ...),
    )
    segment = create_model(
        "SegmentOut",
        kind=(Literal["peak", "section"], ...),
        t_start=(time_type, ...),
        t_end=(time_type, ...),
        label=(str, ...),
    )
    proposal = create_model(
        "FactProposalOut",
        key=(fact_key, ...),
        value=(str, ...),
        evidence_ts=(list[time_type], ...),
        confidence=(Confidence, ...),
    )
    return create_model(
        "AnalysisOut",
        basics=(Basics, ...),
        events=(list[event], ...),
        segments=(list[segment], ...),
        fact_proposals=(list[proposal], ...),
        first_seconds=(list[FirstSecond], ...),
        first_frame=(str, ...),
        last_frame=(str, ...),
    )


def normalise(raw: BaseModel, duration_s: float | None = None) -> Analysis:
    """Convert an LLM-facing result to the stored shape: float seconds, clamped and ordered."""
    data = raw.model_dump()

    def seconds(value: object) -> float:
        t = parse_time(value)
        return min(t, duration_s) if duration_s is not None else t

    for item in data["events"] + data["segments"]:
        start, end = seconds(item["t_start"]), seconds(item["t_end"])
        item["t_start"], item["t_end"] = start, max(start, end)
    for proposal in data["fact_proposals"]:
        proposal["evidence_ts"] = [seconds(t) for t in proposal["evidence_ts"]]
    data["events"].sort(key=lambda e: e["t_start"])
    data["segments"].sort(key=lambda s: s["t_start"])
    return Analysis.model_validate(data)
