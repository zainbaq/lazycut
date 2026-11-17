"""The refine pass (BUILD_SPEC 7.3): one moment, looked at closely.

The full pass samples the whole video at about one frame a second, so its times are rough.
Here a few seconds around one time are cut from the SOURCE file, sampled at a high rate, and
the video model is asked for one thing only: when exactly the described moment happens. The
window's offset is added back to the answer.

It is a separate stage of the event engine: it takes a time and a description and returns a
time, and knows nothing about clips, events or the database.
"""

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.services.llm.base import LLMResult, VideoProvider
from app.services.media import cut_excerpt
from app.services.timecode import parse_time

WINDOW_S = 6.0      # how much of the video the model looks at
REFINE_FPS = 10.0   # frames a second it is sampled at


class RefineOut(BaseModel):
    found: bool
    t: str = ""       # seconds from the start of the excerpt, one decimal ("2.4")
    confidence: Literal["certain", "uncertain"] = "uncertain"
    seen: str = ""    # one short sentence on what marks the moment


@dataclass
class Refined:
    t: float | None           # the moment in the video's own time; None when it was not found
    confidence: str
    seen: str
    window: tuple[float, float]
    result: LLMResult[RefineOut]
    prompt: str


def window_around(t: float, duration_s: float, window_s: float = WINDOW_S) -> tuple[float, float]:
    """A window of `window_s` centred on `t`, slid to stay inside the video."""
    length = min(window_s, duration_s)
    start = min(max(0.0, t - length / 2), max(0.0, duration_s - length))
    return round(start, 3), round(start + length, 3)


def refine_prompt(cue: str, length_s: float, expected_s: float) -> str:
    return (
        f"This is a {length_s:.1f}-second excerpt of a longer video, sampled closely. Find one moment in it.\n\n"
        f"The moment: {cue.strip()}\n\n"
        f"An earlier, rougher pass put it about {expected_s:.1f} s into this excerpt; trust what you see over that.\n"
        "Answer with `t`: the time from the START OF THIS EXCERPT, in seconds with one decimal (for example 2.4), "
        "of the first frame where the moment begins. If the moment is not in the excerpt, answer found = false "
        "and leave `t` empty; do not guess. `seen`: one short sentence on what marks it."
    )


async def refine_moment(provider: VideoProvider, source: Path, t: float, cue: str, duration_s: float,
                        workdir: Path, window_s: float = WINDOW_S, fps: float = REFINE_FPS) -> Refined:
    """Ask the video model where exactly `cue` happens near `t`. The excerpt is deleted afterwards."""
    start, end = window_around(t, duration_s, window_s)
    excerpt = workdir / f"refine_{uuid.uuid4().hex[:8]}.mp4"
    prompt = refine_prompt(cue, end - start, t - start)
    try:
        await cut_excerpt(source, excerpt, start, end)
        result = await provider.analyze_video(excerpt, prompt, RefineOut, fps=fps)
    finally:
        excerpt.unlink(missing_ok=True)
    answer = result.parsed
    moment: float | None = None
    if answer.found and answer.t.strip():
        try:
            inside = parse_time(answer.t)
        except ValueError:
            inside = None
        # An answer outside the excerpt is a wrong answer, not a moment.
        if inside is not None and inside <= (end - start) + 0.25:
            moment = round(min(end, start + inside), 3)
    return Refined(moment, answer.confidence, answer.seen.strip(), (start, end), result, prompt)
