"""The refine pass (BUILD_SPEC 7.3): one moment looked at closely, and a clip's edges refined with it."""

import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.db import session
from app.models import Event, LLMCall, Video
from app.services.events.refine import RefineOut, refine_moment, refine_prompt, window_around
from app.services.llm.base import LLMResult

CONFIG = Path(__file__).resolve().parents[2] / "config"
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is only in the Docker image")


class FakeWatcher:
    """Stands in for Gemini: answers each excerpt from a list, and remembers what it was shown."""

    def __init__(self, answers: list[RefineOut]) -> None:
        self.answers, self.seen = list(answers), []

    async def analyze_video(self, path, prompt, schema, fps=None, media_resolution=None, processing="static"):
        assert schema is RefineOut and Path(path).is_file()
        self.seen.append({"prompt": prompt, "fps": fps, "bytes": Path(path).stat().st_size})
        return LLMResult(parsed=self.answers.pop(0), raw_text="{}", model="fake-gemini",
                         usage={"total_input_tokens": 4200, "total_output_tokens": 50}, latency_s=0.2)


def test_the_window_stays_inside_the_video():
    assert window_around(30.0, 60.0) == (27.0, 33.0)
    assert window_around(1.0, 60.0) == (0.0, 6.0)
    assert window_around(59.0, 60.0) == (54.0, 60.0)
    assert window_around(2.0, 4.0) == (0.0, 4.0)
    text = refine_prompt("the first frame of this event: Counter.", 6.0, 3.0)
    assert "6.0-second excerpt" in text and "about 3.0 s into this excerpt" in text and "do not guess" in text


@pytest.fixture(scope="module")
def source(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("refine") / "source.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=20:size=640x360:rate=30",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


@needs_ffmpeg
async def test_a_refined_moment_gets_the_window_offset_added_back(source, tmp_path):
    watcher = FakeWatcher([RefineOut(found=True, t="2.4", confidence="certain", seen="A flash."),
                           RefineOut(found=False), RefineOut(found=True, t="9.0")])
    got = await refine_moment(watcher, source, 10.0, "the flash", 20.0, tmp_path)
    assert (got.t, got.confidence, got.seen, got.window) == (9.4, "certain", "A flash.", (7.0, 13.0))
    assert watcher.seen[0]["fps"] == 10.0 and watcher.seen[0]["bytes"] > 0 and "the flash" in watcher.seen[0]["prompt"]
    assert not list(tmp_path.glob("refine_*.mp4"))                       # the excerpt is removed afterwards
    assert (await refine_moment(watcher, source, 10.0, "the flash", 20.0, tmp_path)).t is None
    assert (await refine_moment(watcher, source, 10.0, "the flash", 20.0, tmp_path)).t is None   # 9 s into a 6 s excerpt


@pytest.fixture
def client(tmp_path, monkeypatch, source):
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
    watcher = FakeWatcher([])
    monkeypatch.setattr(main, "gemini_factory", lambda _settings: lambda _on_status: watcher)
    with TestClient(main.app) as test_client:
        test_client.watcher = watcher
        yield test_client
    get_settings.cache_clear()


@needs_ffmpeg
def test_refining_a_clip_moves_only_the_edges_it_is_sure_of(client, source):
    with session(client.app.state.engine) as s:
        video = Video(title="Gate Keeper", preset_id="boss_fight", status="ready", duration_s=20.0, fps=30.0,
                      source_path=str(source))
        s.add(video)
        s.flush()
        s.add_all([Event(video_id=video.id, t_start=5.0, t_end=6.0, type="counter", label="Ghoststep"),
                   Event(video_id=video.id, t_start=12.0, t_end=14.0, type="finisher")])
        s.commit()
        video_id = video.id
    clip = client.post(f"/videos/{video_id}/clips", json={"t_start": 4.5, "t_end": 14.5}).json()
    empty = client.post(f"/videos/{video_id}/clips", json={"t_start": 15.0, "t_end": 19.0}).json()
    assert client.get(f"/videos/{video_id}/clips").json()["can_refine"] is True
    assert client.post(f"/clips/{empty['id']}/refine").status_code == 409            # no events to look at
    assert client.post("/clips/missing/refine").status_code == 404

    # The start is seen 0.4 s later than stored; the end is not found, so it stays.
    client.watcher.answers = [RefineOut(found=True, t="3.4", confidence="certain"), RefineOut(found=False)]
    job_id = client.post(f"/clips/{clip['id']}/refine").json()["id"]
    deadline = time.monotonic() + 30
    while (job := client.get(f"/jobs/{job_id}").json())["status"] not in ("done", "error"):
        assert time.monotonic() < deadline
        time.sleep(0.05)
    assert job["status"] == "done", job
    assert job["message"] == "Refined: start 0:04.5 → 0:04.90; end kept (the moment was not found)"
    after = next(c for c in client.get(f"/videos/{video_id}/clips").json()["clips"] if c["id"] == clip["id"])
    assert (after["t_start"], after["t_end"], after["edited"]) == (4.9, 14.5, True)
    first, last = client.watcher.seen
    assert 'Counter "Ghoststep"' in first["prompt"] and "Finisher" in last["prompt"] and "before any dissolve" in last["prompt"]
    with session(client.app.state.engine) as s:
        calls = s.exec(select(LLMCall)).all()
        assert [(c.provider, c.purpose, c.tokens_in) for c in calls] == [("gemini", "clip_refine", 4200)] * 2
