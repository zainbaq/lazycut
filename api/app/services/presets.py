"""Load and validate the channel profile and presets (YAML in the config folder).

Everything niche-specific lives in presets. A preset that fails validation is
reported and skipped; the built-in General preset keeps the app usable.
"""

import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from ruamel.yaml import YAML

BUILTIN_VARIABLES = frozenset(
    {
        "topic",
        "subject",
        "channel_name",
        "display_name",
        "handle",
        "tagline",
        "playlist_url",
        "subscribe_url",
        "full_video_ref",
        "chapters",
        "credit_block",
        "hashtags",
        "hook",
    }
)
_VARIABLE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

Operator = Literal["eq", "ne", "gt", "gte", "lt", "lte", "between", "in"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EventType(_Strict):
    id: str
    label: str
    glyph: Literal["slash", "dot", "ring", "diamond"] = "dot"
    color: Literal["accent", "paper", "warn", "gold"] = "paper"
    definition: str
    show: bool = True


class FactDef(_Strict):
    key: str
    label: str
    type: Literal["int", "text", "bool", "enum"] = "text"
    options: list[str] = []
    derive_from: str | None = None
    required: bool = False
    instructions: str | None = None


class ResearchField(_Strict):
    key: str
    label: str | None = None
    type: Literal["text", "bool"] = "text"
    needs_credible_source: bool = False
    hint: str | None = None  # what to look for, shown to the research model


class Condition(_Strict):
    fact: str | None = None
    research: str | None = None
    op: Operator = "eq"
    value: Any = None

    @model_validator(mode="after")
    def _one_subject(self) -> "Condition":
        if (self.fact is None) == (self.research is None):
            raise ValueError("a condition needs exactly one of `fact` or `research`")
        if self.op == "between" and not (isinstance(self.value, list) and len(self.value) == 2):
            raise ValueError("`between` needs a [low, high] value")
        if self.op == "in" and not isinstance(self.value, list):
            raise ValueError("`in` needs a list value")
        return self


class Hook(_Strict):
    id: str
    text: str
    thumbnail_word: str | None = None
    thumbnail_text_style: str | None = None
    when: Condition


class ClaimRule(_Strict):
    id: str
    phrases: list[str]
    requires: Condition
    severity: Literal["block", "warn"] = "block"
    suggest: str | None = None


class ClipRules(_Strict):
    lead_in_s: float = 0.5
    tail_s: float = 0.5
    end_on: list[str] = []
    start_cue: str | None = None
    end_cue: str | None = None


class BannedTag(_Strict):
    """A tag removed automatically unless the condition holds (e.g. `soulslike` unless research says it is one)."""
    tag: str
    unless: Condition | None = None


class TitlePatterns(_Strict):
    recommended: str
    alternates: list[str] = []


class Templates(_Strict):
    description: str | None = None
    shorts_description: str | None = None
    reel: str | None = None
    reel_end_text: str | None = None


class Preset(_Strict):
    id: str
    name: str
    description: str = ""
    event_types: list[EventType] = Field(min_length=1)
    facts: list[FactDef] = []
    research_fields: list[ResearchField] = []
    credit_fields: list[str] = []
    hooks: list[Hook] = []
    thumbnail_words: list[str] = []
    title_patterns: TitlePatterns
    claim_rules: list[ClaimRule] = []
    clip_rules: ClipRules = ClipRules()
    saved_prompts: list[str] = []
    tag_recipe: list[str] = []
    banned_tags: list[str | BannedTag] = []
    slots: dict[str, str] = {}
    templates: Templates = Templates()
    # Search demand (7.7.1): extra suggestion seeds ({topic}, {name}), hashtags that replace an
    # ambiguous name's hashtag, and the playlist to suggest when the topic has none.
    search_seeds: list[str] = []
    search_fit: str = ""        # which generic search phrases describe this kind of video, for the writer
    fallback_hashtags: list[str] = []
    playlist_name: str = "{topic}"
    # Competitor research (7.7): the YouTube search that finds videos like this one ({topic}, {subject}).
    competitor_query: str = "{topic} {subject}"
    # Credit lines, e.g. "Boss: {real_name} ({epithet})". A line whose first variable is empty is left out.
    credit_lines: list[str] = []

    @model_validator(mode="after")
    def _cross_check(self) -> "Preset":
        event_ids = {e.id for e in self.event_types}
        fact_keys = {f.key for f in self.facts}
        research_keys = {r.key for r in self.research_fields}
        problems: list[str] = []

        if len(event_ids) != len(self.event_types):
            problems.append("event type ids must be unique")
        for fact in self.facts:
            if fact.derive_from and fact.derive_from not in event_ids:
                problems.append(f"fact `{fact.key}` derives from unknown event type `{fact.derive_from}`")
            if fact.type == "enum" and not fact.options:
                problems.append(f"enum fact `{fact.key}` needs options")
        for name in self.clip_rules.end_on:
            if name not in event_ids:
                problems.append(f"clip_rules.end_on names unknown event type `{name}`")
        for name in self.credit_fields:
            if name not in research_keys:
                problems.append(f"credit_fields names unknown research field `{name}`")

        def check_condition(where: str, cond: Condition) -> None:
            if cond.fact is not None and cond.fact not in fact_keys:
                problems.append(f"{where} refers to unknown fact `{cond.fact}`")
            if cond.research is not None and cond.research not in research_keys:
                problems.append(f"{where} refers to unknown research field `{cond.research}`")

        for hook in self.hooks:
            check_condition(f"hook `{hook.id}`", hook.when)
        for rule in self.claim_rules:
            check_condition(f"claim rule `{rule.id}`", rule.requires)
        for ban in self.banned_tags:
            if isinstance(ban, BannedTag) and ban.unless:
                check_condition(f"banned tag `{ban.tag}`", ban.unless)
        for seed in self.search_seeds:
            for name in _VARIABLE.findall(seed):
                if name not in ("topic", "name"):
                    problems.append(f"search seed `{seed}` uses `{{{name}}}`; only {{topic}} and {{name}} are allowed")

        for name in _VARIABLE.findall(self.competitor_query):
            if name not in ("topic", "subject"):
                problems.append(f"competitor_query uses `{{{name}}}`; only {{topic}} and {{subject}} are allowed")

        # Hooks may only use facts, so a hook can never carry model-written text.
        for hook in self.hooks:
            for text in (hook.text, hook.thumbnail_word or ""):
                for name in _VARIABLE.findall(text):
                    if name not in fact_keys:
                        problems.append(f"hook `{hook.id}` uses `{{{name}}}`, which is not a fact")

        allowed = BUILTIN_VARIABLES | fact_keys | research_keys | set(self.slots)
        templates = {
            "title_patterns.recommended": self.title_patterns.recommended,
            **{f"title_patterns.alternates[{i}]": t for i, t in enumerate(self.title_patterns.alternates)},
            **{f"templates.{k}": v for k, v in self.templates.model_dump().items() if v},
            **{f"credit_lines[{i}]": t for i, t in enumerate(self.credit_lines)},
            "playlist_name": self.playlist_name,
        }
        for where, text in templates.items():
            for name in _VARIABLE.findall(text):
                if name not in allowed:
                    problems.append(f"{where} uses unknown variable `{{{name}}}`")

        if problems:
            raise ValueError("; ".join(problems))
        return self

    def event_type_ids(self) -> list[str]:
        return [e.id for e in self.event_types]

    def bans(self) -> list[BannedTag]:
        return [b if isinstance(b, BannedTag) else BannedTag(tag=b) for b in self.banned_tags]


class Playlist(_Strict):
    topic: str
    name: str
    url: str


class ChannelProfile(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    display_name: str
    handle: str = ""
    tagline: str = ""
    subscribe_url: str = ""
    default_preset: str = "general"
    strategy_mode: Literal["search_first", "hook_first"] = "search_first"
    playlists: list[Playlist] = []
    description_template: str = ""
    hashtags: dict[str, int] = {}
    shorts_required_hashtag: str = "#Shorts"
    tags_target: int = 20
    credible_domains: list[str] = []
    blocked_domains: list[str] = []


BUILTIN_GENERAL = Preset(
    id="general",
    name="General",
    description="Works on any video. No niche vocabulary, no claim rules.",
    event_types=[
        EventType(id="highlight", label="Highlight", glyph="slash", color="accent",
                  definition="A moment a viewer would want to see again."),
        EventType(id="scene_change", label="Scene change", glyph="ring",
                  definition="The location, activity or subject changes."),
        EventType(id="screen_text", label="On-screen text",
                  definition="New text appears on screen."),
        EventType(id="peak", label="Peak moment", glyph="diamond", color="gold",
                  definition="The most striking moment of a section."),
    ],
    title_patterns=TitlePatterns(recommended="{topic} - {subject}: {hook}"),
)


class ConfigError(BaseModel):
    file: str
    problem: str


def _load_yaml(path: Path) -> Any:
    return YAML(typ="safe").load(path.read_text(encoding="utf-8"))


def _describe(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or 'file'}: {err['msg']}" for err in exc.errors()
        )
    return str(exc)


def load_presets(config_dir: Path) -> tuple[dict[str, Preset], list[ConfigError]]:
    """Return valid presets by id plus one error per file that failed. `general` always exists."""
    presets: dict[str, Preset] = {}
    errors: list[ConfigError] = []
    folder = config_dir / "presets"
    for path in sorted(folder.glob("*.yaml")) if folder.is_dir() else []:
        try:
            preset = Preset.model_validate(_load_yaml(path))
            if preset.id in presets:
                raise ValueError(f"duplicate preset id `{preset.id}`")
            presets[preset.id] = preset
        except Exception as exc:  # noqa: BLE001 - every failure becomes a config error card
            errors.append(ConfigError(file=f"presets/{path.name}", problem=_describe(exc)))
    presets.setdefault("general", BUILTIN_GENERAL)
    return presets, errors


def load_channel(config_dir: Path) -> tuple[ChannelProfile | None, list[ConfigError]]:
    path = config_dir / "channel.yaml"
    if not path.is_file():
        return None, [ConfigError(file="channel.yaml", problem="file not found")]
    try:
        return ChannelProfile.model_validate(_load_yaml(path)), []
    except Exception as exc:  # noqa: BLE001
        return None, [ConfigError(file="channel.yaml", problem=_describe(exc))]
