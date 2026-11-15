"""Conditions and template variables (BUILD_SPEC 5.1, 7.8). Pure functions, no LLM."""

import re
from typing import Any

from app.services.presets import Condition

VARIABLE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_SEPARATORS = r"[-–—:|·]"


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def holds(cond: Condition, facts: dict[str, Any], research: dict[str, Any]) -> bool:
    """A condition over confirmed facts (only confirmed ones are passed in) or effective research values."""
    value = facts.get(cond.fact) if cond.fact is not None else research.get(cond.research or "")
    if value is None:
        return False
    op, target = cond.op, cond.value
    if op in ("eq", "ne"):
        same = value == target
        if not same and _num(value) is not None and _num(target) is not None:
            same = _num(value) == _num(target)
        if not same and isinstance(value, str) and isinstance(target, str):
            same = value.strip().lower() == target.strip().lower()
        return same if op == "eq" else not same
    if op == "in":
        return any(holds(Condition(fact=cond.fact, research=cond.research, op="eq", value=t), facts, research)
                   for t in target)
    number = _num(value)
    if number is None:
        return False
    if op == "between":
        low, high = _num(target[0]), _num(target[1])
        return low is not None and high is not None and low <= number <= high
    limit = _num(target)
    if limit is None:
        return False
    return {"gt": number > limit, "gte": number >= limit, "lt": number < limit, "lte": number <= limit}[op]


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def fill(text: str, values: dict[str, Any]) -> str:
    """Replace every `{name}`; unknown or empty names become empty strings."""
    return VARIABLE.sub(lambda m: as_text(values.get(m.group(1))), text)


def render_title(pattern: str, values: dict[str, Any]) -> str:
    """A one-line pattern. An empty variable goes with its adjoining separator or brackets (7.8)."""
    text = pattern
    for name in set(VARIABLE.findall(pattern)):
        if as_text(values.get(name)):
            continue
        token = re.escape("{" + name + "}")
        text = re.sub(rf"\s*\(\s*{token}\s*\)", "", text)
        text = re.sub(rf"\s*{_SEPARATORS}\s*{token}", "", text)
        text = re.sub(rf"{token}\s*{_SEPARATORS}\s*", "", text)
        text = re.sub(token, "", text)
    text = fill(text, values)
    text = re.sub(r"\(\s*\)", "", text)
    return re.sub(r"\s{2,}", " ", text).strip(" -–—:|·")


def _is_heading(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and stripped.upper() == stripped and any(c.isalpha() for c in stripped) \
        and not VARIABLE.search(stripped) and len(stripped) <= 40


def render_block(template: str, values: dict[str, Any]) -> str:
    """A multi-line template. A line whose variable is empty is dropped, and so is a heading
    left with nothing under it (7.8). Runs of blank lines collapse to one."""
    lines = template.splitlines()
    rendered: list[str | None] = []  # None = dropped
    for line in lines:
        names = VARIABLE.findall(line)
        empty = names and any(not as_text(values.get(n)) for n in names)
        rendered.append(None if empty else fill(line, values).rstrip())
    out: list[str] = []
    for i, line in enumerate(rendered):
        if line is None:
            continue
        if _is_heading(line):
            # A heading stays only if the line right under it survived and has content.
            below = rendered[i + 1] if i + 1 < len(rendered) else None
            if not below or not below.strip():
                continue
        out.append(line)
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def clock(seconds: float) -> str:
    total = int(seconds)
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
