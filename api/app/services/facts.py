"""Facts: keeping derived facts in step with the events, checking values, payloads (BUILD_SPEC 7.4)."""

from typing import Any

from sqlmodel import Session, select

from app.models import Event, Fact
from app.services.presets import FactDef, Preset


class FactValueError(ValueError):
    pass


def visible_of(events: list[Event], event_type: str) -> list[Event]:
    return sorted((e for e in events if e.type == event_type and not e.hidden), key=lambda e: e.t_start)


def derive(fact: Fact, definition: FactDef, events: list[Event]) -> None:
    """Point a derived fact at the visible events of its type. Confirmed facts keep their value."""
    linked = visible_of(events, definition.derive_from or "")
    fact.proposed_value = len(linked)
    fact.evidence_event_ids = [e.id for e in linked]
    fact.evidence_ts = [e.t_start for e in linked]


def sync_facts(s: Session, video_id: str, preset: Preset) -> list[Fact]:
    """One row per preset fact, in preset order; derived facts that are not confirmed follow the events.

    Creates missing rows (a video edited by hand before any analysis) and leaves rows of
    facts the preset no longer has alone. The caller commits.
    """
    rows = {f.key: f for f in s.exec(select(Fact).where(Fact.video_id == video_id)).all()}
    events = None
    result = []
    for definition in preset.facts:
        fact = rows.get(definition.key)
        if fact is None:
            fact = Fact(video_id=video_id, key=definition.key, label=definition.label)
            s.add(fact)
        if definition.derive_from:
            if events is None:
                events = list(s.exec(select(Event).where(Event.video_id == video_id)).all())
            if not fact.confirmed:
                derive(fact, definition, events)
                s.add(fact)
        result.append(fact)
    return result


def check_value(definition: FactDef | None, raw: Any) -> Any:
    """The value as stored for this fact type, or FactValueError with a message for the user."""
    if raw is None:
        return None
    kind = definition.type if definition else "text"
    if kind == "int":
        if isinstance(raw, bool) or not isinstance(raw, int | float) or float(raw) != int(raw) or raw < 0:
            raise FactValueError("Enter a whole number, 0 or more")
        return int(raw)
    if kind == "bool":
        if not isinstance(raw, bool):
            raise FactValueError("Enter yes or no")
        return raw
    if kind == "enum":
        options = definition.options if definition else []
        if raw not in options:
            raise FactValueError(f"Choose one of: {', '.join(options)}")
        return raw
    if not isinstance(raw, str):
        raise FactValueError("Enter text")
    return raw.strip() or None


def effective_value(fact: Fact) -> Any:
    return fact.value if fact.value is not None else fact.proposed_value


def fact_dict(fact: Fact, preset: Preset | None, events: list[Event] | None = None) -> dict:
    definition = next((f for f in preset.facts if f.key == fact.key), None) if preset else None
    derive_from = definition.derive_from if definition else None
    event_count = verified_count = None
    if derive_from and events is not None:
        linked = visible_of(events, derive_from)
        event_count = len(linked)
        verified_count = sum(e.verified for e in linked)
    return fact.model_dump() | {
        "type": definition.type if definition else "text",
        "options": definition.options if definition else [],
        "required": definition.required if definition else False,
        "derive_from": derive_from,
        "label": fact.label or (definition.label if definition else fact.key),
        "effective_value": effective_value(fact),
        "event_count": event_count,
        "verified_count": verified_count,
        "out_of_date": bool(fact.confirmed and event_count is not None and fact.value != event_count),
    }
