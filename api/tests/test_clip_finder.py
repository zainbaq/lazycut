"""The clip finder (BUILD_SPEC 7.5): picks become ranges in code, and the job through the API."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.db import session
from app.models import Event, IntensitySample, LLMCall, Segment, Video
from app.services import clipfinder as cf
from app.services.llm.base import LLMError, LLMResult
from app.services.presets import load_presets

CONFIG = Path(__file__).resolve().parents[2] / "config"
PRESET = load_presets(CONFIG)[0]["boss_fight"]

# e1 counter 10, e2 counter 12, e3 parry 14, e4 finisher 20-22, e5 counter 40, e6 boss move 50 (crop-unsafe)
SHAPE = [(10.0, "counter", 1.0), (12.0, "counter", 1.0), (14.0, "parry", 1.0), (20.0, "finisher", 2.0),
         (40.0, "counter", 1.0), (50.0, "boss_attack", 1.0)]


def context(duration: float = 60.0) -> cf.ClipContext:
    events = [Event(video_id="v", t_start=t, t_end=t + n, type=kind, intensity="high" if kind == "finisher" else "medium",
                    crop_safe_9x16=kind != "boss_attack") for t, kind, n in SHAPE]
    return cf.ClipContext(
        video=Video(id="v", title="Gate Keeper", topic="Phantom Blade Zero", subject="Zhuo Bi", duration_s=duration),
        preset=PRESET, events=events, dead=[(30.0, 34.0)],
        sections=[Segment(video_id="v", kind="section", t_start=0.0, t_end=30.0, label="Opening")],
        peaks=[Segment(video_id="v", kind="peak", t_start=20.0, t_end=22.0, label="The kill")],
        intensity=[0.0] * 20 + [1.0] * 20 + [0.5] * 80,
    )


def pick(first: str, last: str, payoff: str | None = None, name: str = "Clip") -> cf.Pick:
    return cf.Pick(name=name, first_event=first, last_event=last, payoff_event=payoff, reason="Because.")


def test_the_prompt_lists_every_event_with_an_id_and_the_rules_of_the_preset():
    text = cf.finder_prompt(context(), "Finisher", "reels", 30.0)
    assert 'The creator asked for: "Finisher"' in text and "about 30 s each; never over 180 s" in text
    assert "e1 0:10.0 1.0s Counter medium" in text and "e4 0:20.0 2.0s Finisher high" in text
    assert "e6 0:50.0 1.0s Boss move medium !crop" in text
    assert "Dead time (nothing happens): 0:30.0-0:34.0" in text and "Peak: 0:20.0-0:22.0 The kill" in text
    assert "Motion per 5 s from 0:00, 0 (still) to 9 (busiest): 009944444444" in text
    assert "closes a clip on: Finisher" in text and "first_event and last_event" in text
    timed = cf.finder_prompt(context(), "", None, None, mode="times")
    assert "t_start and t_end as M:SS.s" in timed and 'asked for: "the best clips"' in timed
    assert "usually 10 to 45 s." in timed


def test_a_pick_named_by_events_gets_its_edges_from_code():
    ctx = context()
    c = cf.resolve_anchor(pick("e1", "e4", "e4"), ctx)
    assert (c.t_start, c.t_end, c.payoff_t) == (9.5, 22.5, 20.0)        # 0.5 s lead-in and tail
    assert cf.resolve_anchor(pick("E4", " e1 "), ctx).t_start == 9.5      # reversed and untidy ids
    whole = cf.resolve_anchor(pick("start", "end"), ctx)
    assert (whole.t_start, whole.t_end) == (0.0, 60.0)
    assert cf.resolve_anchor(pick("e1", "e9"), ctx) is None               # no such event
    assert cf.resolve_anchor(pick("0:10", "e4"), ctx) is None             # a time is not an event
    assert cf.resolve_anchor(pick("e1", "e4", "e99"), ctx).payoff_t is None


def test_a_pick_given_as_times_is_snapped_to_the_events():
    ctx = context()
    timed = cf.TimedPick(name="Kill", t_start="0:08.0", t_end="0:25", payoff_t="0:20", reason="r")
    c = cf.resolve_timed(timed, ctx)
    assert (c.t_start, c.t_end, c.payoff_t) == (9.5, 22.5, 20.0)
    assert cf.resolve_timed(timed.model_copy(update={"t_end": "soon"}), ctx) is None
    assert cf.resolve_timed(timed.model_copy(update={"t_end": "0:05"}), ctx) is None


def test_finalise_clamps_drops_repeats_and_caps_the_count():
    ctx = context()
    made = cf.finalise([
        cf.resolve_anchor(pick("e1", "e4", "e4", "Kill"), ctx),
        cf.resolve_anchor(pick("e2", "e4", name="Same footage"), ctx),     # 11 of 13 s shared with the first
        None,
        cf.resolve_anchor(pick("e5", "e5", "e1", "Lone counter"), ctx),    # 2 s long, and its payoff is elsewhere
        cf.resolve_anchor(pick("e5", "end", name="To the end"), ctx),
    ], ctx, "reels")
    assert [c.name for c in made] == ["Kill", "Lone counter", "To the end"]
    assert (made[1].t_start, made[1].t_end, made[1].payoff_t) == (39.5, 42.5, None)   # grown to 3 s
    assert made[2].t_end == 60.0
    many = [cf.Candidate(f"c{i}", i * 10.0, i * 10.0 + 5, None, "") for i in range(8)]
    assert len(cf.finalise(many, context(200.0), None)) == cf.MAX_CANDIDATES
    assert cf.overlap((0, 10), (5, 15)) == pytest.approx(1 / 3) and cf.overlap((0, 5), (5, 9)) == 0.0


def test_without_a_model_clips_come_from_the_timeline_alone():
    ctx = context()
    made = cf.timeline_candidates(ctx, "reels", 15.0)
    assert [c.name for c in made] == ["The ending", "Busiest stretch"]     # the peak repeats the ending
    ending = made[0]
    assert (ending.t_start, ending.t_end, ending.payoff_t) == (9.5, 22.5, 20.0)
    assert all("timeline alone" in c.reason for c in made)
    assert cf.timeline_candidates(cf.ClipContext(video=ctx.video, preset=PRESET), "reels", None) == []


# ---- the job through the API ------------------------------------------------------


class FakeFinder:
    """Stands in for Claude: answers the finder's schema with canned picks."""

    model = "fake-claude"

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.answer = cf.FinderOut(clips=[
            cf.Pick(name="The kill", first_event="e1", last_event="e4", payoff_event="e4", reason="Ends on the finisher."),
            cf.Pick(name="Nearly the same", first_event="e2", last_event="e4", reason="A repeat."),
            cf.Pick(name="Ghost", first_event="e1", last_event="e77", reason="Names an event that is not there."),
            cf.Pick(name="Late counter", first_event="e5", last_event="e6", payoff_event="e5", reason="A second angle."),
        ])
        self.fail = False

    async def generate_json(self, prompt, schema, search=False, effort="low"):
        self.prompts.append(prompt)
        if self.fail:
            raise LLMError("Claude call failed: overloaded")
        assert schema is cf.FinderOut
        return LLMResult(parsed=self.answer, raw_text="{}", model=self.model,
                         usage={"input_tokens": 2300, "output_tokens": 400}, latency_s=0.4)


@pytest.fixture
def client(tmp_path, monkeypatch):
    (tmp_path / "inbox").mkdir()
    (tmp_path / "data").mkdir()
    for key, value in {
        "INBOX_DIR": tmp_path / "inbox", "DATA_DIR": tmp_path / "data", "CONFIG_DIR": CONFIG,
        "DB_PATH": tmp_path / "db" / "app.db", "GEMINI_API_KEY": "", "ANTHROPIC_API_KEY": "",
    }.items():
        monkeypatch.setenv(key, str(value))
    from app import main
    from app.settings import get_settings

    get_settings.cache_clear()
    finder = FakeFinder()
    monkeypatch.setattr(main, "claude_factory", lambda _settings: lambda: finder if finder is not None else None)
    with TestClient(main.app) as test_client:
        test_client.finder = finder
        yield test_client
    get_settings.cache_clear()


def seed(client: TestClient, events: bool = True) -> str:
    with session(client.app.state.engine) as s:
        video = Video(title="Gate Keeper", preset_id="boss_fight", status="ready", duration_s=60.0, fps=30.0)
        s.add(video)
        s.flush()
        if events:
            s.add_all(Event(video_id=video.id, t_start=t, t_end=t + n, type=kind, crop_safe_9x16=kind != "boss_attack")
                      for t, kind, n in SHAPE)
        s.add(Segment(video_id=video.id, kind="dead_time", t_start=30.0, t_end=34.0))
        s.add_all(IntensitySample(video_id=video.id, t=i * 0.5, score=0.5) for i in range(120))
        s.commit()
        return video.id


def find(client: TestClient, video_id: str, **body) -> dict:
    started = client.post(f"/videos/{video_id}/clips/find", json=body)
    assert started.status_code == 202, started.text
    job_id = started.json()["id"]
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.05)
    raise AssertionError("the finder did not finish")


def test_the_finder_turns_picks_into_candidates_and_keeps_what_the_user_kept(client):
    video_id = seed(client)
    job = find(client, video_id, prompt="  Finisher ", platform="shorts", target_len_s=20)
    assert (job["kind"], job["status"], job["message"]) == ("clip_find", "done", "2 clips found")
    assert 'asked for: "Finisher"' in client.finder.prompts[0] and "for Shorts" in client.finder.prompts[0]

    listing = client.get(f"/videos/{video_id}/clips").json()
    assert listing["can_find"] is True and listing["finding"] is False
    kill, late = listing["clips"]
    assert (kill["name"], kill["t_start"], kill["t_end"], kill["payoff_t"]) == ("The kill", 9.5, 22.5, 20.0)
    assert (kill["status"], kill["source"], kill["platform"], kill["prompt"]) == ("candidate", "finder", "shorts", "Finisher")
    assert kill["reason"] == "Ends on the finisher." and kill["edited"] is False
    assert (late["name"], late["t_start"], late["t_end"], late["crop_warning"]) == ("Late counter", 39.5, 51.5, True)
    with session(client.app.state.engine) as s:
        call = s.exec(select(LLMCall)).one()
        assert (call.purpose, call.provider, call.tokens_in, call.status) == ("clip_find", "anthropic", 2300, "ok")

    # Trimming a proposal makes it the user's. A new search replaces only the untouched ones.
    client.patch(f"/clips/{kill['id']}", json={"t_start": 9.0})
    client.finder.answer = cf.FinderOut(note="There is no phase change in this timeline.", clips=[
        cf.Pick(name="Opening", first_event="start", last_event="e3", reason="From the first frame."),
    ])
    job = find(client, video_id, prompt="Phase change")
    assert job["message"] == "1 clip found. There is no phase change in this timeline."
    names = {c["name"]: c["status"] for c in client.get(f"/videos/{video_id}/clips").json()["clips"]}
    assert names == {"The kill": "selected", "Opening": "candidate"}

    client.finder.answer = cf.FinderOut(note="Nothing like that happens here.")
    assert find(client, video_id, prompt="A dance")["message"] == "No clip found. Nothing like that happens here."
    assert [c["name"] for c in client.get(f"/videos/{video_id}/clips").json()["clips"]] == ["The kill"]


def test_the_finder_refuses_without_events_and_reports_a_failed_call(client):
    empty = seed(client, events=False)
    refused = client.post(f"/videos/{empty}/clips/find", json={"prompt": "Anything"})
    assert refused.status_code == 409 and "no events" in refused.json()["detail"]
    assert client.post("/videos/missing/clips/find", json={}).status_code == 404
    video_id = seed(client)
    assert client.post(f"/videos/{video_id}/clips/find", json={"platform": "vine"}).status_code == 422
    assert client.post(f"/videos/{video_id}/clips/find", json={"target_len_s": 1}).status_code == 422

    client.finder.fail = True
    job = find(client, video_id, prompt="Finisher")
    assert job["status"] == "error" and "overloaded" in job["error"]
    with session(client.app.state.engine) as s:
        assert s.exec(select(LLMCall)).one().status == "error"


def test_without_a_key_the_finder_reads_the_timeline_alone(client, monkeypatch):
    video_id = seed(client)
    monkeypatch.setattr(client.app.state.runner.deps, "text_provider", lambda: None)
    assert client.get(f"/videos/{video_id}/clips").json()["can_find"] is False
    job = find(client, video_id, prompt="Finisher", target_len_s=15)
    assert job["status"] == "done" and "the prompt was not read" in job["message"]
    clips = client.get(f"/videos/{video_id}/clips").json()["clips"]
    assert [c["name"] for c in clips] == ["The ending", "Busiest stretch"] and client.finder.prompts == []
