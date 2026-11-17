import asyncio
import shutil
from pathlib import Path

import pytest

from app.services.importers.base import ImportRefError
from app.services.importers.local import LocalImportSource
from app.services.media import (
    MediaError,
    dead_time,
    export_clip,
    export_command,
    intensity_samples,
    keyframe_at_or_before,
    make_proxy,
    parse_scene_scores,
    probe,
    scene_scores,
    snap_to_spike,
    timeline_drift,
    vertical_size,
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


# ---- clip export (BUILD_SPEC 7.6) ---------------------------------------------------


def test_export_commands_and_the_vertical_size():
    assert vertical_size("1080x1920") == (1080, 1920) and vertical_size(" 720X1280 ") == (720, 1280)
    for bad in ("1080", "1080x", "1081x1920", "axb"):
        with pytest.raises(MediaError):
            vertical_size(bad)
    src, dest = Path("in.mp4"), Path("out.mp4")
    accurate = export_command(src, dest, 13.5, 41.0, "none", "accurate")
    assert accurate[accurate.index("-ss") + 1] == "13.500" and accurate[accurate.index("-to") + 1] == "41.000"
    assert accurate.index("-ss") < accurate.index("-i")            # seek on the input: fast and frame-exact
    assert "-vf" not in accurate and "-r" not in accurate          # source size and frame rate kept
    assert accurate[accurate.index("-crf") + 1] == "16" and accurate[accurate.index("-preset") + 1] == "slow"
    vertical = export_command(src, dest, 0, 5, "9x16", "accurate", (1080, 1920))
    assert vertical[vertical.index("-vf") + 1] == "crop=trunc(ih*9/16/2)*2:ih,scale=1080:1920:flags=lanczos,setsar=1"
    lossless = export_command(src, dest, 0, 5, "none", "lossless")
    assert lossless[lossless.index("-c") + 1] == "copy" and "libx264" not in lossless
    with pytest.raises(MediaError):
        export_command(src, dest, 0, 5, "9x16", "lossless")       # a crop needs a re-encode
    with pytest.raises(MediaError):
        export_command(src, dest, 0, 5, "square", "accurate")


@needs_ffmpeg
async def test_accurate_export_is_frame_exact_and_keeps_size_and_rate(sample, tmp_path):
    seen: list[float] = []
    out = tmp_path / "clips" / "cut.mp4"
    made = await export_clip(sample, out, 1.0, 3.0, on_progress=seen.append)
    assert (made["width"], made["height"], round(made["fps"])) == (1280, 1440, 60)
    assert (made["real_start"], made["real_end"]) == (1.0, 3.0) and made["size_bytes"] == out.stat().st_size
    assert seen and seen[-1] == pytest.approx(1.0, abs=0.05)
    assert not list(out.parent.glob("*.part.mp4"))
    times, scores = await scene_scores(out)
    assert abs(len(times) - 120) <= 1                               # 2 s at 60 fps, within one frame
    # The source cuts from black to the test pattern at 2.0 s, so the clip must cut at 1.0 s.
    assert abs(times[scores.index(max(scores))] - 1.0) <= 1 / 60 + 1e-3


@needs_ffmpeg
async def test_vertical_export_is_cropped_and_scaled_to_the_platform_size(sample, tmp_path):
    made = await export_clip(sample, tmp_path / "v.mp4", 0.5, 1.5, crop="9x16", vertical=(1080, 1920))
    assert (made["width"], made["height"], round(made["fps"])) == (1080, 1920, 60)
    assert abs(made["duration_s"] - 1.0) < 0.1
    small = await export_clip(sample, tmp_path / "s.mp4", 0.5, 1.5, crop="9x16", vertical=(720, 1280))
    assert (small["width"], small["height"]) == (720, 1280)


@needs_ffmpeg
async def test_lossless_export_starts_on_a_keyframe_and_says_so(sample, tmp_path):
    # The sample has one keyframe, at 0 s, so a copy asked to start at 1.0 s really starts at 0.
    assert await keyframe_at_or_before(sample, 1.0) == pytest.approx(0.0, abs=0.02)
    made = await export_clip(sample, tmp_path / "copy.mp4", 1.0, 3.0, mode="lossless")
    assert (made["width"], made["height"]) == (1280, 1440)
    assert made["real_start"] == pytest.approx(0.0, abs=0.02) and made["real_end"] == pytest.approx(3.0, abs=0.1)
    assert made["duration_s"] == pytest.approx(3.0, abs=0.1)
