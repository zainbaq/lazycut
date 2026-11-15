"""The rules engine (BUILD_SPEC 7.9): deterministic checks on a package, no LLM.

`check` returns the package fields with auto-fixes applied, and one result per rule and field:
`{key, rule_id, severity: pass|warn|block, field, message, evidence, fixed, dismissed}`.
A block disables Copy for that field; a warn can be dismissed per package (its key is kept).
"""

import copy
import re
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

from app.services.presets import ChannelProfile, Preset
from app.services.research import name_key
from app.services.templating import holds

# YouTube long-form limits (checked 2026-11: title 100 characters, description 5,000,
# all tags together 500 characters counting separators).
LENGTH_LIMITS = {"youtube": {"title": 100, "description": 5000, "tags": 500, "pinned_comment": 10000}}
TAGS_TOLERANCE = 5


@dataclass
class RuleContext:
    platform: str
    preset: Preset
    channel: ChannelProfile | None
    topic: str
    subject: str
    facts: dict[str, Any]          # confirmed facts only
    research: dict[str, Any]       # effective research values
    past_subjects: list[dict] = field(default_factory=list)  # [{title, subject, angle}]
    dismissed: set[str] = field(default_factory=set)


def _result(rule_id: str, severity: str, field_name: str, message: str, evidence: Any = None,
            fixed: bool = False) -> dict:
    return {
        "key": f"{rule_id}:{field_name}", "rule_id": rule_id, "severity": severity, "field": field_name,
        "message": message, "evidence": evidence, "fixed": fixed, "dismissed": False,
    }


def phrase_in(text: str, phrase: str) -> bool:
    return re.search(rf"(?<![\w]){re.escape(phrase)}(?![\w])", text, flags=re.IGNORECASE) is not None


def claim_texts(fields: dict) -> list[tuple[str, str]]:
    """(field path, text) for every place a claim can appear: titles, hook, description, thumbnail words."""
    out = [("title", fields.get("title") or ""), ("hook_line", fields.get("hook_line") or ""),
           ("description", fields.get("description") or "")]
    for i, alt in enumerate(fields.get("title_alternates") or []):
        out.append((f"title_alternates[{i}]", alt.get("text") or ""))
    for i, word in enumerate((fields.get("thumbnail") or {}).get("word_options") or []):
        out.append((f"thumbnail.word_options[{i}]", word))
    return out


def _tags_length(tags: list[str]) -> int:
    # YouTube counts the separators, and a tag with a space as if it were quoted.
    return sum(len(t) + (2 if " " in t else 0) for t in tags) + max(len(tags) - 1, 0)


def check(fields: dict, ctx: RuleContext) -> tuple[dict, list[dict]]:
    fields = copy.deepcopy(fields)
    results: list[dict] = []
    channel = ctx.channel

    # ---- auto-fixes first, so the other rules see the fixed text ----------------
    canonical = ctx.research.get("canonical_name")
    words = re.findall(r"[A-Za-z0-9]+", canonical) if isinstance(canonical, str) else []
    if words:
        # Any spelling of the canonical name (case, spaces, hyphens) becomes the canonical spelling.
        pattern = re.compile(r"(?<![\w])" + r"[\s\-_.]*".join(map(re.escape, words)) + r"(?![\w])", re.IGNORECASE)
        found: list[str] = []

        def fix(text: str) -> str:
            def swap(m: re.Match) -> str:
                if m.group(0) != canonical:
                    found.append(m.group(0))
                return canonical
            return pattern.sub(swap, text)

        for key in ("title", "description", "hook_line"):
            if fields.get(key):
                fields[key] = fix(fields[key])
        for alt in fields.get("title_alternates") or []:
            alt["text"] = fix(alt.get("text") or "")
        results.append(_result("canonical_spelling", "pass", "title",
                               f"Spelling set to “{canonical}”" if found else "Spelling matches research",
                               {"from": sorted(set(found)), "to": canonical} if found else None, fixed=bool(found)))
    else:
        results.append(_result("canonical_spelling", "pass", "title", "No researched spelling to check"))

    want = (channel.hashtags.get(ctx.platform) if channel else None) or 3
    tags_raw = fields.get("hashtags") or []
    hashtags = []
    for tag in tags_raw:
        tag = "#" + re.sub(r"[^\w]", "", str(tag).lstrip("#"))
        if len(tag) > 1 and tag.lower() not in {h.lower() for h in hashtags}:
            hashtags.append(tag)
    fixed = hashtags[:want] != tags_raw
    fields["hashtags"] = hashtags[:want]
    if len(fields["hashtags"]) < want:
        results.append(_result("hashtag_count", "warn", "hashtags",
                               f"{len(fields['hashtags'])} hashtags; the channel uses {want}"))
    else:
        results.append(_result("hashtag_count", "pass", "hashtags", f"{want} hashtags", fixed=fixed))

    banned = {b.lower() for b in ctx.preset.banned_tags}
    tags = []
    removed = []
    for tag in fields.get("tags") or []:
        tag = str(tag).strip().lstrip("#")
        if not tag or tag.lower() in {t.lower() for t in tags}:
            continue
        if tag.lower() in banned:
            removed.append(tag)
            continue
        tags.append(tag)
    fields["tags"] = tags
    results.append(_result("banned_tags", "pass", "tags",
                           f"Removed {', '.join(removed)}" if removed else "No banned tags", removed or None,
                           fixed=bool(removed)))

    # ---- checks ------------------------------------------------------------------
    texts = claim_texts(fields)
    for rule in ctx.preset.claim_rules:
        ok = holds(rule.requires, ctx.facts, ctx.research)
        for path, text in texts:
            found = [p for p in rule.phrases if phrase_in(text, p)]
            if not found:
                continue
            if ok:
                results.append(_result(f"claim_needs_fact.{rule.id}", "pass", path, f"“{found[0]}” is backed",
                                       {"phrase": found[0], "requires": rule.requires.model_dump()}))
            else:
                need = rule.requires.fact or rule.requires.research
                hint = f" Try “{rule.suggest}”." if rule.suggest else ""
                results.append(_result(
                    f"claim_needs_fact.{rule.id}", rule.severity, path,
                    f"“{found[0]}” needs `{need}` {rule.requires.op} {rule.requires.value}, which is not "
                    f"confirmed.{hint}", {"phrase": found[0], "requires": rule.requires.model_dump()},
                ))

    allowed_numbers = {str(int(v)) if isinstance(v, int | float) and float(v).is_integer() else str(v)
                       for v in ctx.facts.values() if isinstance(v, int | float) and not isinstance(v, bool)}
    named = set(re.findall(r"\d+(?:\.\d+)?", f"{ctx.topic} {ctx.subject}"))
    free_words = {w.lower() for w in ctx.preset.thumbnail_words}
    for path, text in texts:
        if path == "description" or (path.startswith("thumbnail") and text.lower() in free_words):
            continue
        stray = [n for n in re.findall(r"\d+(?:\.\d+)?", text) if n not in allowed_numbers and n not in named]
        if stray:
            results.append(_result("number_needs_fact", "warn", path,
                                   f"{', '.join(stray)} does not match a confirmed fact", stray))

    if ctx.topic and channel and channel.strategy_mode == "search_first":
        title = name_key(fields.get("title") or "")
        lead = name_key(f"{ctx.topic} {ctx.subject}")
        topic_first = title.startswith(name_key(ctx.topic)) and name_key(ctx.subject) in title
        if title.startswith(lead) or topic_first:
            results.append(_result("search_first_title", "pass", "title", "Topic and subject lead the title"))
        else:
            results.append(_result("search_first_title", "warn", "title",
                                   "Search-first channel: start the title with the topic and subject"))

    chapters = fields.get("chapter_list") or []
    if not chapters:
        results.append(_result("chapters_valid", "pass", "chapters", "No chapters (the video has too few sections)"))
    else:
        problems = []
        if chapters[0]["t"] != 0:
            problems.append("the first chapter must start at 0:00")
        if len(chapters) < 3:
            problems.append("YouTube needs at least 3 chapters")
        if any(b["t"] - a["t"] < 10 for a, b in pairwise(chapters)):
            problems.append("chapters must be at least 10 s apart")
        results.append(_result("chapters_valid", "block" if problems else "pass", "chapters",
                               "; ".join(problems) or f"{len(chapters)} chapters"))

    target = channel.tags_target if channel else 20
    count = len(fields["tags"])
    results.append(_result("tags_count", "pass" if abs(count - target) <= TAGS_TOLERANCE else "warn", "tags",
                           f"{count} tags (target {target})"))

    subject_key = name_key(ctx.subject)
    matches = [p for p in ctx.past_subjects if subject_key and (
        name_key(p.get("subject") or "") == subject_key or subject_key in name_key(p.get("title") or ""))]
    if not ctx.past_subjects:
        results.append(_result("cannibalization", "pass", "title", "No past uploads recorded"))
    elif matches:
        angles = [m.get("angle") or m.get("title") for m in matches]
        results.append(_result("cannibalization", "warn", "title",
                               "You already have a video on this subject; give this one a distinct angle", angles))
    else:
        results.append(_result("cannibalization", "pass", "title", "No past upload on this subject"))

    for name, limit in LENGTH_LIMITS.get(ctx.platform, {}).items():
        value = fields.get(name)
        size = _tags_length(value) if name == "tags" else len(value or "")
        if size > limit:
            results.append(_result("length_limits", "block", name, f"{size} characters; the limit is {limit}"))

    for r in results:
        r["dismissed"] = r["severity"] == "warn" and r["key"] in ctx.dismissed
    return fields, results


def blocked_fields(results: list[dict]) -> set[str]:
    return {r["field"] for r in results if r["severity"] == "block"}
