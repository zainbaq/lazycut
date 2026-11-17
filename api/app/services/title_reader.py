"""Read a past upload's title into topic, subject and angle, with no model call.

Titles on one channel drift through many layouts ("Game - Boss Boss Fight (angle)", "Boss - Game
Bossfight", "Boss (angle) - Game", "Boss || Game"). Rather than a pattern per layout, the reader
uses the channel's own titles as evidence: the title is cut at its separators, and the piece that
names one of the channel's playlists, or recurs across many of its titles, is the game; the rest is
the subject. Brackets, a `|` tail and the preset's claim phrases ("No Damage") are the angle.
Measured on the owner's channel before it went in (BUILD_SPEC 7.14).
"""

import re
from dataclasses import dataclass

# "Boss Fight", "Bossfight", "Final Bossfight", "DLC Bossfight", "FINAL BOSS Fight".
BOSS_WORDS = re.compile(r"\s*\b(?:(?:final|dlc|enhanced|optional)\s+)*boss\s*fight\b\s*", re.IGNORECASE)
SEPARATOR = re.compile(r"\s+(\|\||\||-|–|—)\s+")
BRACKETS = re.compile(r"\s*\(([^()]*)\)")
HASHTAG = re.compile(r"(?:^|\s)#\w+")


def norm(text: str) -> str:
    """Lower-case words only, so "Black Myth: Wukong" and "Black Myth - Wukong" are the same phrase."""
    text = re.sub(r"bossfight", "boss fight", text.lower())
    return " ".join(re.findall(r"[a-z0-9À-ɏ]+", text))


def _tidy(text: str) -> str:
    return re.sub(r"\s{2,}", " ", BOSS_WORDS.sub(" ", text)).strip(" ,:-")


def _contains(hay: str, needle: str) -> bool:
    return bool(needle) and f" {needle} " in f" {hay} "


@dataclass
class Reading:
    topic: str = ""
    subject: str = ""
    angle: str = ""
    # How the topic was found: "playlist" (a known topic), "repeated" (recurs across titles), or "" (not read).
    by: str = ""


@dataclass
class _Piece:
    text: str
    tail: bool  # came after a `|` or `||`


class TitleReader:
    """Built once per import from every title on the channel, the known topics and the preset's claim phrases."""

    def __init__(self, titles: list[str], known_topics: list[str], angle_phrases: list[str] = ()):
        self.titles = [norm(t) for t in titles]
        self.known = {norm(k) for k in known_topics if norm(k)}
        self.angle_phrases = sorted({p for p in angle_phrases if p.strip()}, key=len, reverse=True)

    def df(self, phrase: str) -> int:
        """In how many of the channel's titles a phrase appears (document frequency)."""
        n = norm(phrase)
        return sum(_contains(t, n) for t in self.titles) if n else 0

    def _topic_in(self, piece: str) -> tuple[int, int, bool] | None:
        """Where a game name sits in `piece`, as (first word, end word, known), longest known name first.

        A known name may run on past a colon into a recurring subtitle ("Elden Ring: Shadow of the
        Erdtree"); a repeated phrase (two words or more, in 2+ titles) is accepted only at the start.
        """
        words = piece.split()
        normed = [norm(w) for w in words]
        best: tuple[int, int, bool] | None = None
        for start in range(len(words)):
            for end in range(len(words), start, -1):
                n = " ".join(w for w in normed[start:end] if w)
                if n in self.known and (best is None or end - start > best[1] - best[0]):
                    best = (start, end, True)
                    break
        if best:
            start, end, _ = best
            # Run on over a recurring subtitle: "Elden Ring:" + "Shadow of the Erdtree".
            if words[end - 1].endswith(":"):
                for stop in range(len(words), end, -1):
                    if self.df(" ".join(words[start:stop])) >= 2:
                        return (start, stop, True)
            return best
        for end in range(len(words), 1, -1):
            head = " ".join(words[:end])
            if len(norm(head).split()) >= 2 and self.df(head) >= 2:
                return (0, end, False)
        return None

    def _angle_out(self, subject: str) -> tuple[str, list[str]]:
        """Move claim phrases ("No Damage", "Final Boss") out of the subject into the angle."""
        found = []
        for phrase in self.angle_phrases:
            pattern = re.compile(rf"\b{re.escape(phrase)}\b", re.IGNORECASE)
            if pattern.search(subject):
                found.append(phrase)
                subject = pattern.sub(" ", subject)
        return _tidy(subject), found

    def read(self, title: str) -> Reading:
        text = HASHTAG.sub("", title).strip()
        angles = [a.strip() for a in BRACKETS.findall(text) if a.strip()]
        bare = BRACKETS.sub("", text).strip()
        parts = SEPARATOR.split(bare)
        pieces = [_Piece(parts[0].strip(), False)]
        for sep, chunk in zip(parts[1::2], parts[2::2], strict=True):
            pieces.append(_Piece(chunk.strip(), sep in ("|", "||")))
        pieces = [p for p in pieces if p.text]
        if not pieces:
            return Reading()

        # The piece that holds the game: a known name beats a repeated phrase, then the more common one.
        found = []
        for i, piece in enumerate(pieces):
            hit = self._topic_in(piece.text)
            if hit:
                start, end, known = hit
                topic = " ".join(piece.text.split()[start:end])
                found.append((known, self.df(topic), -i, i, start, end))
        if not found:
            subject, claims = self._angle_out(pieces[0].text)
            tails = [p.text for p in pieces[1:]]
            return Reading(subject=subject, angle=" · ".join(angles + claims + tails))

        known, _df, _, at, start, end = max(found)
        words = pieces[at].text.split()
        others = [p for j, p in enumerate(pieces) if j != at]
        if start == 0 and end < len(words):
            if known and any(not p.tail for p in others):
                end = len(words)  # "Elden Ring Nightreign - Boss": with the subject elsewhere, the whole piece is the game
            elif colon := next((k for k in range(end, len(words) - 1) if words[k].endswith(":")), None):
                end = colon + 1  # "God of War Ragnarök Valhalla: Fraekni": the subtitle before the colon is the game's
        if start > 0 and end < len(words):
            end = len(words)  # "Rellana in Elden Ring: Shadows of the Erdtree": the rest belongs to the game
        topic = _tidy(" ".join(words[start:end]))
        before, after = _tidy(" ".join(words[:start]).removesuffix(" in")), _tidy(" ".join(words[end:]))
        inline = " ".join(x for x in (before, after) if x)
        if inline:
            subject, tails = inline, [p.text for p in others]  # "Game Boss Boss Fight | tail", "Boss in Game"
        else:
            body = [p.text for p in others if not p.tail]
            tails = [p.text for p in others if p.tail]
            if not body and tails:
                body, tails = tails[:1], tails[1:]  # "Boss || Game": the only other piece is the subject
            subject = " - ".join(_tidy(b) for b in body)
        subject, claims = self._angle_out(subject)
        return Reading(topic=topic, subject=subject, angle=" · ".join(angles + claims + tails), by="playlist" if known else "repeated")
