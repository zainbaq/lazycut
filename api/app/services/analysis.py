"""Video analysis: build the prompt from the preset, call the provider, normalise the result."""

from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.schemas import Analysis, TimeFormat, build_request_model, normalise
from app.services.llm.base import MediaResolution, Processing, VideoProvider
from app.services.media import percentile, snap_to_spike
from app.services.playbook import Playbook
from app.services.presets import Preset
from app.services.timecode import format_clock

_PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
_env = Environment(
    loader=FileSystemLoader(_PROMPTS), undefined=StrictUndefined, keep_trailing_newline=True,
    autoescape=False,
)

TIME_INSTRUCTIONS: dict[TimeFormat, str] = {
    "clock": "write every timestamp as M:SS.s, minutes and seconds with one decimal (for example 1:04.5).",
    "seconds": "write every timestamp as seconds from the start with one decimal (for example 64.5).",
}

# Tokens per unit from the Gemini 3/4 media-resolution table (aistudio.google.com/docs, 2026-11-14).
# Used only for a rough pre-flight estimate; the real figure comes back with each call.
TOKENS_PER_FRAME = {None: 70, "low": 70, "medium": 70, "high": 280}
AUDIO_TOKENS_PER_SECOND = 25


@dataclass(frozen=True)
class VideoContext:
    kind: str  # "long" | "clip"
    duration_s: float
    topic: str = ""
    subject: str = ""
    topic_terms: str = ""


@dataclass
class AnalysisRun:
    analysis: Analysis
    raw_text: str
    model: str
    usage: dict[str, int]
    latency_s: float
    prompt: str = ""


def estimate_input_tokens(duration_s: float, fps: float | None, resolution: MediaResolution | None) -> int:
    frames = duration_s * (fps or 1.0)
    return int(frames * TOKENS_PER_FRAME[resolution] + duration_s * AUDIO_TOKENS_PER_SECOND)


def render_prompt(
    preset: Preset, video: VideoContext, time_format: TimeFormat = "clock", playbook: Playbook | None = None
) -> str:
    labels = {e.id: e.label for e in preset.event_types}
    facts = []
    for fact in preset.facts:
        if fact.instructions:
            guidance = " ".join(fact.instructions.split())
        elif fact.derive_from:
            guidance = f"Count the `{fact.derive_from}` events ({labels[fact.derive_from]})."
        else:
            guidance = "Propose a value from what you can see, or leave it uncertain."
        if fact.options:
            guidance += f" One of: {', '.join(fact.options)}."
        facts.append({"key": fact.key, "label": fact.label, "type": fact.type, "guidance": guidance})
    return _env.get_template("analysis.md").render(
        kind="A pre-trimmed clip" if video.kind == "clip" else "A full-length video",
        duration=format_clock(video.duration_s, decimals=0),
        topic=video.topic.strip(),
        subject=video.subject.strip(),
        topic_terms=video.topic_terms.strip(),
        event_types=preset.event_types,
        facts=facts,
        time_instruction=TIME_INSTRUCTIONS[time_format],
        playbook=playbook,
        playbook_entries=playbook.entries_for(preset) if playbook else [],
    )


async def run_analysis(
    provider: VideoProvider,
    proxy: Path,
    preset: Preset,
    video: VideoContext,
    fps: float | None = None,
    media_resolution: MediaResolution | None = None,
    processing: Processing = "static",
    time_format: TimeFormat = "clock",
    playbook: Playbook | None = None,
) -> AnalysisRun:
    prompt = render_prompt(preset, video, time_format, playbook)
    result = await provider.analyze_video(
        proxy,
        prompt,
        build_request_model(preset, time_format),
        fps=fps,
        media_resolution=media_resolution,
        processing=processing,
    )
    return AnalysisRun(
        analysis=normalise(result.parsed, duration_s=video.duration_s),
        raw_text=result.raw_text,
        model=result.model,
        usage=result.usage,
        latency_s=result.latency_s,
        prompt=prompt,
    )


def snap_event_times(event_times: list[float], times: list[float], scores: list[float]) -> list[float]:
    """Experimental visual snap (EVENT_SNAP=visual): pull each event to a nearby scene-score spike."""
    floor = percentile(scores, 90)
    return [snap_to_spike(t, times, scores, floor) for t in event_times]
