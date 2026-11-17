"""Clips: the deterministic post-processing (BUILD_SPEC 7.5) and the clips API."""

import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import session
from app.models import Clip, Event, Segment, Video
from app.services import clipfinder
from app.services.presets import load_presets

CONFIG = Path(__file__).resolve().parents[2] / "config"
PRESET = load_presets(CONFIG)[0]["boss_fight"]
RULES = PRESET.clip_rules


def ev(t: float, kind: str = "counter", length: float = 1.0, **extra) -> Event:
    return Event(video_id="v", t_start=t, t_end=t + length, type=kind, **extra)


FIGHT = [ev(10.0), ev(12.0), ev(14.0, "parry"), ev(20.0, "finisher", 2.0, intensity="high"), ev(40.0)]


# ---- pure functions ---------------------------------------------------------------


def test_clamp_keeps_a_clip_inside_the_video_and_at_least_three_seconds():
    assert clipfinder.clamp(-2.0, 8.0, 60.0) == (0.0, 8.0)
    assert clipfinder.clamp(50.0, 90.0, 60.0) == (50.0, 60.0)
    assert clipfinder.clamp(10.0, 11.0, 60.0) == (10.0, 13.0)
    assert clipfinder.clamp(59.0, 59.5, 60.0) == (57.0, 60.0)      # too short at the very end: grows backwards
    assert clipfinder.clamp(20.0, 10.0, 60.0) == (20.0, 23.0)      # an end before the start


def test_clamp_cuts_to_the_platform_maximum_without_losing_the_payoff():
    assert clipfinder.clamp(0.0, 300.0, 400.0, "shorts") == (0.0, 180.0)
    assert clipfinder.clamp(0.0, 300.0, 400.0, "tiktok") == (0.0, 300.0)
    assert clipfinder.clamp(0.0, 300.0, 400.0) == (0.0, 300.0)
    # The payoff sits at the end, so the start is cut instead.
    assert clipfinder.clamp(0.0, 300.0, 400.0, "reels", payoff_t=295.0) == (120.0, 300.0)


def test_snap_starts_before_the_first_event_and_ends_after_the_closing_one():
    # The finisher closes a clip (end_on), even with a later event of another type in range.
    events = FIGHT + [ev(23.5, "parry")]
    assert clipfinder.snap(8.0, 30.0, events, RULES) == (9.5, 22.5)
    # No closing type in range: the last event closes it.
    assert clipfinder.snap(9.0, 16.0, events, RULES) == (9.5, 15.5)
    # Hidden events do not count, and a range with no events is left alone.
    assert clipfinder.snap(9.0, 16.0, [ev(10.0, hidden=True), ev(12.0)], RULES) == (11.5, 13.5)
    assert clipfinder.snap(30.0, 36.0, events, RULES) == (30.0, 36.0)


def test_stats_count_events_dead_time_and_the_crop_warning():
    events = FIGHT + [ev(15.0, "boss_attack", crop_safe_9x16=False)]
    numbers = clipfinder.stats(9.5, 22.5, events, [(5.0, 11.0), (16.0, 17.5), (30.0, 33.0)])
    assert numbers["event_counts"] == {"counter": 2, "parry": 1, "boss_attack": 1, "finisher": 1}
    assert numbers["dead_time_s"] == 3.0                      # 9.5–11 and 16–17.5; the run at 30 is outside
    assert numbers["dead_runs"] == [{"t_start": 9.5, "t_end": 11.0}, {"t_start": 16.0, "t_end": 17.5}]
    assert numbers["crop_warning"] is True
    assert clipfinder.stats(9.5, 14.5, FIGHT, [])["crop_warning"] is False


def test_the_payoff_defaults_to_the_closing_event():
    assert clipfinder.default_payoff(9.5, 22.5, FIGHT, RULES) == 20.0
    assert clipfinder.default_payoff(9.5, 15.5, FIGHT + [ev(11.0, "parry", intensity="high")], RULES) == 11.0
    assert clipfinder.default_payoff(9.5, 15.5, FIGHT, RULES) == 14.0     # no closer, none high: the last event
    assert clipfinder.default_payoff(30.0, 36.0, FIGHT, RULES) is None


def note(t_start, t_end, payoff=None, platform=None, events=FIGHT, dead=()):
    return clipfinder.analysis_note(t_start, t_end, payoff, platform, list(events), list(dead), PRESET)


def test_the_note_suggests_starting_later_when_the_first_event_lands_late():
    late = note(6.0, 22.5)
    assert late["id"] == "late_start" and late["apply"] == {"t_start": 9.5}
    assert "4.0 s after" in late["message"] and "Counter" in late["message"]
    assert note(9.5, 22.5) is None                                         # exactly snapped: nothing to say
    # Applying it would leave under 3 s, so it is advice only.
    assert note(6.0, 12.0, events=[ev(10.0)])["apply"] is None


def test_the_note_points_at_dead_time_and_trims_it_only_from_an_edge():
    at_start = note(9.5, 22.5, dead=[(9.5, 12.5)], events=[ev(9.6), ev(20.0, "finisher", 2.0)])
    assert at_start["id"] == "dead_time" and at_start["apply"] == {"t_start": 12.5} and at_start["at"] == [9.5, 12.5]
    at_end = note(9.5, 25.0, dead=[(22.0, 25.0)], events=[ev(10.0), ev(23.9)])
    assert at_end["apply"] == {"t_end": 22.0}
    middle = note(9.5, 22.5, dead=[(15.0, 18.0)])
    assert middle["id"] == "dead_time" and middle["apply"] is None and "one uncut range" in middle["message"]
    assert note(9.5, 22.5, dead=[(15.0, 16.5)]) is None                    # 1.5 s is not worth a note


def test_the_note_asks_for_an_on_screen_promise_when_the_payoff_is_late():
    late = note(9.5, 22.5, payoff=20.0)
    assert late["id"] == "late_payoff" and late["apply"] is None and "10 s in" in late["message"]
    assert note(9.5, 22.5, payoff=14.0) is None


def test_the_note_covers_a_long_tail_the_limit_the_crop_and_an_empty_range():
    tail = note(9.5, 30.0)
    assert tail["id"] == "long_tail" and tail["apply"] == {"t_end": 22.5} and "Finisher" in tail["message"]
    too_long = note(0.0, 200.0, platform="shorts", events=[ev(0.5), ev(199.0)])
    assert too_long["id"] == "too_long" and too_long["apply"] == {"t_end": 180.0}
    assert note(0.0, 200.0, payoff=199.0, platform="shorts", events=[ev(0.5)])["apply"] == {"t_start": 20.0}
    crop = note(9.5, 15.5, events=FIGHT + [ev(11.0, "boss_attack", crop_safe_9x16=False)])
    assert crop["id"] == "crop" and "Boss move" in crop["message"]
    assert note(30.0, 36.0)["id"] == "no_events"


# ---- the API ----------------------------------------------------------------------


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
    with TestClient(main.app) as test_client:
        yield test_client
    get_settings.cache_clear()


def seed(client: TestClient) -> str:
    with session(client.app.state.engine) as s:
        video = Video(title="Gate Keeper", preset_id="boss_fight", status="ready", duration_s=60.0, fps=30.0)
        s.add(video)
        s.flush()
        s.add_all(Event(video_id=video.id, t_start=e.t_start, t_end=e.t_end, type=e.type, intensity=e.intensity)
                  for e in FIGHT)
        s.add(Segment(video_id=video.id, kind="dead_time", t_start=30.0, t_end=34.0))
        s.commit()
        return video.id


def test_a_clip_made_by_hand_is_measured_and_noted(client):
    video_id = seed(client)
    empty = client.get(f"/videos/{video_id}/clips").json()
    assert empty["clips"] == [] and empty["can_find"] is False and empty["finding"] is False
    assert empty["limits"] == {"min_s": 3.0, "max_s": {"shorts": 180.0, "reels": 180.0, "tiktok": 600.0}}

    made = client.post(f"/videos/{video_id}/clips", json={"t_start": 6.0, "t_end": 22.5, "platform": "reels"})
    assert made.status_code == 201
    clip = made.json()
    assert (clip["name"], clip["status"], clip["source"], clip["platform"]) == ("Clip 1", "selected", "user", "reels")
    assert (clip["duration_s"], clip["payoff_t"], clip["frame_t"], clip["edited"]) == (16.5, 20.0, 20.0, False)
    assert clip["event_counts"] == {"counter": 2, "parry": 1, "finisher": 1} and clip["dead_time_s"] == 0.0
    assert clip["note"]["id"] == "late_start" and clip["exports"] == []

    # Applying the note is a plain edit of the edge it names; the next note follows.
    applied = client.patch(f"/clips/{clip['id']}", json=clip["note"]["apply"]).json()
    assert applied["t_start"] == 9.5 and applied["edited"] is True and applied["note"]["id"] == "late_payoff"
    assert client.get(f"/videos/{video_id}/clips").json()["clips"] == [applied]

    assert client.post(f"/videos/{video_id}/clips", json={"t_start": 10.0, "t_end": 12.0}).status_code == 422
    assert client.post(f"/videos/{video_id}/clips", json={"t_start": 50.0, "t_end": 70.0}).status_code == 422
    assert client.post("/videos/missing/clips", json={"t_start": 1.0, "t_end": 9.0}).status_code == 404


def test_trimming_renaming_selecting_and_resetting_a_clip(client):
    video_id = seed(client)
    with session(client.app.state.engine) as s:
        found = Clip(video_id=video_id, name="Finisher", t_start=9.5, t_end=22.5, status="candidate", source="finder",
                     orig_start=9.5, orig_end=22.5, payoff_t=20.0)
        s.add(found)
        s.commit()
        clip_id = found.id

    # A nudge makes a proposal the user's; the numbers follow the new range.
    nudged = client.patch(f"/clips/{clip_id}", json={"t_end": 35.0}).json()
    assert (nudged["t_end"], nudged["status"], nudged["dead_time_s"], nudged["edited"]) == (35.0, "selected", 4.0, True)
    assert nudged["dead_runs"] == [{"t_start": 30.0, "t_end": 34.0}]
    # Moving the range off its payoff picks a new one inside it.
    moved = client.patch(f"/clips/{clip_id}", json={"t_start": 9.5, "t_end": 16.0}).json()
    assert moved["payoff_t"] == 14.0
    reset = client.patch(f"/clips/{clip_id}", json={"reset": True}).json()
    assert (reset["t_start"], reset["t_end"], reset["edited"], reset["payoff_t"]) == (9.5, 22.5, False, 20.0)

    renamed = client.patch(f"/clips/{clip_id}", json={"name": "  The kill  ", "status": "candidate"}).json()
    assert (renamed["name"], renamed["status"]) == ("The kill", "candidate")
    assert client.patch(f"/clips/{clip_id}", json={"payoff_t": 12.0}).json()["frame_t"] == 12.0

    for bad in ({"t_end": 11.0}, {"t_end": 61.0}, {"t_start": -1.0}, {"name": " "}, {"name": None},
                {"payoff_t": 50.0}, {"status": "exported"}, {"platform": "vine"}):
        assert client.patch(f"/clips/{clip_id}", json=bad).status_code == 422, bad
    assert client.patch("/clips/missing", json={"name": "x"}).status_code == 404

    assert client.delete(f"/clips/{clip_id}").status_code == 204
    assert client.get(f"/videos/{video_id}/clips").json()["clips"] == []
    assert client.delete(f"/clips/{clip_id}").status_code == 404


def test_hiding_an_event_changes_what_the_clip_shows(client):
    video_id = seed(client)
    clip = client.post(f"/videos/{video_id}/clips", json={"t_start": 9.5, "t_end": 22.5}).json()
    assert clip["event_counts"]["finisher"] == 1
    finisher = next(e for e in client.get(f"/videos/{video_id}/timeline").json()["events"] if e["type"] == "finisher")
    client.patch(f"/events/{finisher['id']}", json={"hidden": True})
    after = client.get(f"/videos/{video_id}/clips").json()["clips"][0]
    assert "finisher" not in after["event_counts"]
    assert after["note"]["id"] == "long_tail"      # the clip now runs well past its last event


# ---- export through the API (7.6) ---------------------------------------------------


def wait_for_job(client: TestClient, job_id: str, timeout_s: float = 60) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.1)
    raise AssertionError("the job did not finish")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is only in the Docker image")
def test_exporting_a_clip_writes_a_file_records_it_and_serves_it(client, tmp_path):
    source = tmp_path / "data" / "source.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=8:size=640x360:rate=30",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=8", "-shortest", "-c:v", "libx264", "-g", "30",
         "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)], check=True,
    )
    with session(client.app.state.engine) as s:
        video = Video(title="Gate Keeper", topic="Phantom Blade Zero", subject="Zhuo Bi, the Gatekeeper",
                      preset_id="boss_fight", status="ready", duration_s=8.0, fps=30.0, source_path=str(source))
        s.add(video)
        s.commit()
        video_id = video.id
    clip = client.post(f"/videos/{video_id}/clips", json={"t_start": 1.5, "t_end": 5.5, "name": "The kill"}).json()

    assert client.post(f"/clips/{clip['id']}/export", json={"crop": "9x16", "mode": "lossless"}).status_code == 422
    assert client.post(f"/clips/{clip['id']}/export", json={"mode": "fast"}).status_code == 422
    assert client.post("/clips/missing/export", json={}).status_code == 404

    started = client.post(f"/clips/{clip['id']}/export", json={"crop": "9x16"})
    assert started.status_code == 202 and started.json()["kind"] == "clip_export"
    job = wait_for_job(client, started.json()["id"])
    assert job["status"] == "done", job
    assert job["message"].startswith("Exported 1080×1920 at 30 fps · 4.0 s")
    after = client.get(f"/videos/{video_id}/clips").json()["clips"][0]
    assert after["status"] == "exported"
    (vertical,) = after["exports"]
    assert (vertical["crop"], vertical["mode"], vertical["width"], vertical["height"], vertical["fps"]) == (
        "9x16", "accurate", 1080, 1920, 30.0)
    assert (vertical["t_start"], vertical["t_end"], vertical["real_start"], vertical["real_end"]) == (1.5, 5.5, 1.5, 5.5)
    assert "path" not in vertical and vertical["url"] == f"/exports/{vertical['id']}/download"

    got = client.get(vertical["url"])
    assert got.status_code == 200 and got.headers["content-type"] == "video/mp4"
    assert 'filename="TheLazyRonin_PhantomBladeZero_ZhuoBitheGatekeeper_Thekill_9x16.mp4"' in got.headers["content-disposition"]
    assert len(got.content) == vertical["size_bytes"] > 1000

    # A lossless copy starts on the keyframe before the in-point, and the export says where.
    job = wait_for_job(client, client.post(f"/clips/{clip['id']}/export", json={"mode": "lossless"}).json()["id"])
    assert job["status"] == "done" and "lossless, cut on a keyframe" in job["message"]
    exports = {x["mode"]: x for x in client.get(f"/videos/{video_id}/clips").json()["clips"][0]["exports"]}
    assert exports["lossless"]["real_start"] == 1.0 and (exports["lossless"]["width"], exports["lossless"]["height"]) == (640, 360)

    # Exporting the same shape again replaces the earlier file; deleting the clip removes them all.
    client.patch(f"/clips/{clip['id']}", json={"t_end": 6.0})
    wait_for_job(client, client.post(f"/clips/{clip['id']}/export", json={"crop": "9x16"}).json()["id"])
    folder = tmp_path / "data" / "media" / video_id / "clips" / clip["id"]
    assert sorted(p.name for p in folder.iterdir()) == ["9x16_accurate_1500-6000.mp4", "none_lossless_1500-5500.mp4"]
    assert client.get(vertical["url"]).status_code == 404
    assert client.delete(f"/clips/{clip['id']}").status_code == 204
    assert not folder.exists()

    # A job that needs its options cannot be retried blind.
    assert client.post(f"/jobs/{job['id']}/retry").status_code == 409
