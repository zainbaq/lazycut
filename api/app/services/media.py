"""ffprobe / ffmpeg work: probing, the playback proxy, scene scores and intensity.

Everything runs as a subprocess through asyncio so the event loop is never blocked,
and no video is ever read into memory.
"""

import asyncio
import json
import re
import uuid
from array import array
from bisect import bisect_left, bisect_right
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

PROXY_HEIGHT = 720
PROXY_MAX_FPS = 60.0
SDR_TRANSFERS = {None, "", "bt709", "smpte170m", "bt470bg", "iec61966-2-1", "unknown", "gamma22", "gamma28"}


class MediaError(Exception):
    pass


@dataclass(frozen=True)
class MediaInfo:
    duration_s: float
    start_time_s: float  # of the video stream; audio priming can start the container earlier
    width: int
    height: int
    fps: float
    video_codec: str
    audio_codec: str | None
    size_bytes: int
    color_transfer: str | None

    @property
    def is_hdr(self) -> bool:
        return self.color_transfer not in SDR_TRANSFERS

    def to_dict(self) -> dict:
        return {**asdict(self), "is_hdr": self.is_hdr}


async def _run(*cmd: str) -> tuple[str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        tail = err.decode("utf-8", "replace").strip().splitlines()[-8:]
        raise MediaError(f"{cmd[0]} failed ({proc.returncode}): " + " | ".join(tail))
    return out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def _ratio(text: str | None) -> float:
    if not text or text in {"0/0", "N/A"}:
        return 0.0
    num, _, den = text.partition("/")
    try:
        return float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return 0.0


async def probe(path: Path) -> MediaInfo:
    out, _ = await _run(
        "ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)
    )
    data = json.loads(out)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise MediaError(f"{path.name} has no video stream")
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = data.get("format", {})
    duration = float(fmt.get("duration") or video.get("duration") or 0)
    if duration <= 0:
        raise MediaError(f"{path.name} has no readable duration")
    return MediaInfo(
        duration_s=duration,
        start_time_s=float(video.get("start_time") or fmt.get("start_time") or 0),
        width=int(video["width"]),
        height=int(video["height"]),
        fps=_ratio(video.get("avg_frame_rate")) or _ratio(video.get("r_frame_rate")),
        video_codec=video.get("codec_name", ""),
        audio_codec=audio.get("codec_name") if audio else None,
        size_bytes=int(fmt.get("size") or path.stat().st_size),
        color_transfer=video.get("color_transfer"),
    )


async def _run_with_progress(cmd: list[str], duration_s: float, on_progress: Callable[[float], None]) -> None:
    """Run ffmpeg with `-progress pipe:1` and report the share of `duration_s` done."""
    proc = await asyncio.create_subprocess_exec(
        cmd[0], "-progress", "pipe:1", "-nostats", *cmd[1:],
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    errors: list[bytes] = []

    async def drain_stderr() -> None:
        assert proc.stderr is not None
        while line := await proc.stderr.readline():
            errors.append(line)
            del errors[:-20]

    drain = asyncio.create_task(drain_stderr())
    assert proc.stdout is not None
    while line := await proc.stdout.readline():
        key, _, value = line.decode("utf-8", "replace").strip().partition("=")
        if key == "out_time_us" and value.isdigit() and duration_s > 0:
            on_progress(min(1.0, int(value) / 1e6 / duration_s))
    await proc.wait()
    await drain
    if proc.returncode != 0:
        tail = b"".join(errors).decode("utf-8", "replace").strip().splitlines()[-8:]
        raise MediaError(f"{cmd[0]} failed ({proc.returncode}): " + " | ".join(tail))


def proxy_fps(source_fps: float) -> float:
    return round(min(source_fps or 30.0, PROXY_MAX_FPS), 3)


async def make_proxy(
    src: Path, dest: Path, info: MediaInfo, on_progress: Callable[[float], None] | None = None
) -> bool:
    """Transcode the 720p playback/analysis proxy. Returns False if it already existed.

    Constant frame rate at the source rate (capped at 60) and a keyframe every
    half second, so seeking is snappy and frame stepping matches the source.
    """
    if dest.is_file() and dest.stat().st_size > 0:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    fps = proxy_fps(info.fps)
    gop = str(max(1, round(fps / 2)))
    partial = dest.with_name(dest.stem + ".part.mp4")
    cmd = [
        "ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src),
        "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", f"scale=-2:'min({PROXY_HEIGHT},ih)'",
        "-fps_mode", "cfr", "-r", f"{fps:g}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-g", gop, "-keyint_min", gop, "-sc_threshold", "0",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(partial),
    ]
    if on_progress is None:
        await _run(*cmd)
    else:
        await _run_with_progress(cmd, info.duration_s, on_progress)
    partial.replace(dest)
    return True


def timeline_drift(source: MediaInfo, proxy: MediaInfo) -> dict:
    """How far the proxy's timeline is from the source's.

    The video must start within one source frame of the original. Container
    durations also include audio padding, which differs between formats by a
    few hundredths of a second, so duration gets a 0.05 s allowance; a wrong
    frame rate would show up as a far larger gap.
    """
    frame = 1.0 / (source.fps or 30.0)
    duration_diff = abs(proxy.duration_s - source.duration_s)
    start_diff = abs(proxy.start_time_s - source.start_time_s)
    return {
        "duration_diff_s": round(duration_diff, 4),
        "start_diff_s": round(start_diff, 4),
        "frame_s": round(frame, 4),
        "ok": duration_diff <= max(2 * frame, 0.05) and start_diff <= frame,
    }


# -- frames ---------------------------------------------------------------------

FILMSTRIP_WIDTH = 320
FILMSTRIP_MAX_FRAMES = 600


def filmstrip_interval(duration_s: float) -> float:
    """One frame per second; longer videos get at most 600 evenly spaced frames."""
    return max(1.0, duration_s / FILMSTRIP_MAX_FRAMES)


async def make_filmstrip(proxy: Path, folder: Path, duration_s: float) -> dict:
    """JPEG frames of the proxy in `folder`, plus an index. Returns the index; reuses a complete one.

    Frame n (from 0) shows the proxy at n * interval_s.
    """
    index_path = folder / "index.json"
    if index_path.is_file():
        return json.loads(index_path.read_text(encoding="utf-8"))
    interval = filmstrip_interval(duration_s)
    partial = folder.with_name(folder.name + ".part")
    if partial.exists():
        for stale in partial.iterdir():
            stale.unlink()
    partial.mkdir(parents=True, exist_ok=True)
    await _run(
        "ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(proxy),
        "-vf", f"fps=1/{interval:.6f}:round=down,scale={FILMSTRIP_WIDTH}:-2",
        "-q:v", "5", "-start_number", "0", str(partial / "%06d.jpg"),
    )
    count = len(list(partial.glob("*.jpg")))
    if count == 0:
        raise MediaError("ffmpeg wrote no filmstrip frames")
    index = {"interval_s": interval, "width": FILMSTRIP_WIDTH, "count": count}
    (partial / "index.json").write_text(json.dumps(index), encoding="utf-8")
    if folder.exists():
        for stale in folder.iterdir():
            stale.unlink()
        folder.rmdir()
    partial.replace(folder)
    return index


async def frame_at(src: Path, t: float, width: int, dest: Path) -> Path:
    """One JPEG of `src` at `t` seconds, `width` px wide. Cached at `dest`."""
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    # A name per call: two requests for the same frame must not share (and steal) one partial file.
    partial = dest.with_name(f"{dest.stem}.{uuid.uuid4().hex[:8]}.part.jpg")
    await _run(
        "ffmpeg", "-hide_banner", "-nostdin", "-y", "-ss", f"{max(0.0, t):.3f}", "-i", str(src),
        "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3", str(partial),
    )
    if not partial.is_file() or partial.stat().st_size == 0:
        raise MediaError(f"no frame at {t:.2f} s")
    partial.replace(dest)
    return dest


# -- clip export (BUILD_SPEC 7.6) -------------------------------------------------

EXPORT_CRF = "16"  # near-lossless (D20)


def vertical_size(text: str) -> tuple[int, int]:
    """`EXPORT_VERTICAL_SIZE` ("1080x1920") as even width and height."""
    try:
        width, height = (int(part) for part in text.lower().split("x"))
    except ValueError as exc:
        raise MediaError(f"EXPORT_VERTICAL_SIZE must look like 1080x1920, not {text!r}") from exc
    if width < 2 or height < 2 or width % 2 or height % 2:
        raise MediaError(f"EXPORT_VERTICAL_SIZE needs even numbers, not {text!r}")
    return width, height


def export_command(src: Path, dest: Path, t_start: float, t_end: float, crop: str, mode: str,
                   vertical: tuple[int, int] = (1080, 1920)) -> list[str]:
    """The ffmpeg call for one export. Always cut from the source, at the source frame rate (D20).

    accurate: re-encoded near-lossless, frame-exact edges. lossless: stream copy, so the cut
    starts on the keyframe at or before `t_start`. 9x16: centre crop scaled to the platforms'
    native size, so they do not rescale it a second time.
    """
    if mode not in ("accurate", "lossless") or crop not in ("none", "9x16"):
        raise MediaError(f"unknown export: mode {mode!r}, crop {crop!r}")
    if mode == "lossless" and crop != "none":
        raise MediaError("A lossless export cannot be cropped: cropping needs a re-encode")
    head = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-ss", f"{max(0.0, t_start):.3f}", "-to", f"{t_end:.3f}",
            "-i", str(src), "-map", "0:v:0", "-map", "0:a:0?"]
    if mode == "lossless":
        return [*head, "-c", "copy", "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", str(dest)]
    filters = []
    if crop == "9x16":
        width, height = vertical
        filters = ["-vf", f"crop=trunc(ih*9/16/2)*2:ih,scale={width}:{height}:flags=lanczos,setsar=1"]
    return [*head, *filters, "-c:v", "libx264", "-crf", EXPORT_CRF, "-preset", "slow", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", str(dest)]


async def keyframe_at_or_before(src: Path, t: float, reach_s: float = 30.0) -> float | None:
    """The time of the last keyframe at or before `t`: where a stream copy really starts."""
    lo = max(0.0, t - reach_s)
    out, _ = await _run(
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-skip_frame", "nokey",
        "-show_entries", "frame=pts_time", "-of", "csv=p=0", "-read_intervals", f"{lo:.3f}%{t + 0.5:.3f}", str(src),
    )
    times = []
    for line in out.split():
        try:
            times.append(float(line.strip().strip(",")))
        except ValueError:
            continue
    before = [k for k in times if k <= t + 1e-3]
    return max(before) if before else None


async def export_clip(src: Path, dest: Path, t_start: float, t_end: float, crop: str = "none",
                      mode: str = "accurate", vertical: tuple[int, int] = (1080, 1920),
                      on_progress: Callable[[float], None] | None = None) -> dict:
    """Cut one continuous range to `dest`. Returns what the file really holds:
    `{width, height, fps, duration_s, size_bytes, real_start, real_end}`."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(f"{dest.stem}.{uuid.uuid4().hex[:8]}.part.mp4")
    cmd = export_command(src, partial, t_start, t_end, crop, mode, vertical)
    try:
        if on_progress is None:
            await _run(*cmd)
        else:
            await _run_with_progress(cmd, max(t_end - t_start, 0.1), on_progress)
        info = await probe(partial)
        partial.replace(dest)
    finally:
        partial.unlink(missing_ok=True)
    real_start = t_start
    if mode == "lossless":
        key = await keyframe_at_or_before(src, t_start)
        real_start = key if key is not None else t_start
    return {
        "width": info.width, "height": info.height, "fps": round(info.fps, 3), "duration_s": round(info.duration_s, 3),
        "size_bytes": dest.stat().st_size, "real_start": round(real_start, 3),
        "real_end": round(real_start + info.duration_s, 3) if mode == "lossless" else round(t_end, 3),
    }


async def cut_excerpt(src: Path, dest: Path, t_start: float, t_end: float, height: int = 720) -> Path:
    """A short, small, silent cut of the source for the refine pass (7.3): frame-exact, at the
    source frame rate, at most `height` px tall."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    await _run(
        "ffmpeg", "-hide_banner", "-nostdin", "-y", "-ss", f"{max(0.0, t_start):.3f}", "-to", f"{t_end:.3f}",
        "-i", str(src), "-map", "0:v:0", "-vf", f"scale=-2:'min({height},ih)'",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-an",
        "-movflags", "+faststart", str(dest),
    )
    return dest


# -- scene scores ---------------------------------------------------------------

_PTS = re.compile(r"pts_time:([0-9.]+)")
_SCORE = re.compile(r"lavfi\.scene_score=([0-9.]+)")


def parse_scene_scores(text: str) -> tuple[list[float], list[float]]:
    times: list[float] = []
    scores: list[float] = []
    current: float | None = None
    for line in text.splitlines():
        if m := _PTS.search(line):
            current = float(m.group(1))
        elif (m := _SCORE.search(line)) and current is not None:
            times.append(current)
            scores.append(float(m.group(1)))
            current = None
    return times, scores


async def scene_scores(path: Path, cache: Path | None = None) -> tuple[list[float], list[float]]:
    """Per-frame scene-change scores (0-1) with their timestamps. Cached as float32 pairs."""
    if cache is not None and cache.is_file() and cache.stat().st_size > 0:
        raw = array("f")
        raw.frombytes(cache.read_bytes())
        return list(raw[0::2]), list(raw[1::2])
    out, _ = await _run(
        "ffmpeg", "-hide_banner", "-nostdin", "-nostats", "-i", str(path),
        "-vf", "scale=320:-2,select='gte(scene,0)',metadata=print:file=-",
        "-an", "-f", "null", "-",
    )
    times, scores = parse_scene_scores(out)
    if not times:
        raise MediaError("ffmpeg returned no scene scores")
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        raw = array("f")
        for t, s in zip(times, scores, strict=True):
            raw.extend((t, s))
        cache.write_bytes(raw.tobytes())
    return times, scores


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return ordered[index]


def intensity_samples(times: list[float], scores: list[float], bucket_s: float = 0.5) -> list[tuple[float, float]]:
    """Mean score per bucket, normalised 0-1 against the 95th percentile."""
    if not times:
        return []
    buckets: dict[int, list[float]] = {}
    for t, s in zip(times, scores, strict=True):
        buckets.setdefault(int(t // bucket_s), []).append(s)
    means = {i: sum(v) / len(v) for i, v in buckets.items()}
    top = percentile(list(means.values()), 95) or 1.0
    last = max(means)
    return [(i * bucket_s, min(1.0, means.get(i, 0.0) / top)) for i in range(last + 1)]


def dead_time(
    samples: list[tuple[float, float]], threshold: float = 0.08, min_len_s: float = 1.0, bucket_s: float = 0.5
) -> list[tuple[float, float]]:
    """Runs of at least `min_len_s` where intensity stays below the threshold."""
    runs: list[tuple[float, float]] = []
    start: float | None = None
    for t, score in samples:
        if score < threshold:
            start = t if start is None else start
        elif start is not None:
            if t - start >= min_len_s:
                runs.append((start, t))
            start = None
    if start is not None and samples:
        end = samples[-1][0] + bucket_s
        if end - start >= min_len_s:
            runs.append((start, end))
    return runs


def snap_to_spike(
    t: float, times: list[float], scores: list[float], floor: float, window_s: float = 0.75
) -> float:
    """Move a timestamp to the largest scene-score spike nearby, if one stands out.

    A spike stands out when it is at least `floor` (a video-wide high percentile)
    and at least twice the median of its window. Otherwise the time is unchanged.
    """
    lo = bisect_left(times, t - window_s)
    hi = bisect_right(times, t + window_s)
    if hi - lo < 3:
        return t
    window = scores[lo:hi]
    peak = max(window)
    if peak < floor or peak < 2 * percentile(window, 50):
        return t
    return times[lo + window.index(peak)]
