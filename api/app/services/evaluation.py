"""Score an analysis against hand-labelled ground truth (Phase 0, and whenever the prompt changes)."""

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator
from ruamel.yaml import YAML

from app.services.timecode import parse_time


class TruthEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    t: float
    type: str

    @field_validator("t", mode="before")
    @classmethod
    def _clock(cls, value: object) -> float:
        return parse_time(value)


class Truth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video: str  # path inside the import folder
    preset: str = "general"
    kind: Literal["long", "clip"] = "long"
    topic: str = ""
    subject: str = ""
    topic_terms: str = ""
    events: list[TruthEvent] = []  # timed events, when the owner has them
    counts: dict[str, int] = {}  # per-type totals, when only a hand count exists
    facts: dict[str, Any] = {}  # expected fact values

    def timed_counts(self) -> dict[str, int]:
        totals: dict[str, int] = {}
        for event in self.events:
            totals[event.type] = totals.get(event.type, 0) + 1
        return totals

    def true_counts(self) -> dict[str, int]:
        """Per-type totals. Timed events win; `counts` covers the types that have none."""
        return {**self.counts, **self.timed_counts()}

    def problems(self, derived_facts: dict[str, str] | None = None) -> list[str]:
        """Contradictions inside the labels. `derived_facts` maps a fact key to its event type."""
        timed = self.timed_counts()
        found = [
            f"counts.{kind} is {n}, but {timed[kind]} timed `{kind}` event(s) are listed"
            for kind, n in self.counts.items()
            if kind in timed and timed[kind] != n
        ]
        totals = self.true_counts()
        for key, kind in (derived_facts or {}).items():
            expected = self.facts.get(key)
            if isinstance(expected, int) and not isinstance(expected, bool) and kind in totals and expected != totals[kind]:
                found.append(f"facts.{key} is {expected}, but the labels give {totals[kind]} `{kind}` event(s)")
        return found


def load_truth(path: Path) -> Truth:
    return Truth.model_validate(YAML(typ="safe").load(path.read_text(encoding="utf-8")))


def match_events(truth: list[float], found: list[float], tolerance_s: float) -> list[tuple[int, int, float]]:
    """Greedy one-to-one matching, closest pairs first. Returns (truth index, found index, error)."""
    pairs = sorted(
        (abs(f - t), i, j)
        for i, t in enumerate(truth)
        for j, f in enumerate(found)
        if abs(f - t) <= tolerance_s
    )
    used_truth: set[int] = set()
    used_found: set[int] = set()
    matches: list[tuple[int, int, float]] = []
    for error, i, j in pairs:
        if i not in used_truth and j not in used_found:
            used_truth.add(i)
            used_found.add(j)
            matches.append((i, j, error))
    return matches


def score_events(truth: Truth, found: list[tuple[float, str]], tolerance_s: float = 0.5) -> dict:
    """Recall, precision and timing error per event type and overall.

    Only event types the truth file mentions are scored, so types the owner did
    not label (for example boss moves) cannot count as false positives.
    """
    true_counts = truth.true_counts()
    timed: dict[str, list[float]] = {}
    for event in truth.events:
        timed.setdefault(event.type, []).append(event.t)
    found_by_type: dict[str, list[float]] = {}
    for t, kind in found:
        found_by_type.setdefault(kind, []).append(t)

    per_type: dict[str, dict] = {}
    total_true = total_found = total_matched = 0
    errors: list[float] = []
    for kind in sorted(true_counts):
        found_times = sorted(found_by_type.get(kind, []))
        row: dict[str, Any] = {
            "true": true_counts[kind],
            "found": len(found_times),
            "count_diff": len(found_times) - true_counts[kind],
        }
        truth_times = sorted(timed.get(kind, []))
        # Timing can only be scored when every true event of this type has a timestamp.
        if truth_times and len(truth_times) == true_counts[kind]:
            matches = match_events(truth_times, found_times, tolerance_s)
            type_errors = [e for _, _, e in matches]
            row |= {
                "matched": len(matches),
                "recall": round(len(matches) / len(truth_times), 3),
                "precision": round(len(matches) / len(found_times), 3) if found_times else None,
                "mean_error_s": round(sum(type_errors) / len(type_errors), 3) if type_errors else None,
            }
            total_true += len(truth_times)
            total_found += len(found_times)
            total_matched += len(matches)
            errors += type_errors
        per_type[kind] = row

    overall: dict[str, Any] = {"tolerance_s": tolerance_s, "timed_true": total_true}
    if total_true:
        overall |= {
            "found": total_found,
            "matched": total_matched,
            "recall": round(total_matched / total_true, 3),
            "precision": round(total_matched / total_found, 3) if total_found else None,
            "mean_error_s": round(sum(errors) / len(errors), 3) if errors else None,
        }
    return {"overall": overall, "per_type": per_type}


def _same(expected: Any, proposed: str) -> bool:
    text = str(proposed).strip().lower()
    if isinstance(expected, bool):
        return text in ({"true", "yes", "1"} if expected else {"false", "no", "0"})
    if isinstance(expected, (int, float)):
        try:
            return float(text.split()[0]) == float(expected)
        except (ValueError, IndexError):
            return False
    return text == str(expected).strip().lower()


def score_facts(truth: Truth, proposals: dict[str, str]) -> dict:
    rows = {
        key: {"expected": expected, "proposed": proposals.get(key), "ok": key in proposals and _same(expected, proposals[key])}
        for key, expected in truth.facts.items()
    }
    return {"correct": sum(r["ok"] for r in rows.values()), "total": len(rows), "facts": rows}
