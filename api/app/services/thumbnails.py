"""Thumbnail creator (BUILD_SPEC 7.13): settings, the frame finder, prompts, request bodies, the word overlay and the review.

The image model only paints. LazyCut picks the source frame, writes the prompt, draws the result
word itself (so it is spelled right and sits in the same template on every video), sizes the
file for the platform and has Claude check the result for the usual failures: broken faces or
hands, HUD the model left behind, and text that is wrong or hard to read.
"""

import io
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageStat
from pydantic import BaseModel, Field, ValidationError, field_validator
from ruamel.yaml import YAML

ASPECTS = ("16:9", "9:16")
CORNERS = ("top_left", "top_right", "bottom_left", "bottom_right")
OUTPUT_SIZE = {"16:9": (1280, 720), "9:16": (1080, 1920)}   # YouTube thumbnail; Stories / Shorts cover
MAX_BYTES = 2 * 1024 * 1024                                  # YouTube's thumbnail limit
FONTS = {
    "bebas": ("BebasNeue-Regular", "BebasNeue"),
    "montserrat": ("Montserrat-Black", "Montserrat-ExtraBold", "Montserrat-Bold"),
    "league_spartan": ("LeagueSpartan-Black", "LeagueSpartan-ExtraBold", "LeagueSpartan-Bold"),
    "dejavu": ("DejaVuSans-Bold",),
}
FONT_DIRS = (Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path("/config/fonts"))
SETTINGS_KEY = "thumbnails"


# ---- settings -----------------------------------------------------------------------


class ThumbModel(BaseModel):
    label: str
    path: str
    image_field: str = "image_urls"
    negative_field: str | None = None
    params: dict[str, Any] = {}
    options: dict[str, list[Any]] = {}

    @property
    def single_image(self) -> bool:
        return not self.image_field.endswith("s")


class ThumbConfig(BaseModel):
    default_model: str
    text_mode: Literal["app", "model"] = "app"
    review: bool = True
    text_corner: Literal["auto", "top_left", "top_right", "bottom_left", "bottom_right"] = "auto"
    font: Literal["bebas", "montserrat", "league_spartan", "dejavu"] = "bebas"
    aspects: list[Literal["16:9", "9:16"]] = ["16:9"]
    models: dict[str, ThumbModel]
    prompt: str
    text_instruction: dict[Literal["app", "model"], str]
    framing: dict[str, str] = {}

    @field_validator("models")
    @classmethod
    def _some_models(cls, v: dict) -> dict:
        if not v:
            raise ValueError("list at least one model")
        return v


class Overrides(BaseModel):
    """What the Advanced settings page saves. Every field is optional; unset keeps the YAML default."""

    model: str | None = None
    params: dict[str, dict[str, Any]] = {}
    text_mode: Literal["app", "model"] | None = None
    review: bool | None = None
    text_corner: Literal["auto", "top_left", "top_right", "bottom_left", "bottom_right"] | None = None
    font: Literal["bebas", "montserrat", "league_spartan", "dejavu"] | None = None
    aspects: list[Literal["16:9", "9:16"]] | None = None
    prompt: str | None = Field(default=None, max_length=4000)  # a custom template; None = the YAML one


def load_config(config_dir: Path) -> tuple[ThumbConfig | None, str | None]:
    path = config_dir / "thumbnails.yaml"
    if not path.is_file():
        return None, "config/thumbnails.yaml not found"
    try:
        cfg = ThumbConfig.model_validate(YAML(typ="safe").load(path.read_text(encoding="utf-8")))
    except ValidationError as exc:
        return None, f"thumbnails.yaml: {exc.errors()[0]['loc']} {exc.errors()[0]['msg']}"
    except Exception as exc:  # noqa: BLE001 - a YAML syntax error is reported, not raised
        return None, f"thumbnails.yaml: {exc}"
    if cfg.default_model not in cfg.models:
        return None, f"thumbnails.yaml: default_model `{cfg.default_model}` is not under models"
    return cfg, None


def validate_overrides(cfg: ThumbConfig, ov: Overrides) -> list[str]:
    problems: list[str] = []
    if ov.model is not None and ov.model not in cfg.models:
        problems.append(f"Unknown model `{ov.model}`")
    for model_id, params in ov.params.items():
        model = cfg.models.get(model_id)
        if model is None:
            problems.append(f"Unknown model `{model_id}`")
            continue
        for key, value in params.items():
            allowed = model.options.get(key)
            if allowed is None and model.params.get(key, object()) == value:
                continue  # a fixed default sent back as GET returned it
            if allowed is None:
                problems.append(f"{model.label} has no option `{key}`")
            elif value not in allowed:
                problems.append(f"{model.label} {key} must be one of {allowed}")
    if ov.aspects is not None and not ov.aspects:
        problems.append("Pick at least one aspect")
    if ov.prompt is not None and not ov.prompt.strip():
        problems.append("The custom prompt is empty; clear it to use the default")
    return problems


@dataclass
class Effective:
    cfg: ThumbConfig
    model: str
    params: dict[str, dict[str, Any]]
    text_mode: str
    review: bool
    text_corner: str
    font: str
    aspects: list[str]
    prompt: str
    custom_prompt: bool

    def model_params(self, model_id: str) -> dict[str, Any]:
        return dict(self.cfg.models[model_id].params) | self.params.get(model_id, {})

    def view(self) -> dict:
        return {
            "model": self.model, "text_mode": self.text_mode, "review": self.review,
            "text_corner": self.text_corner, "font": self.font, "aspects": self.aspects,
            "prompt": self.prompt, "custom_prompt": self.custom_prompt, "default_prompt": self.cfg.prompt,
            "models": [
                {"id": mid, "label": m.label, "path": m.path, "params": self.model_params(mid), "options": m.options}
                for mid, m in self.cfg.models.items()
            ],
        }


def effective(cfg: ThumbConfig, ov: Overrides | None) -> Effective:
    ov = ov or Overrides()
    model = ov.model if ov.model in cfg.models else cfg.default_model
    return Effective(
        cfg=cfg, model=model, params={k: v for k, v in ov.params.items() if k in cfg.models},
        text_mode=ov.text_mode or cfg.text_mode, review=cfg.review if ov.review is None else ov.review,
        text_corner=ov.text_corner or cfg.text_corner, font=ov.font or cfg.font,
        aspects=list(ov.aspects or cfg.aspects), prompt=ov.prompt or cfg.prompt, custom_prompt=bool(ov.prompt),
    )


# ---- prompts and request bodies -----------------------------------------------------

_VAR = re.compile(r"\{(\w+)\}")


def fill(template: str, values: dict[str, str]) -> str:
    """Replace known {variables}; leave any other braces alone (a pasted prompt may contain some)."""
    return _VAR.sub(lambda m: values.get(m.group(1), m.group(0)), template)


def corner_words(corner: str, aspect: str = "16:9") -> str:
    """Where the word goes, in the prompt's words. In 9:16 it is drawn centred across a band, not in a corner."""
    if aspect == "9:16":
        return ("top" if corner.startswith("top") else "bottom") + " 40% of the picture"
    return corner.replace("_", " ") + " corner"


def build_prompt(eff: Effective, *, template: str | None, topic: str, subject: str, word: str, text_style: str,
                 corner: str, aspect: str, avoid: str = "", text_mode: str | None = None) -> str:
    mode = text_mode or eff.text_mode
    values = {
        "topic": topic or "the game", "subject": subject or "the main character", "word": word,
        "text_style": text_style or "white with a heavy black outline", "text_corner": corner_words(corner, aspect),
        "aspect": "16:9 landscape" if aspect == "16:9" else "9:16 portrait", "avoid": avoid,
    }
    values["text_instruction"] = fill(eff.cfg.text_instruction[mode], values)  # type: ignore[index]
    values["framing"] = fill(eff.cfg.framing.get(aspect, ""), values)
    text = fill(template or eff.prompt, values)
    return "\n".join(line for line in text.splitlines() if line.strip()).strip()


NEGATIVE = "watermark, logo, border, health bar, HUD, button prompt, subtitles, extra fingers, deformed hands, extra limbs"


def request_body(model: ThumbModel, params: dict, prompt: str, image_url: str, aspect: str, text_mode: str) -> dict:
    body: dict[str, Any] = {"prompt": prompt, **params, "aspect_ratio": aspect}
    body[model.image_field] = image_url if model.single_image else [image_url]
    if model.negative_field:
        body[model.negative_field] = NEGATIVE + (", text, letters" if text_mode == "app" else "")
    return body


# ---- frame finder -------------------------------------------------------------------


@dataclass
class FrameStats:
    sharpness: float
    contrast: float
    colorfulness: float
    brightness: float
    corner_busy: dict[str, float]
    dhash: int

    @property
    def free_corner(self) -> str:
        return min(self.corner_busy, key=self.corner_busy.get)  # type: ignore[arg-type]


_LAPLACE = ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=128)


def dhash(img: Image.Image) -> int:
    small = img.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    px = list(small.getdata())
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (px[row * 9 + col] > px[row * 9 + col + 1])
    return bits


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def frame_stats(img: Image.Image) -> FrameStats:
    rgb = img.convert("RGB")
    w = 320
    rgb = rgb.resize((w, max(1, round(rgb.height * w / rgb.width))), Image.Resampling.BILINEAR)
    gray = rgb.convert("L")
    lap = gray.filter(_LAPLACE)
    sharp = ImageStat.Stat(lap).var[0]
    stat = ImageStat.Stat(gray)
    # Hasler and Suesstrunk colourfulness, on a small copy.
    tiny = rgb.resize((80, max(1, round(80 * rgb.height / rgb.width))))
    rg, yb = [], []
    for r, g, b in tiny.getdata():
        rg.append(r - g)
        yb.append(0.5 * (r + g) - b)

    def mean_std(xs: list[float]) -> tuple[float, float]:
        m = sum(xs) / len(xs)
        return m, math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))

    (mrg, srg), (myb, syb) = mean_std(rg), mean_std(yb)
    colorful = math.sqrt(srg ** 2 + syb ** 2) + 0.3 * math.sqrt(mrg ** 2 + myb ** 2)
    edges = gray.filter(ImageFilter.FIND_EDGES)
    cw, ch = round(w * 0.38), round(gray.height * 0.38)
    boxes = {
        "top_left": (0, 0, cw, ch), "top_right": (w - cw, 0, w, ch),
        "bottom_left": (0, gray.height - ch, cw, gray.height), "bottom_right": (w - cw, gray.height - ch, w, gray.height),
    }
    busy = {k: round(ImageStat.Stat(edges.crop(box)).mean[0], 2) for k, box in boxes.items()}
    return FrameStats(sharpness=sharp, contrast=stat.stddev[0], colorfulness=colorful,
                      brightness=stat.mean[0], corner_busy=busy, dhash=dhash(rgb))


def candidate_times(duration_s: float, *, writer_ts: list[float], peaks: list[tuple[float, float]],
                    events: list[tuple[float, float, str]], intensity: list[tuple[float, float]],
                    limit: int = 24) -> list[tuple[float, str]]:
    """Moments worth a look, with why: the writer's picks, peaks, high-intensity events and the busiest seconds.

    Times within a second of an earlier one are dropped; even spacing fills up if there are few.
    """
    edge = min(1.0, duration_s / 10)
    out: list[tuple[float, str]] = []

    def add(t: float, why: str) -> None:
        t = round(min(max(t, edge), max(edge, duration_s - edge)), 2)
        if len(out) < limit and all(abs(t - u) >= 1.0 for u, _ in out):
            out.append((t, why))

    for t in writer_ts:
        add(t, "picked by the writer")
    for start, end in peaks:
        add((start + end) / 2, "peak moment")
    for start, end, label in events:
        add((start + end) / 2, label or "high-intensity event")
    for t, _score in sorted(intensity, key=lambda x: -x[1])[:12]:
        add(t, "busiest moment")
    n = max(0, min(10, limit - len(out)))
    for i in range(n):
        add(duration_s * (i + 0.5) / n, "evenly spaced")
    return sorted(out)


def _rank(values: list[float]) -> list[float]:
    """Each value against the set's 90th percentile, capped at 1 (scales differ per video)."""
    if not values:
        return []
    top = sorted(values)[min(len(values) - 1, round(0.9 * (len(values) - 1)))] or 1.0
    return [min(1.0, v / top) for v in values]


def _duplicate(a: dict, b: dict) -> bool:
    bits = hamming(a["stats"].dhash, b["stats"].dhash)
    return bits <= 2 or (bits <= 6 and abs(a["t"] - b["t"]) < 3.0)


def score_frames(frames: list[dict]) -> list[dict]:
    """Add `code_score` (0-1) to each {t, why, stats, drama}: sharpness first, then contrast, colour and drama.

    Too dark or blown-out frames lose half their score. Frames sharing a `moment` (looked at around
    one candidate time) keep only the best. Near-duplicates keep only the best: frames
    under 3 s apart that look alike (dHash within 6 bits), or frames anywhere that look the same (within 2).
    A fixed-camera arena looks alike all fight long, so distance in time keeps those apart.
    """
    sharp = _rank([f["stats"].sharpness for f in frames])
    contrast = _rank([f["stats"].contrast for f in frames])
    colour = _rank([f["stats"].colorfulness for f in frames])
    for f, s, c, k in zip(frames, sharp, contrast, colour, strict=True):
        score = 0.45 * s + 0.25 * c + 0.15 * k + 0.15 * f.get("drama", 0.0)
        b = f["stats"].brightness
        if b < 35 or b > 215:
            score *= 0.5
        f["code_score"] = round(score, 3)
    kept: list[dict] = []
    moments: set[float] = set()
    for f in sorted(frames, key=lambda x: -x["code_score"]):
        moment = f.get("moment")
        if moment is not None and moment in moments:
            continue  # only the best of the frames looked at around one moment
        if not any(_duplicate(f, k) for k in kept):
            if moment is not None:
                moments.add(moment)
            kept.append(f)
    return kept


# ---- the word overlay ---------------------------------------------------------------

COLORS = {
    "white": (255, 255, 255), "black": (0, 0, 0), "gold": (255, 196, 0), "yellow": (255, 228, 0),
    "red": (232, 32, 32), "orange": (255, 136, 0), "cyan": (0, 220, 255), "blue": (40, 120, 255),
    "green": (60, 220, 90), "purple": (170, 80, 255), "silver": (222, 222, 232), "pink": (255, 90, 170),
}


@dataclass
class TextStyle:
    fill: tuple[int, int, int] = (255, 255, 255)
    stroke: tuple[int, int, int] = (0, 0, 0)
    glow: bool = False


def parse_style(text: str) -> TextStyle:
    """"gold, heavy black outline" -> gold fill, black stroke. The first colour not naming the outline is the fill."""
    words = re.findall(r"[a-z]+", (text or "").lower())
    style = TextStyle()
    fill_set = False
    for i, word in enumerate(words):
        if word not in COLORS:
            continue
        nxt = words[i + 1] if i + 1 < len(words) else ""
        if nxt in ("outline", "stroke", "border"):
            style.stroke = COLORS[word]
        elif not fill_set:
            style.fill, fill_set = COLORS[word], True
    style.glow = "glow" in words
    return style


def font_file(name: str) -> Path | None:
    for stem in FONTS.get(name, ()) + FONTS["dejavu"]:
        for folder in FONT_DIRS:
            if folder.is_dir():
                for path in folder.rglob(f"{stem}*"):
                    if path.suffix.lower() in (".ttf", ".otf"):
                        return path
    return None


def fit_cover(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Scale to cover `size` and crop the middle (the model may return a slightly different ratio)."""
    w, h = size
    scale = max(w / img.width, h / img.height)
    resized = img.convert("RGB").resize((math.ceil(img.width * scale), math.ceil(img.height * scale)),
                                        Image.Resampling.LANCZOS)
    left, top = (resized.width - w) // 2, (resized.height - h) // 2
    return resized.crop((left, top, left + w, top + h))


def _lines(word: str) -> list[list[str]]:
    parts = word.upper().split()
    if len(parts) <= 1:
        return [[word.upper()]]
    options = [[" ".join(parts)]]
    for cut in range(1, len(parts)):
        options.append([" ".join(parts[:cut]), " ".join(parts[cut:])])
    return options


MIN_WORD_SCALE = 0.65  # a 9:16 word shrinks to fit the open space, but never below this share of its full size


def clear_run(img: Image.Image, top: bool, start: float, width: float = 0.6) -> float:
    """How far the open background runs from the safe line towards the middle, as a share of the height.

    Only the columns the word will cover count (`width`, centred). A row is busy when detail fills more than a
    third of them, so a branch poking in from one side does not end the run but a character under the word does.
    Sky, mist and soft ground are calm. A dark character on dark ground can be missed.
    """
    w, h = 108, round(108 * img.height / img.width)
    edges = img.convert("L").resize((w, h), Image.Resampling.BOX).filter(ImageFilter.FIND_EDGES)
    x0, x1 = round(w * (0.5 - width / 2)), round(w * (0.5 + width / 2))
    detail = edges.crop((x0, 0, x1, h)).point(lambda v: 255 if v > 28 else 0)
    rows = [ImageStat.Stat(detail.crop((0, y, x1 - x0, y + 1))).mean[0] / 255 for y in range(h)]
    rows = [sum(rows[max(0, y - 2):y + 3]) / len(rows[max(0, y - 2):y + 3]) for y in range(h)]  # smooth
    order = range(round(h * start), h // 2) if top else range(h - 1 - round(h * start), h // 2, -1)
    run = 0
    for y in order:
        if rows[y] > 1 / 3:
            break
        run += 1
    return run / h


def draw_word(img: Image.Image, word: str, style: TextStyle, corner: str, aspect: str, font_name: str,
              safe: dict | None = None) -> Image.Image:
    """Draw the word huge, with a heavy outline and a soft shadow, in the corner; 9:16 keeps inside the safe margins."""
    word = word.strip()
    if not word:
        return img
    out = img.convert("RGB").copy()
    W, H = out.size
    path = font_file(font_name)
    max_w = W * (0.48 if aspect == "16:9" else 0.86)
    max_h = H * (0.36 if aspect == "16:9" else 0.2)
    margin_x = W * 0.045
    top_safe = H * ((safe or {}).get("top_pct", 12) / 100 if aspect == "9:16" else 0.05)
    bottom_safe = H * ((safe or {}).get("bottom_pct", 15) / 100 if aspect == "9:16" else 0.05)

    def load(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        return ImageFont.truetype(str(path), size) if path else ImageFont.load_default(size)

    best: tuple[int, list[str]] | None = None
    for lines in _lines(word):
        lo, hi = 8, int(H)
        while lo < hi:  # the largest size that fits
            mid = (lo + hi + 1) // 2
            font = load(mid)
            stroke = max(3, round(mid * 0.075))
            widths = [ImageDraw.Draw(out).textbbox((0, 0), ln, font=font, stroke_width=stroke)[2] for ln in lines]
            height = mid * 1.0 * len(lines) + stroke * 2
            if max(widths) <= max_w and height <= max_h:
                lo = mid
            else:
                hi = mid - 1
        if best is None or lo > best[0]:
            best = (lo, lines)
    size, lines = best  # type: ignore[misc]
    draw = ImageDraw.Draw(out)

    def measure(size: int) -> tuple[Any, int, list, int, int, int]:
        font = load(size)
        stroke = max(3, round(size * 0.075))
        boxes = [draw.textbbox((0, 0), ln, font=font, stroke_width=stroke) for ln in lines]
        line_h = max(b[3] - b[1] for b in boxes)
        gap = round(size * 0.04)
        return font, stroke, boxes, line_h, gap, line_h * len(lines) + gap * (len(lines) - 1)

    font, stroke, boxes, line_h, gap, block_h = measure(size)
    top = corner.startswith("top")
    right: bool | None = corner.endswith("right")
    nudge = 0.0
    if aspect == "9:16":
        right = None  # centred horizontally on a phone cover
        # The model decides how much open space it leaves, so measure it on the painted picture and fit the word
        # to it: smaller when the subject comes close (never under MIN_WORD_SCALE), a little lower when there is room.
        span = min(0.9, max(b[2] - b[0] for b in boxes) / W + 0.04)
        room = clear_run(out, top, (top_safe if top else bottom_safe) / H, span) * H - H * 0.012
        if block_h > room:
            size = max(8, int(size * max(room / block_h, MIN_WORD_SCALE)))
            font, stroke, boxes, line_h, gap, block_h = measure(size)
        nudge = min(max(room - block_h, 0) / 2, H * 0.02)
    y0 = top_safe + nudge if top else H - bottom_safe - block_h - nudge

    layer = Image.new("RGBA", out.size, (0, 0, 0, 0))
    shadow = Image.new("RGBA", out.size, (0, 0, 0, 0))
    ld, sd = ImageDraw.Draw(layer), ImageDraw.Draw(shadow)
    for i, (ln, box) in enumerate(zip(lines, boxes, strict=True)):
        width = box[2] - box[0]
        if right is None:
            x = (W - width) / 2 - box[0]
        else:
            x = (W - margin_x - width - box[0]) if right else (margin_x - box[0])
        y = y0 + i * (line_h + gap) - box[1]
        off = max(2, round(size * 0.05))
        sd.text((x + off, y + off), ln, font=font, fill=(0, 0, 0, 170), stroke_width=stroke, stroke_fill=(0, 0, 0, 170))
        if style.glow:
            sd.text((x, y), ln, font=font, fill=(*style.fill, 160), stroke_width=stroke * 2, stroke_fill=(*style.fill, 120))
        ld.text((x, y), ln, font=font, fill=(*style.fill, 255), stroke_width=stroke, stroke_fill=(*style.stroke, 255))
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(2, size * 0.04)))
    out = Image.alpha_composite(out.convert("RGBA"), shadow)
    out = Image.alpha_composite(out, layer)
    return out.convert("RGB")


def encode_jpeg(img: Image.Image, limit: int = MAX_BYTES) -> bytes:
    for quality in (92, 88, 84, 78, 70, 60):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
        if buf.tell() <= limit:
            return buf.getvalue()
    return buf.getvalue()


def render_final(raw: Image.Image, *, aspect: str, word: str, text_style: str, corner: str, font: str,
                 text_mode: str, safe: dict | None = None) -> bytes:
    sized = fit_cover(raw, OUTPUT_SIZE[aspect])
    if text_mode == "app" and word.strip():
        sized = draw_word(sized, word, parse_style(text_style), corner, aspect, font, safe)
    return encode_jpeg(sized)


def text_contrast(img: Image.Image, corner: str) -> float:
    """How much the corner behind the word varies (0-255 std). A calm corner keeps the word readable."""
    W, H = img.size
    if H > W:  # 9:16: the word is centred across a band inside the safe margins
        cw, ch = round(W * 0.86), round(H * 0.2)
        x = (W - cw) // 2
        y = round(H * 0.12) if corner.startswith("top") else H - round(H * 0.15) - ch
        return ImageStat.Stat(img.convert("L").crop((x, y, x + cw, y + ch))).stddev[0]
    cw, ch = round(W * 0.45), round(H * 0.36)
    x = W - cw if corner.endswith("right") else 0
    y = 0 if corner.startswith("top") else H - ch
    return ImageStat.Stat(img.convert("L").crop((x, y, x + cw, y + ch))).stddev[0]


def same_image(a: Image.Image, b: Image.Image) -> bool:
    """True when the model returned the source unchanged (some models do on a refusal)."""
    size = (64, 36)
    diff = ImageChops.difference(a.convert("L").resize(size), b.convert("L").resize(size))
    return ImageStat.Stat(diff).mean[0] < 3


# ---- Claude: frame ranking and result review ----------------------------------------


class FrameJudgement(BaseModel):
    index: int
    score: int = Field(ge=0, le=10, description="How good a thumbnail source this frame is")
    subject_visible: bool = Field(description="The boss or main subject is clearly visible")
    hud: Literal["none", "light", "heavy"]
    text_corner: Literal["top_left", "top_right", "bottom_left", "bottom_right"]
    reason: str = Field(description="Under 15 words")


class FrameRanking(BaseModel):
    frames: list[FrameJudgement]


def ranking_prompt(topic: str, subject: str, count: int) -> str:
    return (
        f"These {count} numbered frames (0 to {count - 1}, in order) come from a gameplay video of "
        f"{subject or 'a boss fight'} in {topic or 'a game'}. An image model will turn the chosen frame into a "
        "YouTube thumbnail, keeping the characters and removing the HUD.\n"
        "Judge each frame as a thumbnail source. A great frame shows the subject large and clear, in a "
        "dramatic action or a strong pose, with readable faces and bodies, little motion blur, and one "
        "calm corner where a two-word caption can go. Heavy HUD is fixable but lowers the score a little; "
        "a frame where the subject is hidden, tiny, or mid-transition scores low.\n"
        "For every frame give: index, score 0-10, subject_visible, hud (none, light, heavy), the calmest "
        "corner for text, and a reason under 15 words."
    )


class Check(BaseModel):
    id: Literal["faces", "hands", "hud", "text", "likeness", "artifacts", "placement"]
    ok: bool
    note: str = Field(description="Under 20 words; what is wrong, or 'fine'")


class ReviewOut(BaseModel):
    checks: list[Check]
    summary: str = Field(description="One sentence")


REVIEW_IDS = ("faces", "hands", "hud", "text", "likeness", "artifacts", "placement")


def review_prompt(*, word: str, text_mode: str, subject: str, avoid: str, aspect: str) -> str:
    text_rule = (
        f'The caption "{word}" must be spelled exactly, easy to read at phone size, and be the only text. '
        "Narrow or missing gaps between its words are fine; judge the letters and digits only."
        if word else "There should be no text at all."
    )
    return (
        "Image 1 is a gameplay frame. Image 2 is a YouTube thumbnail made from it "
        f"({aspect}, the caption was {'drawn by the app' if text_mode == 'app' else 'drawn by the image model'}).\n"
        "Check image 2 strictly, the way a creator would before uploading:\n"
        "- faces: faces are intact and not melted, doubled or distorted\n"
        "- hands: hands and fingers look right, weapons are held plausibly, no extra limbs\n"
        "- hud: no game HUD is left (health or boss bars, button prompts, subtitles, damage numbers, minimap, lock-on or waypoint markers)\n"
        f"- text: {text_rule}\n"
        f"- likeness: {subject or 'the subject'} and the player character still match image 1 (design, colours, gear)\n"
        "- artifacts: no smears, seams, duplicated objects, watermarks or logos\n"
        f"- placement: the caption does not cover a face, the subject or a weapon{'; ' + avoid if avoid else ''}\n"
        "Return all seven checks with ok true or false and a short note, and a one-sentence summary."
    )


def review_dict(out: ReviewOut, model: str) -> dict:
    checks = {c.id: c for c in out.checks}
    ordered = [checks[i].model_dump() if i in checks else {"id": i, "ok": True, "note": "not checked"}
               for i in REVIEW_IDS]
    problems = [c for c in ordered if not c["ok"]]
    return {"verdict": "ok" if not problems else "check", "checks": ordered, "summary": out.summary,
            "problems": len(problems), "model": model}


@dataclass
class Prepared:
    """What one thumbnail request needs, decided before any paid call."""

    model_id: str
    params: dict
    prompt: str
    aspect: str
    word: str
    text_style: str
    corner: str
    custom_prompt: bool
    extra: dict = field(default_factory=dict)
