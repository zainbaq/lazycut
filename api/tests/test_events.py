from pathlib import Path

import pytest

from app.services import events as engine_module
from app.services.analysis import VideoContext
from app.services.events import Detection, DetectionContext, build_detectors, merge, run_engine
from app.services.events.base import CallRecord
from app.services.events.detectors.gemini import GeminiDetector
from tests.test_analysis import PRESETS, FakeProvider


def det(t: float, kind: str, detector: str, label: str = "", **extra) -> Detection:
    return Detection(t_start=t, type=kind, detector=detector, label=label, **extra)


def test_merge_joins_detectors_but_never_repeats_from_one_detector():
    found = [
        det(10.0, "counter", "gemini", "Red burst"),
        det(11.0, "counter", "gemini", "Second counter a second later"),
        det(10.4, "counter", "flash", evidence={"red_share": 0.3}),
        det(36.7, "hit_taken", "gauge", evidence={"from": 0.49, "to": 0.12}),
        det(36.0, "hit_taken", "gemini", "Shockwave hits the player", intensity="high", crop_safe_9x16=False),
        det(36.2, "counter", "gemini", "Different type, same moment"),
    ]
    events = merge(found, priority=["gauge", "gemini", "flash"])

    assert [(e.t_start, e.type, [d.detector for d in e.detections]) for e in events] == [
        (10.0, "counter", ["gemini", "flash"]),
        (11.0, "counter", ["gemini"]),
        (36.2, "counter", ["gemini"]),
        (36.7, "hit_taken", ["gauge", "gemini"]),
    ]
    hit = events[3]
    # The time comes from the gauge (first in priority); the label and attributes fill in from Gemini.
    assert hit.label == "Shockwave hits the player"
    assert hit.intensity == "high" and hit.crop_safe_9x16 is False
    assert hit.detected_by()[0] == {"detector": "gauge", "t_start": 36.7, "label": "", "evidence": {"from": 0.49, "to": 0.12}}


def test_merge_window_and_closest_match():
    found = [det(10.0, "counter", "gemini"), det(20.0, "counter", "gemini"), det(13.5, "counter", "flash"), det(18.0, "counter", "flash")]
    events = merge(found, priority=["gemini", "flash"])
    assert [(e.t_start, len(e.detections)) for e in events] == [(10.0, 1), (13.5, 1), (20.0, 2)]


class FakeDetector:
    """A detector added without touching anything outside the engine's registry."""

    id = "fake"

    def __init__(self) -> None:
        self.seen: DetectionContext | None = None

    def enabled_for(self, ctx: DetectionContext) -> bool:
        return ctx.playbook is None  # stands in for "needs something this video lacks"

    async def detect(self, ctx: DetectionContext) -> list[Detection]:
        self.seen = ctx
        return [det(4.6, "counter", self.id, evidence={"why": "test"}), det(30.0, "finisher", self.id)]


def context(provider=None, calls=None) -> DetectionContext:
    return DetectionContext(
        proxy=Path("proxy.mp4"), duration_s=32.0, preset=PRESETS["boss_fight"], video=VideoContext("long", 32.0),
        video_provider=provider, on_call=(calls.append if calls is not None else lambda _c: None),
    )


async def test_a_new_detector_plugs_in_through_the_registry(monkeypatch):
    monkeypatch.setitem(engine_module.REGISTRY, "fake", FakeDetector)
    calls: list[CallRecord] = []
    ctx = context(FakeProvider(), calls)
    detectors = build_detectors(["gemini", "fake"])

    result = await run_engine(ctx, detectors)

    assert result.ran == ["gemini", "fake"] and result.skipped == []
    by_time = {(e.t_start, e.type): [d.detector for d in e.detections] for e in result.events}
    # The fake's counter at 4.6 s joins Gemini's at 4.5 s; its finisher stands alone.
    assert by_time[(4.5, "counter")] == ["gemini", "fake"]
    assert by_time[(30.0, "finisher")] == ["fake"]
    assert "gemini" in ctx.outputs  # basics, sections and fact proposals pass through
    assert calls[0].provider == "gemini" and calls[0].tokens_in == 9 and "Return JSON" in calls[0].prompt


async def test_detectors_without_what_they_need_are_skipped():
    result = await run_engine(context(provider=None), build_detectors(["gemini"]))
    assert result.ran == [] and result.skipped == ["gemini"] and result.events == []


def test_unknown_detector_ids_are_reported():
    with pytest.raises(ValueError, match="nope"):
        build_detectors(["gemini", "nope"])
    assert isinstance(build_detectors(["gemini"])[0], GeminiDetector)
