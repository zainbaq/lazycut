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
from app.services.search_demand import coverage, tag_key
from app.services.templating import holds

# YouTube long-form limits (checked 2026-11: title 100 characters, description 5,000,
# all tags together 500 characters counting separators).
LENGTH_LIMITS = {
    "youtube": {"title": 100, "description": 5000, "tags": 500, "pinned_comment": 10000},
    # Short-form (looked up 2026-11-16; only third-party pages were found and they disagree on the
    # caption limits, so the lower figure is used: Reels 2,200; TikTok 2,200 of a reported 2,200-4,000).
    "shorts": {"title": 100, "description": 5000},
    "reels": {"caption": 2200},
    "tiktok": {"caption": 2200},
}
# The text a short-form package is posted with, per platform; claims are checked in all of it.
SHORT_TEXT = {"shorts": ("title", "description"), "reels": ("on_screen_text", "caption", "end_text"),
              "tiktok": ("on_screen_text", "caption", "end_text")}
FREE_TEXT = {"description", "caption", "pinned_comment"}  # numbers are not checked in running text
TAGS_TOLERANCE = 5
MIN_CHAPTER_S = 10.0  # YouTube: every chapter, the last one included, is at least 10 s


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
    duration_s: float | None = None  # the video's length, for the last chapter's minimum
    # Search demand (7.7.1): the fitting phrases with their demand, bare names that mean something
    # else, hashtags to use instead of those, and the playlist to suggest when the topic has none.
    phrases: list[dict] | None = None   # None = no search data
    ambiguous: set[str] = field(default_factory=set)
    fallback_hashtags: list[str] = field(default_factory=list)
    missing_playlist: str | None = None
    # Short-form: the clip's platform maximum (duration_s is then the clip's length) and what counts
    # as a reference back to the full video (its link, the playlist, the channel's names).
    clip_limit_s: float | None = None
    link_refs: list[str] = field(default_factory=list)


def _within(hay: str, needle: str) -> bool:
    """Whole-word containment of name keys ("byakue" in "onimusha way of the sword byakue")."""
    return bool(hay) and bool(needle) and f" {needle} " in f" {hay} "


def subject_names(ctx: "RuleContext") -> set[str]:
    """The subject's names as keys: as typed, the canonical name, its comma parts, the real name, nicknames."""
    raw = [ctx.subject, *(str(ctx.research.get(k) or "") for k in ("canonical_name", "real_name"))]
    raw += str(ctx.research.get("nicknames") or "").split(",")
    names = set()
    for name in raw:
        names.add(name_key(name))
        names.update(name_key(part) for part in name.split(",")[:1])  # "Zhuo Bi, the Gatekeeper" -> "Zhuo Bi"
    return {n for n in names if len(n) >= 3}


def repeats(ctx: "RuleContext") -> list[dict]:
    """Past uploads (Shorts excluded upstream) about the same subject in the same game (7.7)."""
    names = subject_names(ctx)
    topic = name_key(ctx.topic)
    out = []
    for p in ctx.past_subjects:
        past_topic = name_key(p.get("topic") or "")
        title = name_key(p.get("title") or "")
        # A past upload with no game recorded may be the same game: it still counts.
        same_game = not topic or not past_topic or _within(past_topic, topic) or _within(topic, past_topic)
        if not same_game:
            continue
        past_subject = name_key(p.get("subject") or "")
        if any(n == past_subject or _within(past_subject, n) or _within(title, n) for n in names):
            out.append(p)
    return out


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


def active_bans(preset: Preset, facts: dict, research: dict) -> list[str]:
    """Banned tags in force: a ban with `unless` lifts when its condition holds."""
    return [b.tag for b in preset.bans() if not (b.unless and holds(b.unless, facts, research))]


def _compact(text: str) -> str:
    return name_key(text).replace(" ", "")


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
    # A hashtag of a bare name that means something else (#SwordFanatic is a manhwa) sends viewers
    # to the wrong page: swap in the preset's fallback hashtag, or drop it.
    ambiguous = {n.replace(" ", "") for n in ctx.ambiguous}
    swapped: list[str] = []
    kept: list[str] = []
    for tag in hashtags:
        if tag[1:].lower() not in ambiguous:
            kept.append(tag)
            continue
        taken = {h.lower() for h in hashtags + kept}
        spare = next((f if f.startswith("#") else "#" + f for f in ctx.fallback_hashtags
                      if (f if f.startswith("#") else "#" + f).lower() not in taken), None)
        swapped.append(f"{tag} → {spare}" if spare else f"{tag} removed")
        if spare:
            kept.append(spare)
    hashtags = kept
    if swapped:
        results.append(_result("ambiguous_names", "pass", "hashtags",
                               f"{'; '.join(swapped)}: the bare name is mostly searched for something else",
                               swapped, fixed=True))
    fixed = hashtags[:want] != tags_raw
    fields["hashtags"] = hashtags[:want]
    if len(fields["hashtags"]) < want:
        results.append(_result("hashtag_count", "warn", "hashtags",
                               f"{len(fields['hashtags'])} hashtags; the channel uses {want}"))
    else:
        results.append(_result("hashtag_count", "pass", "hashtags", f"{want} hashtags", fixed=fixed))

    banned = [_compact(b) for b in active_bans(ctx.preset, ctx.facts, ctx.research) if _compact(b)]
    tags = []
    removed = []
    bare = []
    for tag in fields.get("tags") or []:
        tag = str(tag).strip().lstrip("#")
        if not tag or tag_key(tag) in {tag_key(t) for t in tags}:
            continue
        if any(b in _compact(tag) for b in banned):  # "Soulslike", "souls-like", "phantom blade zero soulslike"
            removed.append(tag)
            continue
        if name_key(tag) in ctx.ambiguous:
            bare.append(tag)
            continue
        tags.append(tag)
    results.append(_result("banned_tags", "pass", "tags",
                           f"Removed {', '.join(removed)}" if removed else "No banned tags", removed or None,
                           fixed=bool(removed)))
    if bare:
        results.append(_result("ambiguous_names", "pass", "tags",
                               f"Removed {', '.join(bare)}: on its own it is mostly searched for something else; "
                               "the tags with the topic name stay", bare, fixed=True))
    # Tags come most important first, so the ones past YouTube's total limit are dropped from the end.
    tag_limit = LENGTH_LIMITS.get(ctx.platform, {}).get("tags")
    dropped = []
    while tag_limit and len(tags) > 1 and _tags_length(tags) > tag_limit:
        dropped.insert(0, tags.pop())
    fields["tags"] = tags
    if dropped:
        results.append(_result("tags_fit", "pass", "tags",
                               f"Dropped {', '.join(dropped)} to fit YouTube's {tag_limit}-character limit",
                               dropped, fixed=True))

    # ---- checks ------------------------------------------------------------------
    results += claim_and_number_results(claim_texts(fields), ctx)
    _later_checks(fields, ctx, results)
    for r in results:
        r["dismissed"] = r["severity"] == "warn" and r["key"] in ctx.dismissed
    return fields, results


def claim_and_number_results(texts: list[tuple[str, str]], ctx: RuleContext) -> list[dict]:
    """Claim phrases need their fact; numbers must match a confirmed fact or the topic/subject name.
    Also used to weigh title candidates before one is picked."""
    results: list[dict] = []
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
        if path in FREE_TEXT or (path.startswith("thumbnail") and text.lower() in free_words):
            continue
        stray = [n for n in re.findall(r"\d+(?:\.\d+)?", text) if n not in allowed_numbers and n not in named]
        if stray:
            results.append(_result("number_needs_fact", "warn", path,
                                   f"{', '.join(stray)} does not match a confirmed fact", stray))
    return results


def _later_checks(fields: dict, ctx: RuleContext, results: list[dict]) -> None:
    channel = ctx.channel

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
        if any(b["t"] - a["t"] < MIN_CHAPTER_S for a, b in pairwise(chapters)):
            problems.append("chapters must be at least 10 s apart")
        if ctx.duration_s and ctx.duration_s - chapters[-1]["t"] < MIN_CHAPTER_S:
            problems.append("the last chapter must be at least 10 s long")
        results.append(_result("chapters_valid", "block" if problems else "pass", "chapters",
                               "; ".join(problems) or f"{len(chapters)} chapters"))

    target = channel.tags_target if channel else 20
    count = len(fields["tags"])
    results.append(_result("tags_count", "pass" if abs(count - target) <= TAGS_TOLERANCE else "warn", "tags",
                           f"{count} tags (target {target})"))

    matches = repeats(ctx)
    if not ctx.past_subjects:
        results.append(_result("cannibalization", "pass", "title", "No past uploads recorded"))
    elif matches:
        angles = [m.get("angle") or m.get("title") for m in matches]
        results.append(_result("cannibalization", "warn", "title",
                               "You already have a video on this subject; give this one a distinct angle", angles))
    else:
        results.append(_result("cannibalization", "pass", "title", "No past upload on this subject"))

    _search_demand(fields, ctx, results)

    if ctx.missing_playlist:
        results.append(_result("playlist", "warn", "description",
                               f"No playlist for {ctx.topic} yet, so the description has no playlist link. Create "
                               f"“{ctx.missing_playlist}” and list it under playlists in config/channel.yaml"))

    for name, limit in LENGTH_LIMITS.get(ctx.platform, {}).items():
        value = fields.get(name)
        size = _tags_length(value) if name == "tags" else len(value or "")
        if size > limit:
            results.append(_result("length_limits", "block", name, f"{size} characters; the limit is {limit}"))
    title_limit = LENGTH_LIMITS.get(ctx.platform, {}).get("title")
    for i, alt in enumerate(fields.get("title_alternates") or []):
        size = len(alt.get("text") or "")
        if title_limit and size > title_limit:
            results.append(_result("length_limits", "warn", f"title_alternates[{i}]",
                                   f"{size} characters; too long to use as the title (limit {title_limit})"))


TOP_PHRASES = 3
LEAD_CHARS = 150  # what search results show of a description


def _search_demand(fields: dict, ctx: RuleContext, results: list[dict]) -> None:
    """The title and the description's opening should carry at least one of the most popular
    search phrases that fit the video. Mostly matters after a manual edit: generation picks the
    best-scoring title already."""
    if ctx.phrases is None:
        results.append(_result("search_demand", "pass", "title", "No search data; the writer's choices stand"))
        return
    top = sorted((p for p in ctx.phrases if p.get("fits")), key=lambda p: -p["demand"])[:TOP_PHRASES]
    if not top:
        results.append(_result("search_demand", "pass", "title", "No search phrase fits this video"))
        return
    names = ", ".join(f"“{p['text']}”" for p in top)
    for field_name, text in (("title", fields.get("title") or ""),
                             ("description", (fields.get("description") or "")[:LEAD_CHARS])):
        covered = [p["text"] for p in top if coverage(text, p["text"])[0]]
        where, s = ("The title", "es") if field_name == "title" else ("The description's first lines", "")
        if covered:
            results.append(_result("search_demand", "pass", field_name,
                                   f"{where} cover{'s' if s else ''} “{covered[0]}”", covered))
        else:
            results.append(_result("search_demand", "warn", field_name,
                                   f"{where} miss{s} every top search for this video: {names}",
                                   [p["text"] for p in top]))


def check_short(fields: dict, ctx: RuleContext) -> tuple[dict, list[dict]]:
    """The rules for one short-form package (Shorts, Reels or TikTok): spelling and hashtags are
    fixed, then claims, numbers, the link back to the full video, the lengths and the clip itself."""
    fields = copy.deepcopy(fields)
    results: list[dict] = []
    channel = ctx.channel
    texts = [name for name in SHORT_TEXT.get(ctx.platform, ()) if name in fields]
    body = "description" if ctx.platform == "shorts" else "caption"
    name = {"shorts": "Shorts", "reels": "Reels", "tiktok": "TikTok"}.get(ctx.platform, ctx.platform)

    canonical = ctx.research.get("canonical_name")
    words = re.findall(r"[A-Za-z0-9]+", canonical) if isinstance(canonical, str) else []
    if words:
        pattern = re.compile(r"(?<![\w#])" + r"[\s\-_.]*".join(map(re.escape, words)) + r"(?![\w])", re.IGNORECASE)
        found: list[str] = []

        def swap(m: re.Match) -> str:
            if m.group(0) != canonical:
                found.append(m.group(0))
            return canonical

        for key in texts:
            fields[key] = pattern.sub(swap, fields.get(key) or "")
        if found:
            results.append(_result("canonical_spelling", "pass", texts[0], f"Spelling set to “{canonical}”",
                                   {"from": sorted(set(found)), "to": canonical}, fixed=True))

    # Hashtags: the platform's count, #Shorts where it is required, no bare ambiguous names. The
    # line of hashtags inside the description or caption follows whatever changes here.
    want = (channel.hashtags.get(ctx.platform) if channel else None) or 5
    required = (channel.shorts_required_hashtag if channel else "#Shorts") if ctx.platform == "shorts" else None
    before = list(fields.get("hashtags") or [])
    tags: list[str] = []
    for tag in ([required] if required else []) + before:
        tag = "#" + re.sub(r"[^\w]", "", str(tag).lstrip("#"))
        if len(tag) > 1 and tag.lower() not in {h.lower() for h in tags}:
            tags.append(tag)
    ambiguous = {n.replace(" ", "") for n in ctx.ambiguous}
    kept: list[str] = []
    swapped: list[str] = []
    for tag in tags:
        if tag[1:].lower() not in ambiguous:
            kept.append(tag)
            continue
        taken = {h.lower() for h in tags + kept}
        spare = next((f if f.startswith("#") else "#" + f for f in ctx.fallback_hashtags
                      if (f if f.startswith("#") else "#" + f).lower() not in taken), None)
        swapped.append(f"{tag} → {spare}" if spare else f"{tag} removed")
        if spare:
            kept.append(spare)
    kept = kept[:want]
    fields["hashtags"] = kept
    in_text = fields.get("hashtags_text")
    if in_text is None:
        in_text = " ".join(before)
    now = " ".join(kept)
    if in_text and in_text != now and in_text in (fields.get(body) or ""):
        fields[body] = fields[body].replace(in_text, now)
    fields["hashtags_text"] = now
    if swapped:
        results.append(_result("ambiguous_names", "pass", "hashtags",
                               f"{'; '.join(swapped)}: the bare name is mostly searched for something else",
                               swapped, fixed=True))
    added = bool(required) and required.lower() not in {str(t).lower() for t in before}
    if len(kept) < want:
        results.append(_result("hashtag_count", "warn", "hashtags", f"{len(kept)} hashtags; the channel uses {want} on {name}"))
    else:
        results.append(_result("hashtag_count", "pass", "hashtags",
                               f"{want} hashtags" + (f", {required} added" if added else ""), fixed=kept != before))

    results += claim_and_number_results(
        [(key, fields.get(key) or "") for key in texts] + [("pinned_comment", fields.get("pinned_comment") or "")], ctx)

    text = (fields.get(body) or "").lower()
    refs = [r for r in ctx.link_refs if r and r.lower() in text]
    if refs:
        results.append(_result("link_back", "pass", body, f"Points back to the full video ({refs[0]})"))
    else:
        why = (f" (the template's playlist line was left out: {ctx.topic} has no playlist in config/channel.yaml)"
               if ctx.missing_playlist else "")
        results.append(_result("link_back", "warn" if ctx.platform == "tiktok" else "block", body,
                               "Nothing points back to the full video: add its link, the playlist or the channel "
                               f"name{why}"))

    for key, limit in LENGTH_LIMITS.get(ctx.platform, {}).items():
        size = len(fields.get(key) or "")
        if size > limit:
            results.append(_result("length_limits", "block", key, f"{size} characters; the {name} limit is {limit}"))

    if ctx.clip_limit_s and ctx.duration_s and ctx.duration_s > ctx.clip_limit_s + 1e-6:
        results.append(_result("clip_length", "warn", "clip",
                               f"The clip is {ctx.duration_s:.1f} s; {name} takes up to {ctx.clip_limit_s:g} s"))
    else:
        results.append(_result("clip_length", "pass", "clip", f"The clip fits {name}"))

    for r in results:
        r["dismissed"] = r["severity"] == "warn" and r["key"] in ctx.dismissed
    return fields, results


def blocked_fields(results: list[dict]) -> set[str]:
    return {r["field"] for r in results if r["severity"] == "block"}
