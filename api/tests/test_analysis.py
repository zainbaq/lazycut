from pathlib import Path

import pytest

from app.schemas import build_request_model, normalise
from app.services.analysis import VideoContext, estimate_input_tokens, render_prompt, run_analysis
from app.services.llm.base import LLMResult
from app.services.llm.gemini import _GaveUp, classify_error, strip_fences
from app.services.presets import load_presets
from app.services.timecode import format_clock, parse_time

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
PRESETS = load_presets(CONFIG_DIR)[0]

RAW = {
    "basics": {"subject_name_on_screen": "Byakue", "on_screen_text": [], "audio_notes": "Sword clashes."},
    "events": [
        {"t_start": "0:04.5", "t_end": "0:05.0", "type": "counter", "label": "Issen 2",
         "intensity": "high", "crop_safe_9x16": True, "confidence": "certain"},
        {"t_start": "0:02.0", "t_end": "0:01.0", "type": "counter", "label": "Issen 1",
         "intensity": "high", "crop_safe_9x16": True, "confidence": "certain"},
    ],
    "segments": [{"kind": "peak", "t_start": "0:27.0", "t_end": "0:40.0", "label": "Finisher"}],
    "fact_proposals": [{"key": "hits_taken", "value": "0", "evidence_ts": [], "confidence": "certain"}],
    "first_seconds": [{"t": 0, "description": "Boss leaps.", "intensity": "medium"}],
    "first_frame": "A courtyard.",
    "last_frame": "Victory text.",
}


@pytest.mark.parametrize(
    ("value", "seconds"),
    [(12.5, 12.5), ("12.5", 12.5), ("12.5s", 12.5), ("0:04.5", 4.5), ("1:04", 64.0), ("1:02:03.5", 3723.5)],
)
def test_parse_time(value, seconds):
    assert parse_time(value) == seconds


@pytest.mark.parametrize("value", ["", "abc", "1:2:3:4", -1, True])
def test_parse_time_rejects(value):
    with pytest.raises(ValueError):
        parse_time(value)


def test_format_clock():
    assert format_clock(4.5) == "0:04.5"
    assert format_clock(64) == "1:04.0"
    assert format_clock(300, decimals=0) == "5:00"
    assert format_clock(3723.5) == "1:02:03.5"


def test_request_model_limits_types_and_fact_keys():
    model = build_request_model(PRESETS["boss_fight"], "clock")
    schema = model.model_json_schema()
    assert schema["$defs"]["EventOut"]["properties"]["type"]["enum"] == PRESETS["boss_fight"].event_type_ids()
    assert schema["$defs"]["EventOut"]["properties"]["t_start"]["type"] == "string"
    assert "hits_taken" in schema["$defs"]["FactProposalOut"]["properties"]["key"]["enum"]
    with pytest.raises(ValueError):
        model.model_validate(RAW | {"events": [RAW["events"][0] | {"type": "highlight"}]})


def test_seconds_format_uses_numbers():
    schema = build_request_model(PRESETS["general"], "seconds").model_json_schema()
    assert schema["$defs"]["EventOut"]["properties"]["t_start"]["type"] == "number"


def test_normalise_orders_clamps_and_converts():
    parsed = build_request_model(PRESETS["boss_fight"], "clock").model_validate(RAW)
    analysis = normalise(parsed, duration_s=32.0)
    assert [e.t_start for e in analysis.events] == [2.0, 4.5]
    assert analysis.events[0].t_end == 2.0  # an end before its start is pulled up
    assert analysis.segments[0].t_end == 32.0  # clamped to the video
    assert analysis.fact_proposals[0].key == "hits_taken"


def test_prompt_carries_preset_vocabulary_only():
    video = VideoContext("long", 185, "Onimusha: Way of the Sword", "Byakue", "Issen = perfect counter")
    boss = render_prompt(PRESETS["boss_fight"], video)
    assert "- counter: The player lands a perfect counter or riposte." in boss
    assert "hits_taken (Hits taken, int): List each timestamp where the player's health drops" in boss
    assert "counter_count (Counters landed, int): Count the `counter` events" in boss
    assert "about 3:05 from Onimusha: Way of the Sword" in boss
    assert "M:SS.s" in boss
    assert "can contain 50 parries" in boss
    assert "Never merge repeats" in boss

    general = render_prompt(PRESETS["general"], VideoContext("long", 400, "Valheim", "Mountain base build"))
    assert "health" not in general.lower()
    assert "FACT PROPOSALS: none for this video" in general
    assert "Extra terms for this topic: none" in general


def test_token_estimate():
    assert estimate_input_tokens(300, 1, None) == 300 * 70 + 300 * 25
    assert estimate_input_tokens(300, 5, "high") == 1500 * 280 + 300 * 25


def test_strip_fences_and_error_classes():
    assert strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert strip_fences('{"a": 1}') == '{"a": 1}'
    assert classify_error(RuntimeError("429 RESOURCE_EXHAUSTED")) == "rate_limit"
    assert classify_error(RuntimeError("503 UNAVAILABLE")) == "server"
    assert classify_error(RuntimeError("400 INVALID_ARGUMENT")) == "fatal"
    assert classify_error(RuntimeError("429 RESOURCE_EXHAUSTED: requests per day limit exceeded on Free Tier")) == "fatal"
    # A background call that Gemini ends itself: out of quota waits, anything else retries.
    assert classify_error(_GaveUp("call ended as failed after 11 s: [Error(code='RESOURCE_EXHAUSTED')]")) == "rate_limit"
    assert classify_error(_GaveUp("call ended as failed after 300 s: no reason given")) == "server"


class FakeProvider:
    def __init__(self):
        self.calls = []

    async def analyze_video(self, path, prompt, schema, fps=None, media_resolution=None, processing="static"):
        self.calls.append({"fps": fps, "resolution": media_resolution, "processing": processing})
        return LLMResult(parsed=schema.model_validate(RAW), raw_text="{}", model="fake", usage={"total_input_tokens": 9})

    async def generate_json(self, prompt, schema, search=False):
        raise NotImplementedError


async def test_run_analysis_through_the_provider_interface():
    provider = FakeProvider()
    run = await run_analysis(
        provider, Path("proxy.mp4"), PRESETS["boss_fight"], VideoContext("long", 32.0), fps=5, media_resolution="high"
    )
    assert provider.calls == [{"fps": 5, "resolution": "high", "processing": "static"}]
    assert len(run.analysis.events) == 2
    assert run.usage == {"total_input_tokens": 9}
