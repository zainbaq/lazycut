"""Phase 0 prototype: read an on-screen gauge (a health bar) straight from the pixels.

The game draws its own state on screen. This measures how full a bar is on every
sampled frame and lists the moments it drops (damage) or rises (healing), with no
model involved. It is a probe to see whether the idea works, not app code yet.

    docker compose run --rm api python -m scripts.gauge_probe pb0-the-sword-fanatic \
        --gauge player_health=170:3:123:627 --gauge boss_health=336:3:472:58

A gauge is `name=width:height:x:y` in proxy pixels: a thin strip along the bar.
"""

import argparse
import asyncio
import json
import statistics

from app.services.timecode import format_clock
from app.settings import get_settings

FPS = 10


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("name", help="truth-file name; the proxy is read from data/eval/<name>/proxy.mp4")
    p.add_argument("--gauge", action="append", required=True, help="name=width:height:x:y in proxy pixels")
    p.add_argument("--min-step", type=float, default=0.03, help="smallest change that counts (default: 3%% of the bar)")
    return p.parse_args()


async def read_strip(proxy: str, w: int, h: int, x: int, y: int) -> list[bytes]:
    """One row of RGB pixels per sampled frame: the strip averaged down to a single line."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-v", "error", "-i", proxy,
        "-vf", f"fps={FPS},crop={w}:{h}:{x}:{y},scale={w}:1:flags=area",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(err.decode(errors="replace")[-400:])
    row = w * 3
    return [out[i : i + row] for i in range(0, len(out) - row + 1, row)]


def fill_fraction(row: bytes) -> float:
    """Share of the bar that is lit, counted from the left until the lit part ends.

    Lit = bright and nearly colourless (the bar is white). Three dark pixels in a
    row end the count, so a speck of glare further right is ignored.
    """
    width = len(row) // 3
    lit, gap = 0, 0
    for i in range(width):
        r, g, b = row[i * 3 : i * 3 + 3]
        if max(r, g, b) > 140 and max(r, g, b) - min(r, g, b) < 60:
            lit, gap = i + 1, 0
        else:
            gap += 1
            if gap >= 3:
                break
    return lit / width


def steps(series: list[float], min_step: float) -> list[dict]:
    """Drops and rises in a smoothed series. Frames where the bar is not on screen are skipped."""
    smooth = [statistics.median(series[max(0, i - 2) : i + 3]) for i in range(len(series))]
    found: list[dict] = []
    level = None
    for i, value in enumerate(smooth):
        if value < 0.02:  # HUD hidden (cutscene) or bar empty: no reading
            continue
        if level is None:
            level = value
            continue
        change = value - level
        if abs(change) >= min_step:
            kind = "drop" if change < 0 else "rise"
            last = found[-1] if found else None
            if last and last["kind"] == kind and i / FPS - last["t_end"] <= 0.6:
                last["t_end"], last["to"] = i / FPS, round(value, 3)  # same event, still moving
            else:
                found.append({
                    "kind": kind, "t": i / FPS, "t_end": i / FPS,
                    "from": round(level, 3), "to": round(value, 3),
                })
            level = value
        elif found and i / FPS - found[-1]["t_end"] > 0.6:
            level = value  # follow slow drift between events
    return drop_flickers(found, min_step)


def drop_flickers(events: list[dict], min_step: float) -> list[dict]:
    """Remove a change that is undone within a second: a glow over the bar, not damage or healing."""
    kept: list[dict] = []
    skip = False
    for current, following in zip(events, [*events[1:], None], strict=True):
        if skip:
            skip = False
            continue
        if (
            following is not None
            and following["kind"] != current["kind"]
            and following["t"] - current["t_end"] <= 1.0
            and abs(following["to"] - current["from"]) < min_step
        ):
            skip = True
            continue
        kept.append(current)
    return kept


async def main() -> int:
    args = parse_args()
    settings = get_settings()
    work = settings.data_dir / "eval" / args.name
    proxy = work / "proxy.mp4"
    if not proxy.is_file():
        print(f"No proxy at {proxy}. Run eval_analysis --dry-run first.")
        return 2
    report = {}
    for spec in args.gauge:
        name, geometry = spec.split("=", 1)
        w, h, x, y = (int(v) for v in geometry.split(":"))
        rows = await read_strip(str(proxy), w, h, x, y)
        series = [fill_fraction(row) for row in rows]
        events = steps(series, args.min_step)
        report[name] = {"fps": FPS, "series": [round(v, 3) for v in series], "events": events}
        drops = [e for e in events if e["kind"] == "drop"]
        rises = [e for e in events if e["kind"] == "rise"]
        print(f"\n{name}: {len(rows)} frames, {len(drops)} drop(s), {len(rises)} rise(s)")
        for e in events:
            print(f"  {format_clock(e['t'])}  {e['kind']:<4}  {e['from']:.0%} -> {e['to']:.0%}")
    (work / "gauges.json").write_text(json.dumps(report), encoding="utf-8")
    print(f"\nWrote {work / 'gauges.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
