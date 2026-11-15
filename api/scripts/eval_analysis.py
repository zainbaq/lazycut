"""Phase 0: measure how well the analysis reads real footage.

For every `eval/*.truth.yaml` this makes the proxy, runs the analysis across a
grid of sampling rates and media resolutions, scores each run against the hand
labels, and writes `eval/results/summary.md`.

    docker compose run --rm api python -m scripts.eval_analysis --dry-run
    docker compose run --rm api python -m scripts.eval_analysis --fps 1,2,5 --resolution default,high
"""

import argparse
import asyncio
import json
import sys
import time

from app.services.analysis import (
    VideoContext,
    estimate_input_tokens,
    run_analysis,
    snap_event_times,
)
from app.services.evaluation import Truth, load_truth, score_events, score_facts
from app.services.importers.base import ImportRefError
from app.services.importers.local import LocalImportSource
from app.services.llm.base import LLMError, LLMParseError
from app.services.llm.gemini import GeminiProvider
from app.services.media import MediaError, make_proxy, probe, scene_scores, timeline_drift
from app.services.playbook import load_playbook
from app.services.presets import load_presets
from app.services.timecode import format_clock
from app.settings import get_settings


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", help="run a single truth file by name (without .truth.yaml)")
    p.add_argument("--fps", default="1,2,5", help="comma-separated sampling rates (default: 1,2,5)")
    p.add_argument("--resolution", default="default", help="comma-separated: default, low, medium, high")
    p.add_argument("--processing", default="static", help="comma-separated: static, agentic")
    p.add_argument("--time-format", default="clock", help="comma-separated: clock, seconds")
    p.add_argument("--playbook", default="off", help="comma-separated: off, on (uses config/playbooks/<topic>.yaml)")
    p.add_argument("--tolerance", type=float, default=0.5, help="match window in seconds (default: 0.5)")
    p.add_argument("--dry-run", action="store_true", help="make proxies and estimates; do not call Gemini")
    p.add_argument("--force", action="store_true", help="re-run configurations that already have a result")
    p.add_argument(
        "--background", action="store_true",
        help="start each Gemini call in the background and poll for the answer instead of holding a connection open",
    )
    p.add_argument("--retry-errors", action="store_true", help="re-run configurations whose saved result is an error")
    p.add_argument("--report-only", action="store_true", help="rebuild summary.md from saved results; no Gemini calls")
    return p.parse_args()


def grid(args: argparse.Namespace) -> list[dict]:
    configs = []
    for processing in args.processing.split(","):
        # A sampling rate only applies in static mode.
        rates = [float(x) for x in args.fps.split(",")] if processing == "static" else [None]
        for fps in rates:
            for resolution in args.resolution.split(","):
                for time_format in args.time_format.split(","):
                    for playbook in getattr(args, "playbook", "off").split(","):
                        configs.append({
                            "fps": fps,
                            "resolution": None if resolution == "default" else resolution,
                            "processing": processing,
                            "time_format": time_format,
                            "playbook": playbook == "on",
                        })
    return configs


def config_label(cfg: dict) -> str:
    rate = f"fps{cfg['fps']:g}" if cfg["fps"] is not None else "auto"
    label = f"{cfg['processing']}__{rate}__{cfg['resolution'] or 'default'}__{cfg['time_format']}"
    return f"{label}__playbook" if cfg.get("playbook") else label


def score(truth: Truth, analysis: dict, tolerance: float, snap: tuple[list[float], list[float]]) -> dict:
    events = [(e["t_start"], e["type"]) for e in analysis["events"]]
    snapped_times = snap_event_times([t for t, _ in events], *snap)
    snapped = [(t, kind) for t, (_, kind) in zip(snapped_times, events, strict=True)]
    proposals = {p["key"]: p["value"] for p in analysis["fact_proposals"]}
    return {
        "events": score_events(truth, events, tolerance),
        "events_wide": score_events(truth, events, 1.0)["overall"],
        "events_loose": score_events(truth, events, 3.0)["overall"],
        "events_snapped": score_events(truth, snapped, tolerance)["overall"],
        "moved_by_snap": sum(1 for a, b in zip(snapped_times, [t for t, _ in events], strict=True) if a != b),
        "facts": score_facts(truth, proposals),
    }


def fmt(value: object, suffix: str = "") -> str:
    return "–" if value is None else f"{value}{suffix}"


def summary_row(name: str, cfg: dict, record: dict) -> str:
    mode = f"{cfg['processing']} + playbook" if cfg.get("playbook") else cfg["processing"]
    base = f"| {name} | {mode} | {fmt(cfg['fps'])} | {cfg['resolution'] or 'default'} | {cfg['time_format']} |"
    if record.get("status") != "ok":
        note = record.get("error") or f"estimate {record.get('estimated_input_tokens', '?')} tokens"
        return f"{base} {record.get('status')} | | | | | | | | | | {note[:120]} |"
    s = record["score"]
    o, w, sn, f = s["events"]["overall"], s["events_wide"], s["events_snapped"], s["facts"]
    loose = s.get("events_loose", {})
    counts = ", ".join(f"{k} {v['found']}/{v['true']}" for k, v in s["events"]["per_type"].items())
    usage = record.get("usage", {})
    return (
        f"{base} ok | {counts} | {fmt(o.get('recall'))} | {fmt(o.get('precision'))} | {fmt(o.get('mean_error_s'), ' s')} |"
        f" {fmt(w.get('recall'))} | {fmt(loose.get('recall'))} |"
        f" {fmt(sn.get('recall'))} / {fmt(sn.get('mean_error_s'), ' s')} |"
        f" {f['correct']}/{f['total']} | {fmt(usage.get('total_input_tokens'))} / {fmt(usage.get('total_output_tokens'))} |"
        f" {record.get('latency_s', 0):.0f} s |"
    )


SUMMARY_HEAD = (
    "| Video | Mode | fps | Resolution | Times | Status | Found/true by type | Recall | Precision | Mean error |"
    " Recall ±1 s | Recall ±3 s | Snapped recall / error | Facts | Tokens in / out | Time |\n"
    "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"
)


def short_label(cfg: dict) -> str:
    rate = f"{cfg['fps']:g} fps" if cfg["fps"] is not None else "agentic"
    extras = [
        x for x in (
            cfg["resolution"],
            "seconds" if cfg["time_format"] == "seconds" else None,
            "+ playbook" if cfg.get("playbook") else None,
        ) if x
    ]
    return " ".join([rate, *extras])


def detail_table(truth: Truth, runs: list[tuple[dict, dict]]) -> str:
    """Label by label: where each run put the nearest event of the same type, and what it added.

    A cell shows the gap from your label to the run's nearest same-type event
    (`+1.0 s` = Gemini is one second late). `missed` = nothing of that type
    within 10 s. A second line names a different event type seen within 2 s,
    which usually means Gemini saw the moment but classified it differently.
    """
    ok_runs = [(cfg, rec) for cfg, rec in runs if rec.get("status") == "ok"]
    if not ok_runs:
        return "No completed runs."
    head = "| Your label | " + " | ".join(short_label(cfg) for cfg, _ in ok_runs) + " |"
    lines = [head, "| --- |" + " --- |" * len(ok_runs)]
    for label in sorted(truth.events, key=lambda e: e.t):
        cells = []
        for _, rec in ok_runs:
            events = rec["analysis"]["events"]
            same = [e for e in events if e["type"] == label.type]
            near = min(same, key=lambda e: abs(e["t_start"] - label.t), default=None)
            if near is None or abs(near["t_start"] - label.t) > 10:
                cell = "missed"
            else:
                cell = f"{near['t_start'] - label.t:+.1f} s"
            other = min(
                (e for e in events if e["type"] != label.type and abs(e["t_start"] - label.t) <= 2),
                key=lambda e: abs(e["t_start"] - label.t), default=None,
            )
            if other is not None:
                cell += f"<br>({other['type']} {other['t_start'] - label.t:+.1f} s)"
            cells.append(cell)
        lines.append(f"| {format_clock(label.t)} {label.type} | " + " | ".join(cells) + " |")

    scored = set(truth.true_counts())
    lines += ["", "Events Gemini reported that are more than 3 s from any label of the same type:", ""]
    for cfg, rec in ok_runs:
        extras = [
            f"{e['type']} {format_clock(e['t_start'])} ({e['label']})"
            for e in rec["analysis"]["events"]
            if e["type"] in scored
            and all(abs(e["t_start"] - t.t) > 3 for t in truth.events if t.type == e["type"])
        ]
        lines.append(f"- **{short_label(cfg)}**: " + ("; ".join(extras) if extras else "none"))
    return "\n".join(lines)


async def main() -> int:
    args = parse_args()
    settings = get_settings()
    presets, preset_errors = load_presets(settings.config_dir)
    for err in preset_errors:
        print(f"config error: {err.file}: {err.problem}", file=sys.stderr)

    truth_files = sorted(settings.eval_dir.glob("*.truth.yaml"))
    if args.only:
        truth_files = [f for f in truth_files if f.name == f"{args.only}.truth.yaml"]
    if not truth_files:
        print(f"No truth files in {settings.eval_dir}. Copy example.truth.yaml.sample to <name>.truth.yaml and fill it in.")
        return 2

    provider = None
    if not args.dry_run and not args.report_only:
        try:
            provider = GeminiProvider(
                settings.gemini_api_key, settings.gemini_video_model,
                request_timeout_s=1800 if args.background else 720, background=args.background,
                max_attempts=2,  # every attempt is a billed or rationed request
                on_status=lambda msg: print(f"    · {msg}", flush=True),
            )
        except LLMError as exc:
            print(f"Cannot call Gemini: {exc}. Use --dry-run to check everything else.", file=sys.stderr)
            return 2

    inbox = LocalImportSource(settings.inbox_dir)
    results_dir = settings.eval_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    rows: list[str] = []
    notes: list[str] = []
    details: list[str] = []

    for truth_file in truth_files:
        name = truth_file.name.removesuffix(".truth.yaml")
        print(f"\n== {name}")
        try:
            truth = load_truth(truth_file)
            preset = presets[truth.preset]
            source = inbox.resolve(truth.video)
            info = await probe(source)
        except (ImportRefError, MediaError, KeyError, ValueError) as exc:
            print(f"  skipped: {exc}", file=sys.stderr)
            notes.append(f"- **{name}** skipped: {exc}")
            continue

        work = settings.data_dir / "eval" / name
        proxy = work / "proxy.mp4"
        started = time.monotonic()
        made = await make_proxy(source, proxy, info)
        proxy_info = await probe(proxy)
        drift = timeline_drift(info, proxy_info)
        scores = await scene_scores(proxy, work / "scene_scores.bin")
        print(
            f"  source {info.width}x{info.height} {info.fps:g} fps {info.duration_s:.1f} s {info.size_bytes / 1e6:.0f} MB"
            f"{' HDR' if info.is_hdr else ''} | proxy {proxy_info.size_bytes / 1e6:.0f} MB"
            f" ({'made' if made else 'reused'}, {time.monotonic() - started:.0f} s) | timeline {'ok' if drift['ok'] else 'DRIFT'} {drift}"
        )
        notes.append(
            f"- **{name}**: {info.width}×{info.height}, {info.fps:g} fps, {info.duration_s:.1f} s,"
            f" source {info.size_bytes / 1e6:.0f} MB, proxy {proxy_info.size_bytes / 1e6:.0f} MB,"
            f" proxy timeline {'matches' if drift['ok'] else 'DRIFTS: ' + json.dumps(drift)}"
            f"{', HDR source' if info.is_hdr else ''}"
        )
        video = VideoContext(truth.kind, info.duration_s, truth.topic, truth.subject, truth.topic_terms)
        playbook = load_playbook(settings.playbook_dir, truth.topic)
        if playbook:
            notes.append(f"  - playbook: `{playbook.topic}`, research coverage {playbook.coverage}")
        derived = {f.key: f.derive_from for f in preset.facts if f.derive_from}
        for problem in truth.problems(derived):
            print(f"  label check: {problem}")
            notes.append(f"  - label check: {problem}")

        for cfg in [] if args.report_only else grid(args):
            label = config_label(cfg)
            out = results_dir / f"{name}__{label}.json"
            estimate = estimate_input_tokens(info.duration_s, cfg["fps"], cfg["resolution"])
            record: dict
            if cfg["playbook"] and playbook is None:
                print(f"  {label}: skipped, no playbook for topic {truth.topic!r}")
                continue
            saved = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else None
            if saved and args.retry_errors and saved.get("status") == "error":
                saved = None
            if saved and not args.force and not args.dry_run:
                record = saved
                print(f"  {label}: reused saved result")
            elif args.dry_run:
                record = {"status": "dry-run", "estimated_input_tokens": estimate}
                print(f"  {label}: about {estimate:,} input tokens (estimate)")
            else:
                print(f"  {label}: running (about {estimate:,} input tokens)", flush=True)
                record = {"name": name, "config": cfg, "estimated_input_tokens": estimate}
                try:
                    run = await run_analysis(
                        provider, proxy, preset, video,
                        fps=cfg["fps"], media_resolution=cfg["resolution"],
                        processing=cfg["processing"], time_format=cfg["time_format"],
                        playbook=playbook if cfg["playbook"] else None,
                    )
                    record |= {
                        "status": "ok", "model": run.model, "usage": run.usage,
                        "latency_s": round(run.latency_s, 1), "analysis": run.analysis.model_dump(),
                    }
                except LLMParseError as exc:
                    record |= {"status": "parse-error", "error": str(exc), "raw_text": exc.raw_text}
                except LLMError as exc:
                    record |= {"status": "error", "error": str(exc)}
                out.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")

            if record.get("status") == "ok":
                record["score"] = score(truth, record["analysis"], args.tolerance, scores)
                out.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
                o = record["score"]["events"]["overall"]
                print(
                    f"    recall {fmt(o.get('recall'))}, precision {fmt(o.get('precision'))},"
                    f" mean error {fmt(o.get('mean_error_s'), ' s')},"
                    f" facts {record['score']['facts']['correct']}/{record['score']['facts']['total']},"
                    f" tokens in {fmt(record['usage'].get('total_input_tokens'))}"
                )
            elif record.get("status") not in {"dry-run"}:
                print(f"    {record.get('status')}: {record.get('error', '')[:200]}")
            if record.get("status") == "dry-run":
                rows.append(summary_row(name, cfg, record))

        # Report every saved run for this video, not only the ones requested this time.
        saved: list[tuple[dict, dict]] = []
        for path in results_dir.glob(f"{name}__*.json"):
            rec = json.loads(path.read_text(encoding="utf-8"))
            if rec.get("status") == "ok":
                rec["score"] = score(truth, rec["analysis"], args.tolerance, scores)
            saved.append((rec["config"], rec))
        saved.sort(key=lambda r: (
            r[0]["processing"], r[0]["time_format"], r[0]["resolution"] or "", r[0]["fps"] or 0,
            bool(r[0].get("playbook")),
        ))
        rows += [summary_row(name, cfg, rec) for cfg, rec in saved]
        details += [f"### {name}", "", detail_table(truth, saved), ""]

    summary = "\n".join([
        "# Phase 0 analysis accuracy",
        "",
        (
            f"Model: `{settings.gemini_video_model or 'not set'}` · match window ±{args.tolerance:g} s"
            f"{' · dry run, no Gemini calls' if args.dry_run else ''}"
        ),
        "",
        "## Videos",
        *notes,
        "",
        "## Runs",
        SUMMARY_HEAD,
        *rows,
        "",
        (
            "Recall = true events found within the window. Precision = found events that are true."
            " Snapped = the same events after the experimental visual snap."
            " Only event types named in the truth file are scored."
        ),
        "",
        "## Label by label",
        "",
        (
            "Each cell is the gap from your label to the run's nearest event of the same type"
            " (+ means Gemini is late). `missed` means nothing of that type within 10 s."
            " A second line names a different event type within 2 s."
        ),
        "",
        *details,
    ])
    (results_dir / "summary.md").write_text(summary, encoding="utf-8")
    print(f"\nWrote {results_dir / 'summary.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
