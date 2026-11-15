"""Timestamp parsing and formatting shared by analysis, evaluation and the UI payloads."""


def parse_time(value: object) -> float:
    """Return seconds from a number, `12.5`, `12.5s`, `M:SS`, `M:SS.s` or `H:MM:SS.s`."""
    if isinstance(value, bool):
        # Every bad timestamp is a ValueError, so callers catch one type.
        raise ValueError(f"not a timestamp: {value!r}")  # noqa: TRY004
    if isinstance(value, (int, float)):
        seconds = float(value)
    else:
        text = str(value).strip().lower().removesuffix("s").strip()
        if not text:
            raise ValueError("empty timestamp")
        parts = text.split(":")
        if len(parts) > 3:
            raise ValueError(f"not a timestamp: {value!r}")
        try:
            seconds = 0.0
            for part in parts:
                seconds = seconds * 60 + float(part)
        except ValueError as exc:
            raise ValueError(f"not a timestamp: {value!r}") from exc
    if seconds < 0:
        raise ValueError(f"negative timestamp: {value!r}")
    return seconds


def format_clock(seconds: float, decimals: int = 1) -> str:
    """Format seconds as `M:SS.s` (or `H:MM:SS.s` from one hour up)."""
    seconds = max(0.0, round(seconds, decimals))
    whole = int(seconds)
    frac = seconds - whole
    hours, rem = divmod(whole, 3600)
    minutes, secs = divmod(rem, 60)
    tail = f"{secs + frac:0{3 + decimals if decimals else 2}.{decimals}f}"
    if hours:
        return f"{hours}:{minutes:02d}:{tail}"
    return f"{minutes}:{tail}"
