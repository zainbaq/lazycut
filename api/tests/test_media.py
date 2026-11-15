import asyncio
import shutil

import pytest

from app.services.importers.base import ImportRefError
from app.services.importers.local import LocalImportSource
from app.services.media import (
    dead_time,
    intensity_samples,
    make_proxy,
    parse_scene_scores,
    probe,
    scene_scores,
    snap_to_spike,
    timeline_drift,
)

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is only in the Docker image")


def test_parse_scene_scores():
    text = (
        "frame:0    pts:0       pts_time:0\nlavfi.scene_score=0.000000\n"
        "frame:1    pts:512     pts_time:0.0333333\nlavfi.scene_score=0.412000\n"
    )
    times, scores = parse_scene_scores(text)
    assert times == [0.0, 0.0333333]
    assert scores == [0.0, 0.412]


def test_intensity_and_dead_time():
    times = [i / 10 for i in range(60)]  # 6 s at 10 fps
    scores = [0.0 if 2.0 <= t < 4.0 else 0.5 for t in times]
    samples = intensity_samples(times, scores)
    assert len(samples) == 12
    assert samples[0] == (0.0, 1.0)
    assert dead_time(samples) == [(2.0, 4.0)]


def test_snap_moves_only_to_a_clear_spike():
    times = [i / 10 for i in range(100)]
    flat = [0.01] * 100
    spiky = flat.copy()
    spiky[53] = 0.9
    assert snap_to_spike(5.0, times, spiky, floor=0.5) == 5.3
    assert snap_to_spike(5.0, times, flat, floor=0.5) == 5.0  # nothing stands out
    assert snap_to_spike(2.0, times, spiky, floor=0.5) == 2.0  # the spike is out of reach


def test_import_refs_cannot_escape_the_folder(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "fight.mp4").write_bytes(b"x")
    (inbox / "notes.txt").write_text("x")
    (tmp_path / "secret.mp4").write_bytes(b"x")
    source = LocalImportSource(inbox)
    assert source.resolve("fight.mp4") == (inbox / "fight.mp4").resolve()
    for bad in ["../secret.mp4", "notes.txt", "missing.mp4", "."]:
        with pytest.raises(ImportRefError):
            source.resolve(bad)
    items = asyncio.run(source.list())
    assert [i.ref for i in items] == ["fight.mp4"]


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    """Four seconds of 60 fps test pattern with a hard cut at 2 s."""
    path = tmp_path_factory.mktemp("media") / "sample.mkv"
    cmd = [
        "ffmpeg", "-hide_banner", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=1280x1440:r=60:d=2",
        "-f", "lavfi", "-i", "testsrc=s=1280x1440:r=60:d=2",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
        "-map", "[v]", "-map", "2:a", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(path),
    ]
    import subprocess

    subprocess.run(cmd, check=True, capture_output=True)
    return path


@needs_ffmpeg
async def test_probe_proxy_and_timeline(sample, tmp_path):
    info = await probe(sample)
    assert (info.width, info.height) == (1280, 1440)
    assert round(info.fps) == 60
    assert abs(info.duration_s - 4.0) < 0.1
    assert not info.is_hdr

    proxy = tmp_path / "proxy.mp4"
    assert await make_proxy(sample, proxy, info) is True
    assert await make_proxy(sample, proxy, info) is False  # idempotent
    proxy_info = await probe(proxy)
    assert proxy_info.height == 720
    assert proxy_info.width == 640
    assert round(proxy_info.fps) == 60
    assert proxy_info.video_codec == "h264"
    drift = timeline_drift(info, proxy_info)
    assert drift["ok"], (drift, info, proxy_info)


@needs_ffmpeg
async def test_scene_scores_find_the_cut(sample, tmp_path):
    cache = tmp_path / "scene_scores.bin"
    times, scores = await scene_scores(sample, cache)
    assert len(times) > 200
    peak_time = times[scores.index(max(scores))]
    assert abs(peak_time - 2.0) < 0.05
    cached_times, cached_scores = await scene_scores(sample, cache)
    assert len(cached_times) == len(times)
    assert abs(cached_scores[scores.index(max(scores))] - max(scores)) < 1e-6
    assert snap_to_spike(2.4, times, scores, floor=0.2) == pytest.approx(peak_time)
