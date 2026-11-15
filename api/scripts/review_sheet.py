"""Phase 0: a review sheet, so the owner confirms events instead of hand-labelling them.

`build` collects every moment that something proposed as an event:

- the saved Gemini runs (every run under eval/results, repeats grouped),
- drops in the player's health bar (from gauge_probe's gauges.json),
- full-screen red flashes (the look of a counter in some games),
- the labels already in the truth file.

Each candidate gets a strip of frames, a short clip and, for health drops, a
before/after crop of the HUD. The owner answers on the page. `apply` turns the
saved answers into the truth file.

    docker compose run --rm api python -m scripts.review_sheet build --hud 420:80:40:590
    docker compose run --rm api python -m scripts.review_sheet apply /data/review/answers.json

Parries and boss attacks are left out: there are too many to tick one by one.
"""

import argparse
import asyncio
import json
import statistics
from pathlib import Path

from ruamel.yaml import YAML

from app.services.timecode import format_clock, parse_time
from app.settings import get_settings

REVIEW_TYPES = ("counter", "hit_taken", "finisher", "phase_change")
ALL_TYPES = ("counter", "parry", "hit_taken", "boss_attack", "phase_change", "finisher")
DERIVED_FACTS = {"hits_taken": "hit_taken", "counter_count": "counter"}

STRIP_FRAMES = 16
STRIP_STEP_S = 0.25
STRIP_LEAD_S = 1.5  # the strip starts this long before the proposed time
CLIP_LEAD_S = 2.0
CLIP_LENGTH_S = 5.0

FLASH_FPS = 10
FLASH_GRID = (32, 18)
FLASH_THRESHOLD = 0.12  # share of the frame that is strongly red


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="collect candidates and write the page with its frame strips and clips")
    build.add_argument("--only", help="a single truth file by name (without .truth.yaml)")
    build.add_argument("--hud", help="width:height:x:y of the HUD corner to show before and after a health drop")
    build.add_argument("--no-media", action="store_true", help="list the candidates without making strips and clips")
    apply = sub.add_parser("apply", help="write the truth files from the answers saved on the page")
    apply.add_argument("answers", help="JSON file: {<name>: {candidates: {<id>: {verdict, type, t}}, added: [{t, type}]}}")
    return p.parse_args()


# ---- candidates -------------------------------------------------------------------


def group_repeats(reports: list[dict], gap_s: float = 2.0) -> list[dict]:
    """Group reports of one event type from several runs into moments.

    A report is {t, label, run}. Two reports belong together when they are within
    `gap_s` of each other. The moment's time is the median of its reports.
    """
    groups: list[list[dict]] = []
    for report in sorted(reports, key=lambda r: r["t"]):
        if groups and report["t"] - groups[-1][-1]["t"] <= gap_s:
            groups[-1].append(report)
        else:
            groups.append([report])
    return [
        {
            "t": round(statistics.median(r["t"] for r in group), 2),
            "label": group[0]["label"],
            "runs": len({r["run"] for r in group}),
        }
        for group in groups
    ]


def red_flashes(red_share: list[float], fps: int = FLASH_FPS, threshold: float = FLASH_THRESHOLD) -> list[float]:
    """Start times of full-screen red flashes. Flashes within 0.8 s of each other count once."""
    found: list[float] = []
    i = 0
    while i < len(red_share):
        if red_share[i] >= threshold:
            found.append(i / fps)
            while i + 1 < len(red_share) and red_share[i + 1] >= threshold * 0.6:
                i += 1
            i += int(0.8 * fps)
        i += 1
    return found


def red_share(frame: bytes) -> float:
    """Share of a small RGB frame that is strongly red."""
    pixels = len(frame) // 3
    red = sum(
        1
        for i in range(0, pixels * 3, 3)
        if frame[i] > 110 and frame[i] - max(frame[i + 1], frame[i + 2]) > 50
    )
    return red / pixels if pixels else 0.0


def nearest(candidates: list[dict], kind: str, t: float, before_s: float, after_s: float) -> dict | None:
    """The `kind` candidate closest to `t`, if one lies between t - before_s and t + after_s."""
    close = [c for c in candidates if c["type"] == kind and t - before_s <= c["t"] <= t + after_s]
    return min(close, key=lambda c: abs(c["t"] - t)) if close else None


def collect(
    runs: list[list[dict]], drops: list[dict], flashes: list[float], labels: list[dict]
) -> list[dict]:
    """Merge every source into one list of candidates, in video order.

    `runs` are the event lists of the saved analyses, `drops` the health-bar drops
    ({t, t_end, from, to}), `flashes` red-flash times, `labels` the truth file's
    timed events ({t, type}).
    """
    found: list[dict] = []

    # Health drops are measured, so they come first and keep their own time.
    for drop in drops:
        found.append({
            "t": drop["t"], "type": "hit_taken", "label": "",
            "sources": [f"The health bar fell from {drop['from']:.0%} to {drop['to']:.0%}."],
            "drop": {"t": drop["t"], "t_end": drop.get("t_end", drop["t"])},
        })

    for kind in REVIEW_TYPES:
        reports = [
            {"t": e["t_start"], "label": e.get("label", ""), "run": n}
            for n, events in enumerate(runs)
            for e in events
            if e["type"] == kind
        ]
        for moment in group_repeats(reports):
            said = f"Gemini reported it in {moment['runs']} of {len(runs)} runs."
            match = nearest(found, kind, moment["t"], 3.0, 3.0) if kind == "hit_taken" else None
            if match and "drop" in match:
                match["sources"].append(said)
                match["label"] = match["label"] or moment["label"]
            else:
                found.append({"t": moment["t"], "type": kind, "label": moment["label"], "sources": [said]})

    # A counter's flash comes a second or two after the exchange Gemini timed.
    for flash in flashes:
        if any("drop" in c and abs(c["t"] - flash) <= 1.0 for c in found):
            continue  # the red flash of taking damage
        seen = f"The screen flashed red at {format_clock(flash)}."
        match = nearest(found, "counter", flash, 3.5, 1.0)
        if match:
            if not any("flashed red" in s for s in match["sources"]):
                match["sources"].append(seen)
        else:
            found.append({
                "t": flash, "type": "counter", "label": "",
                "sources": [seen, "No run reported a counter here."],
            })

    for label in labels:
        yours = f"You labelled this at {format_clock(label['t'])}."
        match = nearest(found, label["type"], label["t"], 3.0, 3.0)
        if match:
            match["sources"].append(yours)
        else:
            found.append({"t": label["t"], "type": label["type"], "label": "", "sources": [yours]})

    found.sort(key=lambda c: (c["t"], c["type"]))
    for c in found:
        c["t"] = round(c["t"], 2)
        # The id is the type and the time in tenths of a second, so it survives a rebuild.
        c["id"] = f"{c['type']}-{round(c['t'] * 10):05d}"
        c["strip_start"] = round(max(0.0, c["t"] - STRIP_LEAD_S), 2)
    return found


# ---- answers to truth -------------------------------------------------------------


def events_from_answers(answers: dict) -> list[dict]:
    """The confirmed events ({t, type}) in video order: every `yes` plus the ones the owner added."""
    confirmed = [
        {"t": float(a["t"]), "type": a["type"]}
        for a in (answers.get("candidates") or {}).values()
        if a.get("verdict") == "yes"
    ]
    confirmed += [{"t": parse_time(a["t"]), "type": a["type"]} for a in answers.get("added") or []]
    return sorted(confirmed, key=lambda e: (e["t"], e["type"]))


def reviewed_truth(old: dict, answers: dict) -> dict:
    """The truth file's content after a review.

    Reviewed types are replaced by what the owner confirmed. A reviewed type with no
    confirmed event gets a count of 0, so it is still scored. Other types are kept.

    A candidate the owner re-typed to a type outside the review (say a "counter" that
    was really a parry) goes to `unscored`: one stray parry label would otherwise turn
    parry into a scored type with a single true event.
    """
    confirmed = events_from_answers(answers)
    kept = [
        {"t": parse_time(e["t"]), "type": e["type"]}
        for e in old.get("events") or []
        if e["type"] not in REVIEW_TYPES
    ]
    events = sorted(kept + [e for e in confirmed if e["type"] in REVIEW_TYPES], key=lambda e: (e["t"], e["type"]))
    timed = {e["type"] for e in events}
    counts = {k: v for k, v in (old.get("counts") or {}).items() if k not in REVIEW_TYPES}
    counts |= {kind: 0 for kind in REVIEW_TYPES if kind not in timed}
    facts = dict(old.get("facts") or {})
    for key, kind in DERIVED_FACTS.items():
        if key in facts:
            facts[key] = sum(e["type"] == kind for e in events)
    unscored = [e for e in confirmed if e["type"] not in REVIEW_TYPES]
    return {**old, "events": events, "counts": counts, "facts": facts, "unscored": unscored}


def render_truth(truth: dict) -> str:
    """The truth file as text, in the layout of example.truth.yaml.sample."""

    def quoted(value: object) -> str:
        return json.dumps(str(value), ensure_ascii=False)

    lines = [
        "# Ground truth for one video. Events confirmed on the review sheet (scripts.review_sheet).",
        "",
        f"video: {truth['video']}",
        f"preset: {truth.get('preset', 'general')}",
        f"kind: {truth.get('kind', 'long')}",
        f"topic: {quoted(truth.get('topic', ''))}",
        f"subject: {quoted(truth.get('subject', ''))}",
        f"topic_terms: {quoted(truth.get('topic_terms', ''))}",
        "",
        "# One line per event with the time it starts. Only the types listed here or in `counts` are scored.",
    ]
    if truth["events"]:
        lines.append("events:")
        lines += [f'  - {{t: "{format_clock(e["t"], 2)}", type: {e["type"]}}}' for e in truth["events"]]
    else:
        lines.append("events: []")
    if truth.get("unscored"):
        lines += ["", "# Confirmed on review but not scored, because that type was not reviewed in full:"]
        lines += [f"#   {format_clock(e['t'], 2)} {e['type']}" for e in truth["unscored"]]
    lines += ["", "# Types that were reviewed and never happen, or that only have a hand count."]
    if truth["counts"]:
        lines.append("counts:")
        lines += [f"  {kind}: {n}" for kind, n in truth["counts"].items()]
    else:
        lines.append("counts: {}")
    lines += ["", "# What the facts should come out as."]
    if truth["facts"]:
        lines.append("facts:")
        lines += [f"  {key}: {json.dumps(value)}" for key, value in truth["facts"].items()]
    else:
        lines.append("facts: {}")
    return "\n".join(lines) + "\n"


# ---- media ------------------------------------------------------------------------


async def ffmpeg(*args: str) -> bytes:
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-v", "error", "-y", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(err.decode(errors="replace")[-400:])
    return out


async def read_red_share(proxy: Path) -> list[float]:
    w, h = FLASH_GRID
    out = await ffmpeg(
        "-i", str(proxy), "-vf", f"fps={FLASH_FPS},scale={w}:{h}:flags=area", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"
    )
    size = w * h * 3
    return [red_share(out[i : i + size]) for i in range(0, len(out) - size + 1, size)]


async def make_media(proxy: Path, folder: Path, candidate: dict, hud: str | None) -> None:
    """Write the strip, the clip and (for a health drop) the HUD crop, unless they exist."""
    strip = folder / f"{candidate['id']}.jpg"
    if not strip.is_file():
        await ffmpeg(
            "-ss", str(candidate["strip_start"]), "-i", str(proxy), "-frames:v", "1",
            "-vf", f"fps={1 / STRIP_STEP_S:g},scale=256:144,tile={STRIP_FRAMES}x1", "-q:v", "4", str(strip),
        )
    clip = folder / f"{candidate['id']}.mp4"
    if not clip.is_file():
        await ffmpeg(
            "-ss", str(max(0.0, candidate["t"] - CLIP_LEAD_S)), "-t", str(CLIP_LENGTH_S), "-i", str(proxy),
            "-vf", "scale=640:360,fps=30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "32",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k", "-ac", "1", "-movflags", "+faststart", str(clip),
        )
    drop = candidate.get("drop")
    if drop and hud:
        crop = folder / f"{candidate['id']}.hud.jpg"
        if not crop.is_file():
            cut = f"crop={hud},scale=iw*2:ih*2"
            await ffmpeg(
                "-ss", str(max(0.0, drop["t"] - 0.5)), "-i", str(proxy),
                "-ss", str(drop["t_end"] + 0.7), "-i", str(proxy),
                "-filter_complex", f"[0:v]{cut}[a];[1:v]{cut}[b];[a][b]vstack", "-frames:v", "1", "-q:v", "3", str(crop),
            )


# ---- commands ---------------------------------------------------------------------


async def build(args: argparse.Namespace) -> int:
    settings = get_settings()
    out_dir = settings.data_dir / "review"
    truth_files = sorted(settings.eval_dir.glob("*.truth.yaml"))
    if args.only:
        truth_files = [f for f in truth_files if f.name == f"{args.only}.truth.yaml"]
    videos = []
    for truth_file in truth_files:
        name = truth_file.name.removesuffix(".truth.yaml")
        work = settings.data_dir / "eval" / name
        proxy = work / "proxy.mp4"
        if not proxy.is_file():
            print(f"{name}: no proxy at {proxy}. Run eval_analysis --dry-run first.")
            continue
        truth = YAML(typ="safe").load(truth_file.read_text(encoding="utf-8"))
        runs = []
        for path in sorted((settings.eval_dir / "results").rglob(f"{name}__*.json")):
            saved = json.loads(path.read_text(encoding="utf-8"))
            if saved.get("status") == "ok":
                runs.append(saved["analysis"]["events"])
        gauges = json.loads((work / "gauges.json").read_text(encoding="utf-8")) if (work / "gauges.json").is_file() else {}
        drops = [e for e in gauges.get("player_health", {}).get("events", []) if e["kind"] == "drop"]
        flashes = red_flashes(await read_red_share(proxy))
        labels = [{"t": parse_time(e["t"]), "type": e["type"]} for e in truth.get("events") or []]
        candidates = collect(runs, drops, flashes, labels)
        by_type = {k: sum(c["type"] == k for c in candidates) for k in REVIEW_TYPES}
        print(
            f"{name}: {len(candidates)} candidates {by_type} from {len(runs)} runs,"
            f" {len(drops)} health drops, {len(flashes)} red flashes, {len(labels)} labels"
        )
        folder = out_dir / "media" / name
        if not args.no_media:
            folder.mkdir(parents=True, exist_ok=True)
            gate = asyncio.Semaphore(4)

            async def one(c: dict, proxy: Path = proxy, folder: Path = folder, gate: asyncio.Semaphore = gate) -> None:
                async with gate:
                    await make_media(proxy, folder, c, args.hud)

            await asyncio.gather(*(one(c) for c in candidates))
        for c in candidates:
            c["hud"] = bool(c.pop("drop", None) and args.hud)
        videos.append({
            "id": name, "title": truth.get("subject") or name, "topic": truth.get("topic", ""),
            "media": f"media/{name}", "candidates": candidates,
        })

    data = {
        "videos": videos, "types": ALL_TYPES,
        "strip": {"frames": STRIP_FRAMES, "step": STRIP_STEP_S}, "clip_lead": CLIP_LEAD_S,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "candidates.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    template = (Path(__file__).parent / "review_sheet.html").read_text(encoding="utf-8")
    page = template.replace("/*REVIEW_DATA*/null", json.dumps(data).replace("</", "<\\/"))
    (out_dir / "index.html").write_text(page, encoding="utf-8")
    print(f"Wrote {out_dir / 'index.html'}")
    return 0


def apply(args: argparse.Namespace) -> int:
    settings = get_settings()
    answers = json.loads(Path(args.answers).read_text(encoding="utf-8"))
    listed = settings.data_dir / "review" / "candidates.json"
    asked = (
        {v["id"]: [c["id"] for c in v["candidates"]] for v in json.loads(listed.read_text(encoding="utf-8"))["videos"]}
        if listed.is_file()
        else {}
    )
    for name, video_answers in answers.items():
        skipped = [c for c in asked.get(name, []) if c not in (video_answers.get("candidates") or {})]
        if skipped:
            print(f"{name}: {len(skipped)} not answered, so left out: {', '.join(skipped)}")
        truth_file = settings.eval_dir / f"{name}.truth.yaml"
        if not truth_file.is_file():
            print(f"{name}: no truth file, skipped")
            continue
        old_text = truth_file.read_text(encoding="utf-8")
        backup = settings.eval_dir / f"{name}.truth.before-review.yaml"
        if not backup.is_file():
            backup.write_text(old_text, encoding="utf-8")
        truth = reviewed_truth(YAML(typ="safe").load(old_text), video_answers)
        truth_file.write_text(render_truth(truth), encoding="utf-8")
        totals = {k: sum(e["type"] == k for e in truth["events"]) for k in sorted({e["type"] for e in truth["events"]})}
        print(f"{name}: wrote {len(truth['events'])} events {totals}; the old labels are in {backup.name}")
    return 0


if __name__ == "__main__":
    cli = parse_args()
    raise SystemExit(asyncio.run(build(cli)) if cli.command == "build" else apply(cli))
