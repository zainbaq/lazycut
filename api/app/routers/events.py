"""The eye test: user edits to events, and fact confirmation (BUILD_SPEC 7.4, 9.4)."""

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.db import session
from app.models import Event, Fact, Video, utc_now
from app.services.facts import FactValueError, check_value, effective_value, fact_dict, sync_facts
from app.services.presets import Preset, load_presets
from app.settings import get_settings

router = APIRouter()

DEFAULT_LENGTH_S = 0.5  # a new event with no end lasts this long


def _session(request: Request) -> Session:
    return session(request.app.state.engine)


def _preset(video: Video) -> Preset:
    presets, _ = load_presets(get_settings().config_dir)
    return presets.get(video.preset_id) or presets["general"]


def _check_type(preset: Preset, event_type: str) -> None:
    if event_type not in {t.id for t in preset.event_types}:
        raise HTTPException(422, f"`{event_type}` is not an event type of the {preset.name} preset")


def _check_times(video: Video, t_start: float, t_end: float) -> None:
    duration = video.duration_s or 0.0
    if not (0 <= t_start <= duration and 0 <= t_end <= duration):
        raise HTTPException(422, f"Times must lie between 0 and {duration:.2f} s")
    if t_end < t_start:
        raise HTTPException(422, "An event cannot end before it starts")


def _event(s: Session, event_id: str) -> Event:
    event = s.get(Event, event_id)
    if event is None:
        raise HTTPException(404, "No such event")
    return event


def _refresh_facts(s: Session, video: Video) -> None:
    sync_facts(s, video.id, _preset(video))


class NewEvent(BaseModel):
    t_start: float
    type: str
    t_end: float | None = None
    label: str = ""
    # Restoring a deleted event (undo) sends it back whole.
    id: str | None = None
    t_model_start: float | None = None
    t_model_end: float | None = None
    intensity: Literal["low", "medium", "high"] = "medium"
    crop_safe_9x16: bool = True
    confidence: Literal["certain", "uncertain"] = "certain"
    source: Literal["model", "user"] = "user"
    detected_by: list[dict] = []
    verified: bool = False
    hidden: bool = False
    edited: bool = False


@router.post("/videos/{video_id}/events", status_code=201)
def add_event(video_id: str, body: NewEvent, request: Request) -> dict:
    with _session(request) as s:
        video = s.get(Video, video_id)
        if video is None:
            raise HTTPException(404, "No such video")
        preset = _preset(video)
        _check_type(preset, body.type)
        t_end = body.t_end if body.t_end is not None else min(body.t_start + DEFAULT_LENGTH_S, video.duration_s or 0.0)
        _check_times(video, body.t_start, max(t_end, body.t_start))
        data = body.model_dump(exclude_none=True) | {"t_end": max(t_end, body.t_start), "video_id": video_id}
        if body.id is not None:
            if s.get(Event, body.id) is not None:
                raise HTTPException(409, "That event already exists")
        else:
            # A brand-new event is the user's, whatever the body says.
            data |= {"source": "user", "detected_by": [], "t_model_start": None, "t_model_end": None, "edited": False}
        event = Event(**data)
        s.add(event)
        s.flush()
        _refresh_facts(s, video)
        s.commit()
        return event.model_dump()


class EventEdit(BaseModel):
    t_start: float | None = None
    t_end: float | None = None
    type: str | None = None
    label: str | None = None
    verified: bool | None = None
    hidden: bool | None = None


@router.patch("/events/{event_id}")
def edit_event(event_id: str, body: EventEdit, request: Request) -> dict:
    with _session(request) as s:
        event = _event(s, event_id)
        video = s.get(Video, event.video_id)
        changes = body.model_dump(exclude_unset=True)
        if any(changes.get(k) is None for k in ("t_start", "type", "verified", "hidden") if k in changes):
            raise HTTPException(422, "Leave a field out instead of sending null")
        t_start, t_end = event.t_start, event.t_end
        if "t_start" in changes:
            shift = changes["t_start"] - event.t_start
            t_start = changes["t_start"]
            t_end = changes["t_end"] if changes.get("t_end") is not None else event.t_end + shift
            if changes.get("t_end") is None:
                t_end = min(t_end, video.duration_s or t_end)  # a moved event stays inside the video
        elif changes.get("t_end") is not None:
            t_end = changes["t_end"]
        _check_times(video, t_start, t_end)
        if "type" in changes:
            _check_type(_preset(video), changes["type"])

        label = (changes["label"] or "").strip() if "label" in changes else event.label
        reshaped = (
            abs(t_start - event.t_start) > 1e-9 or abs(t_end - event.t_end) > 1e-9
            or changes.get("type", event.type) != event.type or label != event.label
        )
        event.t_start, event.t_end, event.label = t_start, t_end, label
        for key in ("type", "verified", "hidden"):
            if key in changes:
                setattr(event, key, changes[key])
        if reshaped and event.source == "model":
            event.edited = True
        s.add(event)
        s.flush()
        _refresh_facts(s, video)
        s.commit()
        return event.model_dump()


@router.delete("/events/{event_id}", status_code=204)
def delete_event(event_id: str, request: Request) -> Response:
    with _session(request) as s:
        event = _event(s, event_id)
        video = s.get(Video, event.video_id)
        s.delete(event)
        s.flush()
        _refresh_facts(s, video)
        s.commit()
    return Response(status_code=204)


class FactEdit(BaseModel):
    value: Any = Field(default=None)
    confirmed: bool | None = None


@router.put("/facts/{fact_id}")
def edit_fact(fact_id: str, body: FactEdit, request: Request) -> dict:
    with _session(request) as s:
        fact = s.get(Fact, fact_id)
        if fact is None:
            raise HTTPException(404, "No such fact")
        video = s.get(Video, fact.video_id)
        preset = _preset(video)
        definition = next((f for f in preset.facts if f.key == fact.key), None)
        sent = body.model_dump(exclude_unset=True)
        if "value" in sent:
            try:
                fact.value = check_value(definition, sent["value"])
            except FactValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        if sent.get("confirmed") is True:
            value = effective_value(fact)
            if value is None:
                raise HTTPException(422, "There is no value to confirm yet")
            fact.value, fact.confirmed, fact.confirmed_at = value, True, utc_now()
        elif sent.get("confirmed") is False:
            fact.confirmed, fact.confirmed_at = False, None
            if definition and definition.derive_from and "value" not in sent:
                fact.value = None  # an unlocked derived fact follows the events again (7.4)
        s.add(fact)
        s.flush()
        sync_facts(s, video.id, preset)
        s.commit()
        events = list(s.exec(select(Event).where(Event.video_id == video.id)).all())
        return fact_dict(fact, preset, events)
