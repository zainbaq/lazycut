"""Phase 2 probe: two ways to ask the text model for clips, side by side on the app's own videos.

`anchors`: the model names the first and last event of each clip; code places the edges.
`times`:   the model writes timestamps; code snaps them to the events (the spec's first draft).

Each (video, prompt) pair is run once per mode and checked in code: how many picks were usable,
how far snapping had to move the model's times, whether the first pick holds what the prompt
asked for, the lengths, and what each call cost in tokens.

    python -m scripts.clip_finder_probe --dry            # print one prompt, no model call
    python -m scripts.clip_finder_probe                  # PAID: one Claude call per video, prompt and mode
"""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlmodel import select

from app.db import make_engine, session
from app.models import Video
from app.services import clipfinder as cf
from app.services.llm.anthropic import ClaudeProvider
from app.services.llm.base import LLMError
from app.services.presets import load_presets
from app.services.timecode import parse_time
from app.settings import get_settings

MODES = ("anchors", "times")


def counts(ctx: cf.ClipContext, start: float, end: float) -> dict[str, int]:
    return cf.stats(start, end, ctx.events, ctx.dead)["event_counts"]


def most_in_window(ctx: cf.ClipContext, kind: str, length_s: float) -> int:
    """The most events of one type that any window of this length can hold."""
    times = [e.t_start for e in ctx.events if e.type == kind]
    return max((sum(1 for u in times if t <= u <= t + length_s) for t in times), default=0)


def expectation(ctx: cf.ClipContext, prompt: str, first: cf.Candidate | None, note: str) -> str:
    """What the prompt plainly asks for, checked against the first pick. Rough on purpose."""
    words = prompt.lower()
    have = {e.type for e in ctx.events}
    if first is None:
        missing = ("phase" in words and "phase_change" not in have) or ("finisher" in words and "finisher" not in have)
        return "ok: nothing to find, and it said so" if missing and note else "MISS: no clip"
    inside = counts(ctx, first.t_start, first.t_end)
    length = first.t_end - first.t_start
    if "finisher" in words:
        last = [e for e in ctx.events if e.type == "finisher"]
        if not last:
            return "n/a: no finisher in the timeline"
        ok = inside.get("finisher", 0) > 0 and first.t_end - last[-1].t_end <= 2.0
        return f"{'ok' if ok else 'MISS'}: finisher {'in' if inside.get('finisher') else 'not in'} pick 1, " \
               f"ends {first.t_end - last[-1].t_end:+.1f} s after it"
    if "phase" in words:
        if "phase_change" not in have:
            return f"{'ok' if note else 'MISS'}: no phase change exists; note={'yes' if note else 'no'}"
        return f"{'ok' if inside.get('phase_change') else 'MISS'}: phase change {'in' if inside.get('phase_change') else 'not in'} pick 1"
    if "counter" in words:
        best = most_in_window(ctx, "counter", length)
        got = inside.get("counter", 0)
        return f"{'ok' if got >= best - 1 else 'MISS'}: {got} counters in pick 1; the most any {length:.0f} s holds is {best}"
    if "opening" in words:
        return f"{'ok' if first.t_start <= 15 else 'MISS'}: pick 1 starts at {cf.stamp(first.t_start)}"
    if "ending" in words:
        gap = ctx.duration_s - first.t_end
        return f"{'ok' if gap <= 15 else 'MISS'}: pick 1 ends {gap:.1f} s before the end"
    return "n/a"


async def run(provider: ClaudeProvider, ctx: cf.ClipContext, prompt: str, platform: str, target: float | None,
              mode: str) -> dict:
    text = cf.finder_prompt(ctx, prompt, platform, target, mode)
    try:
        result = await provider.generate_json(text, cf.FinderOut if mode == "anchors" else cf.TimedOut, effort="low")
    except LLMError as exc:
        return {"mode": mode, "error": str(exc)}
    picks = result.parsed.clips
    resolved, shifts = [], []
    for pick in picks:
        if mode == "anchors":
            resolved.append(cf.resolve_anchor(pick, ctx))
            continue
        cand = cf.resolve_timed(pick, ctx)
        resolved.append(cand)
        if cand is not None:
            # How far snapping moved what the model wrote: its own aim, measured.
            shifts.append((round(cand.t_start - parse_time(pick.t_start), 2), round(cand.t_end - parse_time(pick.t_end), 2)))
    final = cf.finalise(list(resolved), ctx, platform)
    return {
        "mode": mode, "raw": len(picks), "unusable": sum(c is None for c in resolved), "kept": len(final),
        "repeats_dropped": sum(c is not None for c in resolved) - len(final),
        "snap_shifts": shifts,
        "clips": [{"name": c.name, "t_start": c.t_start, "t_end": c.t_end, "length": round(c.t_end - c.t_start, 1),
                   "payoff_t": c.payoff_t, "events": counts(ctx, c.t_start, c.t_end),
                   "dead_s": cf.stats(c.t_start, c.t_end, ctx.events, ctx.dead)["dead_time_s"],
                   "note": (cf.analysis_note(c.t_start, c.t_end, c.payoff_t, platform, ctx.events, ctx.dead, ctx.preset)
                            or {}).get("id"),
                   "reason": c.reason} for c in final],
        "model_note": result.parsed.note,
        "check": expectation(ctx, prompt, final[0] if final else None, result.parsed.note),
        "tokens_in": result.usage.get("input_tokens"), "tokens_out": result.usage.get("output_tokens"),
        "latency_s": result.latency_s, "model": result.model,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry", action="store_true", help="print one prompt per mode and stop (no model call)")
    parser.add_argument("--platform", default="reels")
    parser.add_argument("--target", type=float, default=None, help="target length in seconds (default: none)")
    parser.add_argument("--out", default="", help="where to save the results as JSON (default: /eval/results/...)")
    args = parser.parse_args()

    settings = get_settings()
    presets, _ = load_presets(settings.config_dir)
    engine = make_engine(settings.db_path)
    jobs = []
    with session(engine) as s:
        for video in s.exec(select(Video).where(Video.status == "ready")).all():
            preset = presets.get(video.preset_id) or presets["general"]
            ctx = cf.load_context(s, video, preset, full=True)
            if ctx.events:
                jobs += [(ctx, prompt) for prompt in preset.saved_prompts]
    if args.dry:
        ctx, prompt = jobs[0]
        for mode in MODES:
            print(f"===== {mode} =====\n{cf.finder_prompt(ctx, prompt, args.platform, args.target, mode)}\n")
        print("Timeline-only fallback:", [(c.name, cf.stamp(c.t_start), cf.stamp(c.t_end)) for c in
                                          cf.timeline_candidates(ctx, args.platform, args.target)])
        print(f"{len(jobs) * len(MODES)} calls would be made.")
        return

    provider = ClaudeProvider(settings.anthropic_api_key, settings.anthropic_model)
    results = []
    for ctx, prompt in jobs:
        row = {"video": ctx.video.title, "preset": ctx.preset.id, "prompt": prompt, "runs": []}
        for mode in MODES:
            run_result = await run(provider, ctx, prompt, args.platform, args.target, mode)
            row["runs"].append(run_result)
            print(f"\n{ctx.video.title[:44]} | {prompt} | {mode}")
            if "error" in run_result:
                print("  ERROR", run_result["error"])
                continue
            print(f"  picks {run_result['raw']} unusable {run_result['unusable']} repeats {run_result['repeats_dropped']}"
                  f" kept {run_result['kept']} | {run_result['tokens_in']} in / {run_result['tokens_out']} out"
                  f" / {run_result['latency_s']} s | {run_result['check']}")
            if run_result["snap_shifts"]:
                print("  snap moved (start, end):", run_result["snap_shifts"])
            for c in run_result["clips"]:
                print(f"   {cf.stamp(c['t_start'])}-{cf.stamp(c['t_end'])} {c['length']:>5} s  {c['name']}  {c['events']}"
                      f"  dead {c['dead_s']}  note {c['note']}")
            if run_result["model_note"]:
                print("  note:", run_result["model_note"])
        results.append(row)

    out = Path(args.out) if args.out else settings.eval_dir / "results" / f"clip_finder_probe_{datetime.now(UTC):%Y%m%d_%H%M}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nSaved {out}")


if __name__ == "__main__":
    asyncio.run(main())
