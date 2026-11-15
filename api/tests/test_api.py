"""The API end to end on a generated video: import, analysis through the event engine, timeline, re-analysis.

Gemini is replaced by the fake provider; ffmpeg must be installed (it is in the API image).
"""

import asyncio
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.db import session
from app.models import Event, LLMCall, Video
from app.services.jobs import Bus
from tests.test_analysis import FakeProvider
from tests.test_research import FakeClaude

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")

CONFIG = Path(__file__).resolve().parents[2] / "config"


@pytest.fixture
def client(tmp_path, monkeypatch):
    inbox, data = tmp_path / "inbox", tmp_path / "data"
    inbox.mkdir()
    data.mkdir()
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=6:size=320x240:rate=30",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=6", "-shortest",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(inbox / "fight.mp4")],
        check=True,
    )
    (inbox / "notes.txt").write_text("not a video")
    for key, value in {
        "INBOX_DIR": inbox, "DATA_DIR": data, "CONFIG_DIR": CONFIG, "DB_PATH": tmp_path / "db" / "app.db",
        "GEMINI_API_KEY": "", "EVENT_DETECTORS": "gemini",
    }.items():
        monkeypatch.setenv(key, str(value))

    from app import main
    from app.settings import get_settings

    get_settings.cache_clear()
    provider = FakeProvider()
    monkeypatch.setattr(main, "gemini_factory", lambda _settings: lambda _on_status: provider)
    claude = FakeClaude()
    claude.canonical = "Byakue"
    monkeypatch.setattr(main, "claude_factory", lambda _settings: lambda: claude)
    with TestClient(main.app) as test_client:
        test_client.provider = provider
        yield test_client
    get_settings.cache_clear()


def wait_until_settled(client: TestClient, video_id: str, timeout_s: float = 90) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        video = client.get(f"/videos/{video_id}").json()
        if video["display_status"] not in ("importing", "analyzing"):
            return video
        time.sleep(0.3)
    raise AssertionError(f"video still busy: {video}")


def test_import_analyze_timeline_and_reanalysis(client):
    listing = client.get("/imports").json()
    assert [i["ref"] for i in listing["items"]] == ["fight.mp4"]
    assert listing["items"][0]["imported_video_id"] is None

    assert client.post("/videos", json={"ref": "../etc/passwd", "title": "x"}).status_code == 422
    assert client.post("/videos", json={"ref": "fight.mp4", "title": "x", "preset_id": "nope"}).status_code == 422
    created = client.post("/videos", json={
        "source": "local", "ref": "fight.mp4", "title": "Byakue", "subject": "Byakue",
        "topic": "Onimusha", "kind": "long", "preset_id": "boss_fight",
    })
    assert created.status_code == 201
    video_id = created.json()["id"]

    video = wait_until_settled(client, video_id)
    assert video["status"] == "ready"
    assert video["display_status"] == "needs_confirmation"  # hits_taken is required and unconfirmed
    assert abs(video["duration_s"] - 6.0) < 0.1 and video["width"] == 320
    for _ in range(100):  # research runs beside the analysis and is not part of the display status
        jobs = {j["kind"]: j["status"] for j in client.get(f"/videos/{video_id}").json()["jobs"]}
        if jobs.get("research") == "done":
            break
        time.sleep(0.05)
    assert jobs == {"import": "done", "analysis": "done", "research": "done"}
    assert client.get(f"/videos/{video_id}/research").json()["method"] == "search"
    assert video["analysis"]["event_count"] == 2
    assert client.get("/imports").json()["items"][0]["imported_video_id"] == video_id

    timeline = client.get(f"/videos/{video_id}/timeline").json()
    assert [(e["t_start"], e["type"], e["source"]) for e in timeline["events"]] == [
        (2.0, "counter", "model"), (4.5, "counter", "model"),
    ]
    assert timeline["events"][0]["detected_by"][0]["detector"] == "gemini"
    assert timeline["events"][0]["t_model_start"] == 2.0
    assert len(timeline["intensity"]["scores"]) >= 11
    assert timeline["segments"] == [{**timeline["segments"][0], "kind": "peak", "t_end": 6.0}]
    assert timeline["event_types"][0]["id"] == "counter"

    facts = {f["key"]: f for f in client.get(f"/videos/{video_id}/facts").json()}
    assert facts["counter_count"]["proposed_value"] == 2 and facts["counter_count"]["derive_from"] == "counter"
    assert facts["hits_taken"]["required"] is True and facts["hits_taken"]["confirmed"] is False

    frames = client.get(f"/videos/{video_id}/frames").json()
    assert frames["interval_s"] == 1.0 and len(frames["frames"]) == 6
    assert client.get(frames["frames"][2]["url"]).headers["content-type"] == "image/jpeg"
    assert client.get(f"/videos/{video_id}/frame", params={"t": 2.5, "w": 160}).status_code == 200

    whole = client.get(f"/videos/{video_id}/media")
    assert whole.status_code == 200 and whole.headers["content-type"] == "video/mp4"
    part = client.get(f"/videos/{video_id}/media", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100
    assert part.headers["content-range"].startswith("bytes 0-99/")

    engine = client.app.state.engine
    with session(engine) as s:
        purposes = sorted(c.purpose for c in s.exec(select(LLMCall)).all())
        assert purposes == ["analysis", "research_search", "research_structure"]
        first = s.exec(select(Event).where(Event.video_id == video_id).order_by(Event.t_start)).first()
        first.verified = True
        s.add(first)
        s.commit()
        kept_id = first.id

    job = client.post(f"/videos/{video_id}/analyze", json={})
    assert job.status_code == 202
    wait_until_settled(client, video_id)
    events = client.get(f"/videos/{video_id}/timeline").json()["events"]
    # The verified event survives; the re-detected one beside it is dropped as a duplicate.
    assert [(e["id"] == kept_id, e["t_start"]) for e in events] == [(True, 2.0), (False, 4.5)]

    client.post(f"/videos/{video_id}/analyze", json={"discard_user_work": True})
    wait_until_settled(client, video_id)
    events = client.get(f"/videos/{video_id}/timeline").json()["events"]
    assert all(e["id"] != kept_id and not e["verified"] for e in events) and len(events) == 2

    assert client.patch(f"/videos/{video_id}", json={"preset_id": "general"}).json()["preset_id"] == "general"
    folder = Path(client.app.state.runner.deps.settings.media_dir) / video_id
    assert folder.is_dir()
    assert client.delete(f"/videos/{video_id}").status_code == 204
    assert not folder.exists()
    assert client.get(f"/videos/{video_id}").status_code == 404
    with session(engine) as s:
        assert s.exec(select(Video)).all() == []


def test_analyze_without_a_key_is_refused(client, monkeypatch):
    client.app.state.runner.deps.video_provider = lambda _on_status: None
    client.app.state.runner.deps.text_provider = lambda: None
    created = client.post("/videos", json={"ref": "fight.mp4", "title": "No key"}).json()
    video = wait_until_settled(client, created["id"])
    assert [j["kind"] for j in video["jobs"]] == ["import"]  # no analysis was queued
    assert video["display_status"] == "ready"  # General has no required facts
    refused = client.post(f"/videos/{created['id']}/analyze", json={})
    assert refused.status_code == 409 and "GEMINI_API_KEY" in refused.json()["detail"]


async def test_bus_delivers_to_subscribers_only_after_they_join():
    bus = Bus()
    bus.publish("v1", "job.progress", {"n": 0})
    queue = bus.subscribe("v1")
    bus.publish("v1", "job.done", {"n": 1})
    bus.publish("v2", "job.done", {"n": 2})
    assert await asyncio.wait_for(queue.get(), 1) == 'event: job.done\ndata: {"n":1}\n\n'
    assert queue.empty()
    bus.unsubscribe("v1", queue)
    bus.publish("v1", "job.done", {"n": 3})
    assert queue.empty()
