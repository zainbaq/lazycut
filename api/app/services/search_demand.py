"""Search demand (BUILD_SPEC 7.7.1): what people actually type on YouTube, so the package is
chosen by measured demand instead of the writer's guess.

The source is YouTube's search suggestions: free, no key, ordered by popularity. It is an
unofficial endpoint, so every failure is soft: the package falls back to the writer's choices
and says there is no search data. A suggestion's rank is a demand signal, not a view count.

Only the topic and subject names are sent.
"""

import asyncio
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlmodel import Session, select

from app.models import Research, utc_now
from app.services.research import name_key

SOURCE = "youtube_suggest"
SUGGEST_URL = "https://suggestqueries.google.com/complete/search?client=firefox&ds=yt&hl=en&gl=US&q="
MAX_NAMES = 5
MAX_REQUESTS = 40
MAX_PHRASES = 40
AMBIGUOUS_SHARE = 0.3   # a bare name is ambiguous when under 30% of its suggestions mention the topic
AMBIGUOUS_MIN = 3       # ... and it has at least this many suggestions (a unique name has few)
FRONT_CHARS = 60        # search and mobile cut titles near here
_STOP = {"the", "a", "an", "of", "in", "on", "and", "vs"}


class SuggestClient(Protocol):
    async def suggest(self, query: str) -> list[str]: ...


class YouTubeSuggest:
    """The live client. Requests are spaced out so the harvest stays polite."""

    def __init__(self, pause_s: float = 0.15, timeout_s: float = 8.0):
        self.pause_s, self.timeout_s = pause_s, timeout_s

    def _get(self, query: str) -> list[str]:
        req = urllib.request.Request(SUGGEST_URL + urllib.parse.quote(query), headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        return [str(x) for x in data[1]] if isinstance(data, list) and len(data) > 1 else []

    async def suggest(self, query: str) -> list[str]:
        out = await asyncio.to_thread(self._get, query)
        await asyncio.sleep(self.pause_s)
        return out


# ---- names and seeds --------------------------------------------------------------


def subject_names(subject: str, research: dict[str, Any], before: str | None = None) -> list[str]:
    """The names people may search the subject by: the subject, its canonical name and its parts
    ("Hua Qianxiao, the Sword Fanatic" → "hua qianxiao", "sword fanatic"), real name, epithet, nicknames."""
    raw = [subject, research.get("canonical_name"), research.get("real_name"), research.get("epithet"), before]
    raw += re.split(r"[,;/]| or ", research.get("nicknames") or "")
    names: list[str] = []
    for value in raw:
        if not isinstance(value, str):
            continue
        for part in [value, *value.split(",")]:
            key = re.sub(r"^(the|a|an) ", "", name_key(part))
            if len(key) > 2 and key not in names:
                names.append(key)
    # Names of up to three words first: people rarely type the long "x, the y" form.
    order = {n: i for i, n in enumerate(names)}
    return sorted(names, key=lambda n: (len(n.split()) > 3, order[n]))[:MAX_NAMES]


def seed_queries(topic: str, names: list[str], templates: list[str]) -> list[str]:
    topic = name_key(topic)
    seeds = [topic] if topic else []
    for name in names:
        seeds += [f"{topic} {name}".strip(), f"{topic} {name} ".lstrip(), name]
    for template in templates:
        if "{name}" in template:
            seeds += [name_key(template.format(topic=topic, name=n)) for n in names]
        else:
            seeds.append(name_key(template.format(topic=topic, name="")))
    out: list[str] = []
    for seed in seeds:
        if seed.strip() and seed not in out:
            out.append(seed)
    return out[:MAX_REQUESTS]


async def harvest(client: SuggestClient, topic: str, names: list[str], templates: list[str]) -> dict:
    """Ask for suggestions on every seed and keep each phrase's best rank and how often it came back."""
    phrases: dict[str, dict] = {}
    bare: dict[str, dict] = {}
    errors = 0
    seeds = seed_queries(topic, names, templates)
    topic_key = name_key(topic)
    for seed in seeds:
        try:
            got = await client.suggest(seed)
        except Exception:  # noqa: BLE001 - an unofficial endpoint; any failure is soft
            errors += 1
            continue
        if seed in names:
            bare[seed] = {"total": len(got), "about_topic": sum(topic_key in name_key(g) for g in got) if topic_key else 0,
                          "sample": got[:3]}
        for rank, text in enumerate(got):
            key = name_key(text)
            entry = phrases.setdefault(key, {"text": key, "rank": rank, "seen": 0})
            entry["rank"] = min(entry["rank"], rank)
            entry["seen"] += 1
    return {"source": SOURCE, "harvested_at": utc_now(), "topic": topic_key, "names": names, "seeds": len(seeds),
            "errors": errors, "bare": bare, "phrases": sorted(phrases.values(), key=lambda p: (p["rank"], -p["seen"]))}


# ---- reading the harvest ----------------------------------------------------------


def demand(entry: dict) -> float:
    """1.0 for a top suggestion down to 0.1 for the tenth, plus a little for each extra seed that found it."""
    return round(max(0.1, 1 - entry["rank"] / 10) + 0.05 * min(entry["seen"] - 1, 4), 3)


def ambiguous_names(payload: dict | None) -> set[str]:
    """Bare names whose suggestions are mostly about something else (a manhwa, a song, another game)."""
    out = set()
    for name, b in ((payload or {}).get("bare") or {}).items():
        if b["total"] >= AMBIGUOUS_MIN and b["about_topic"] / b["total"] < AMBIGUOUS_SHARE:
            out.add(name)
    return out


def _tokens(text: str) -> list[str]:
    return [t for t in name_key(text).split() if t not in _STOP]


def candidate_phrases(payload: dict | None, topic: str, topic_terms: str = "") -> list[dict]:
    """Phrases anchored to this video: they name the topic, or a subject name that is not ambiguous.
    "drunk boss manga" (an ambiguous name, no topic) and "sekiro how to beat drunk boss" are left out."""
    if not payload:
        return []
    anchors = [name_key(topic)] + [name_key(t) for t in re.split(r"[,;]", topic_terms or "") if t.strip()]
    anchors = [a for a in anchors if a]
    unambiguous = [n for n in payload.get("names") or [] if n not in ambiguous_names(payload)]
    out = []
    for entry in payload.get("phrases") or []:
        text = entry["text"]
        names_in = [n for n in payload.get("names") or [] if _contains(text, n)]
        has_topic = any(_contains(text, a) for a in anchors)
        if has_topic or any(n in unambiguous for n in names_in):
            out.append({"text": text, "rank": entry["rank"], "seen": entry["seen"], "demand": demand(entry),
                        "about_subject": bool(names_in)})
    out.sort(key=lambda p: -p["demand"])
    return [p | {"id": f"p{i + 1}"} for i, p in enumerate(out[:MAX_PHRASES])]


def _contains(text: str, phrase: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(name_key(phrase))}(?![a-z0-9])", name_key(text)) is not None


def coverage(title: str, phrase: str) -> tuple[float, bool]:
    """1.0 when the phrase's words appear in order in the title, 0.6 when all appear in any order;
    and whether the match ends within the first 60 characters."""
    words = _tokens(title)
    want = _tokens(phrase)
    if not want:
        return 0.0, False
    for i in range(len(words) - len(want) + 1):
        if words[i:i + len(want)] == want:
            return 1.0, _ends_before(title, want[-1], FRONT_CHARS)
    if set(want) <= set(words):
        return 0.6, _ends_before(title, want[-1], FRONT_CHARS)
    return 0.0, False


def _ends_before(title: str, last_word: str, limit: int) -> bool:
    m = re.search(rf"(?i)(?<![a-z0-9]){re.escape(last_word)}(?![a-z0-9])", title)
    return bool(m) and m.end() <= limit


@dataclass
class TitleScore:
    score: float
    covers: list[dict]


LONG_TITLE = 70     # phones cut titles near here
REPEAT_PENALTY = 0.85


def score_title(title: str, phrases: list[dict]) -> TitleScore:
    """Sum of demand over the fitting phrases the title covers; a match past 60 characters counts 70%.
    Stuffing does not pay: each repeated word costs 15%, and every character past 70 costs 2%
    (down to half), since the title truncates on phones."""
    total, covers = 0.0, []
    for p in phrases:
        if not p.get("fits"):
            continue
        cov, front = coverage(title, p["text"])
        if cov:
            gain = p["demand"] * cov * (1.0 if front else 0.7)
            total += gain
            covers.append({"text": p["text"], "demand": p["demand"], "match": "exact" if cov == 1 else "words",
                           "front": front})
    words = _tokens(title)
    repeats = len(words) - len(set(words))
    total *= REPEAT_PENALTY ** repeats
    if len(title) > LONG_TITLE:
        total *= max(0.5, 1 - (len(title) - LONG_TITLE) * 0.02)
    return TitleScore(round(total, 3), covers)


def tag_key(tag: str) -> str:
    """Tags that differ only by small words ("the", "a") are the same tag."""
    return " ".join(_tokens(tag))


def hashtag_name(tag: str) -> str:
    return re.sub(r"[^a-z0-9]", "", tag.lower())


# ---- storage: one row per subject, next to its research ---------------------------

DEMAND = "search_demand"
FRESH_DAYS = 7


def find_row(s: Session, subject_row: Research) -> Research | None:
    return s.exec(select(Research).where(Research.kind == DEMAND, Research.subject_key == subject_row.subject_key,
                                         Research.topic_key == subject_row.topic_key)).first()


def save(s: Session, subject_row: Research, payload: dict) -> Research:
    row = find_row(s, subject_row) or Research(kind=DEMAND, subject_key=subject_row.subject_key,
                                               topic_key=subject_row.topic_key, payload={})
    row.payload = payload
    s.add(row)
    return row


def is_fresh(payload: dict | None, days: int = FRESH_DAYS) -> bool:
    if not payload or not payload.get("phrases"):
        return False
    try:
        when = datetime.fromisoformat(payload["harvested_at"])
    except (KeyError, ValueError):
        return False
    return datetime.now(UTC) - when < timedelta(days=days)
