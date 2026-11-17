"""Phase 2 probe: does the refine pass (BUILD_SPEC 7.3) move a rough event time closer to the truth?

For a video in the app that has reviewed labels in `eval/`, each stored model event of one type
that sits within 1.5 s of a confirmed time is refined, and the error before and after is printed.

    python -m scripts.refine_probe --truth pb0-the-gate-keeper --type counter --limit 5      # PAID: one small Gemini call each
"""

import argparse
import asyncio
import tempfile
from pathlib import Path

from ruamel.yaml import YAML
from sqlmodel import col, select

from app.db import make_engine, session
from app.models import Event, Video
from app.services.events.refine import REFINE_FPS, WINDOW_S, refine_moment
from app.services.llm.gemini import GeminiProvider
from app.services.playbook import load_playbook
from app.services.presets import load_presets
from app.services.timecode import parse_time
from app.settings import get_settings


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--truth", required=True, help="name of the truth file in eval/, without .truth.yaml")
    parser.add_argument("--type", default="counter")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--fps", type=float, default=REFINE_FPS)
    parser.add_argument("--window", type=float, default=WINDOW_S)
    args = parser.parse_args()

    settings = get_settings()
    truth = YAML(typ="safe").load((settings.eval_dir / f"{args.truth}.truth.yaml").read_text(encoding="utf-8"))
    times = sorted(parse_time(e["t"]) for e in truth["events"] if e["type"] == args.type)
    presets, _ = load_presets(settings.config_dir)
    with session(make_engine(settings.db_path)) as s:
        video = s.exec(select(Video).where(Video.import_ref == truth["video"])).first()
        if video is None:
            raise SystemExit(f"{truth['video']} is not imported in the app")
        events = s.exec(select(Event).where(Event.video_id == video.id, Event.type == args.type, Event.source == "model")
                        .order_by(col(Event.t_start))).all()
    preset = presets[truth.get("preset") or video.preset_id]
    definition = next(t.definition for t in preset.event_types if t.id == args.type)
    playbook = load_playbook(settings.playbook_dir, video.topic)
    looks = next((e.looks_like for e in (playbook.entries if playbook else []) if e.event_type == args.type), "")
    cue = f"{definition} {looks}".strip()
    print(f"cue: {cue}\n")

    provider = GeminiProvider(settings.gemini_api_key, settings.gemini_video_model, max_attempts=2, request_timeout_s=300)
    before, after, done = [], [], 0
    with tempfile.TemporaryDirectory() as tmp:
        for event in events:
            near = min(times, key=lambda t: abs(t - event.t_model_start))
            if abs(near - event.t_model_start) > 1.5 or done >= args.limit:
                continue
            done += 1
            got = await refine_moment(provider, Path(video.source_path), event.t_model_start, cue, video.duration_s,
                                      Path(tmp), args.window, args.fps)
            usage = got.result.usage
            err0 = event.t_model_start - near
            err1 = (got.t - near) if got.t is not None else None
            before.append(abs(err0))
            if err1 is not None:
                after.append(abs(err1))
            print(f"truth {near:7.2f} | full pass {event.t_model_start:7.2f} ({err0:+.2f}) | refined "
                  f"{got.t if got.t is not None else 'not found'} ({'' if err1 is None else f'{err1:+.2f}'}) "
                  f"{got.confidence} | {usage.get('total_input_tokens')} in / {usage.get('total_output_tokens')} out "
                  f"/ {got.result.latency_s:.0f} s | {got.seen}")
    if before:
        print(f"\nmean error: full pass {sum(before) / len(before):.2f} s over {len(before)}; "
              f"refined {sum(after) / len(after) if after else float('nan'):.2f} s over {len(after)} found")


if __name__ == "__main__":
    asyncio.run(main())
