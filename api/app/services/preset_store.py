"""Write presets back to YAML (5): create, update, delete, with the owner's comments kept.

An update arrives as a whole preset (what the form edits). It is validated first, then merged into
the file's round-trip tree node by node, so unchanged parts keep their comments, quoting, flow style
and order, and only what changed is rewritten. A value the file spells out that equals the default
stays as written; a field reset to its default is dropped from the file.
"""

import difflib
import io
import os
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import (
    DoubleQuotedScalarString,
    FoldedScalarString,
    LiteralScalarString,
    SingleQuotedScalarString,
)

from app.services.presets import Preset, load_presets

PRESET_ID = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
# List items are matched by these keys, so editing one item never disturbs its neighbours' comments.
ITEM_KEYS = ("id", "key", "tag")


class PresetProblem(ValueError):
    """A preset that cannot be saved; `problems` holds one {path, message} per issue."""

    def __init__(self, problems: list[dict[str, str]], status: int = 422):
        self.problems = problems
        self.status = status
        super().__init__("; ".join(p["message"] if not p["path"] else f"{p['path']}: {p['message']}" for p in problems))


def _yaml() -> YAML:
    y = YAML()  # round-trip
    y.preserve_quotes = True
    y.width = 4096  # never re-wrap the owner's long lines
    y.indent(mapping=2, sequence=4, offset=2)
    return y


# The cross-check (presets.Preset._cross_check) reports at the root; its messages name their place.
_PLACES = [
    (re.compile(r"^(templates\.\w+|title_patterns\.\w+|credit_lines|playlist_name|clip_rules\.end_on|credit_fields)"), None),
    (re.compile(r"^event type ids"), "event_types"),
    (re.compile(r"^(enum )?fact `"), "facts"),
    (re.compile(r"^hook `"), "hooks"),
    (re.compile(r"^claim rule `"), "claim_rules"),
    (re.compile(r"^banned tag `"), "banned_tags"),
    (re.compile(r"^search seed `"), "search_seeds"),
    (re.compile(r"^competitor_query uses"), "competitor_query"),
]


def _place(message: str) -> str:
    for pattern, section in _PLACES:
        m = pattern.match(message)
        if m:
            return section or re.sub(r"\[(\d+)\]", r".\1", m.group(1))
    return ""


def problems_of(exc: Exception) -> list[dict[str, str]]:
    """Pydantic errors as {path, message}; the cross-check's joined message is split back up and placed."""
    if isinstance(exc, ValidationError):
        out = []
        for err in exc.errors():
            path = ".".join(str(p) for p in err["loc"])
            message = str(err["msg"]).removeprefix("Value error, ")
            out.extend({"path": path or _place(m), "message": m} for m in message.split("; "))
        return out
    return [{"path": "", "message": str(exc)}]


def validate(data: Any) -> Preset:
    try:
        return Preset.model_validate(data)
    except ValidationError as exc:
        raise PresetProblem(problems_of(exc)) from exc


def parse_yaml(text: str) -> Any:
    try:
        return YAML(typ="safe").load(text)
    except Exception as exc:
        raise PresetProblem([{"path": "", "message": f"Not valid YAML: {exc}"}]) from exc


# ---- files ---------------------------------------------------------------------------


def preset_files(config_dir: Path) -> dict[str, Path]:
    """Preset id -> file, for every file that names an id (valid or not)."""
    folder = config_dir / "presets"
    found: dict[str, Path] = {}
    for path in sorted(folder.glob("*.yaml")) if folder.is_dir() else []:
        try:
            data = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001, S112 - a broken file is reported by load_presets; skip it here
            continue
        if isinstance(data, dict) and isinstance(data.get("id"), str):
            found.setdefault(data["id"], path)
    return found


def read_text(config_dir: Path, preset_id: str) -> str | None:
    path = preset_files(config_dir).get(preset_id)
    return path.read_text(encoding="utf-8") if path else None


def _write(path: Path, text: str) -> None:
    """Write next to the target, then swap, so a crash never leaves half a preset."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _dump(tree: Any) -> str:
    buf = io.StringIO()
    _yaml().dump(tree, buf)
    return buf.getvalue()


# ---- merge ---------------------------------------------------------------------------


def _scalar(old: Any, new: Any) -> Any:
    """A new string keeps the old one's style: block (| or >) or quoted. New multi-line text becomes |."""
    if not isinstance(new, str):
        return new
    if isinstance(old, FoldedScalarString) and "\n" not in new.rstrip("\n"):
        return FoldedScalarString(new)
    if isinstance(old, LiteralScalarString | FoldedScalarString) or "\n" in new.rstrip("\n"):
        return LiteralScalarString(new)
    if isinstance(old, DoubleQuotedScalarString):
        return DoubleQuotedScalarString(new)
    if isinstance(old, SingleQuotedScalarString):
        return SingleQuotedScalarString(new)
    return new


def _fresh(value: Any, flow: bool, like: Any = None) -> Any:
    """A new node for a value that was not in the file, styled like `like` (a sibling) where it can be."""
    if isinstance(value, dict):
        peer = like if isinstance(like, dict) else {}
        node = CommentedMap((k, _fresh(v, True, peer.get(k))) for k, v in value.items())
        if flow and not any(isinstance(v, str) and "\n" in v for v in value.values()):
            node.fa.set_flow_style()
        return node
    if isinstance(value, list):
        peer = like[0] if isinstance(like, list) and like else None
        node = CommentedSeq(_fresh(v, True, peer) for v in value)
        if flow:
            node.fa.set_flow_style()
        return node
    return _scalar(like, value)


def _item_key(item: Any) -> Any:
    if isinstance(item, dict):
        for k in ITEM_KEYS:
            if k in item:
                return (k, item[k])
        return None
    return ("value", item) if isinstance(item, str) else None


def _is_flow(node: Any) -> bool:
    return bool(getattr(node, "fa", None) and node.fa.flow_style())


def _merge_seq(old: CommentedSeq, full: list, minimal: list) -> CommentedSeq:
    keys_old = [_item_key(i) for i in old]
    keys_new = [_item_key(i) for i in full]
    keyed = all(k is not None for k in keys_old + keys_new) and len(set(keys_new)) == len(keys_new)
    if keyed and len(old) == len(full) and all(isinstance(i, str) for i in full):
        keyed = False  # strings edited in place: keep each line's comment on its line
    child_flow = any(_is_flow(i) for i in old if isinstance(i, CommentedMap | CommentedSeq)) or not old
    like = old[0] if old else None  # new items copy a sibling's quoting
    if keyed:
        kept = [k for k in keys_old if k in keys_new]
        if kept != [k for k in keys_new if k in keys_old]:
            # Reordered: rebuild in the new order, reusing each item's node (its own comments go with it).
            by_key = dict(zip(keys_old, old, strict=True))
            out = CommentedSeq(
                _merge(by_key[k], f, m) if k in by_key else _fresh(m, child_flow, like)
                for k, f, m in zip(keys_new, full, minimal, strict=True)
            )
            if _is_flow(old):
                out.fa.set_flow_style()
            return out
        for i in reversed(range(len(old))):
            if keys_old[i] not in keys_new:
                del old[i]
        # What is left is in the new order, so walk both and insert the new items where they belong.
        for j, (k, f, m) in enumerate(zip(keys_new, full, minimal, strict=True)):
            if j < len(old) and _item_key(old[j]) == k:
                old[j] = _merge(old[j], f, m)
            else:
                old.insert(j, _fresh(m, child_flow, like))
        return old
    # Plain lists: by position, so a comment on line 2 stays on line 2.
    for i in range(min(len(old), len(full))):
        old[i] = _merge(old[i], full[i], minimal[i])
    while len(old) > len(full):
        del old[-1]
    for f, m in zip(full[len(old):], minimal[len(old):], strict=True):
        old.append(_fresh(m, child_flow, like))
    return old


def _spelled_out(old: Any, full: Any) -> bool:
    """True when what the file writes matches `full` (keys it leaves out take their defaults)."""
    if isinstance(old, dict) and isinstance(full, dict):
        return all(k in full and _spelled_out(v, full[k]) for k, v in old.items())
    if isinstance(old, list) and isinstance(full, list):
        return len(old) == len(full) and all(_spelled_out(a, b) for a, b in zip(old, full, strict=True))
    return old == full


def _merge_map(old: CommentedMap, full: dict, minimal: dict, order: list[str] | None = None) -> CommentedMap:
    for key in list(old):
        if key in minimal:
            continue
        # Not in the minimal dump: the new value is the default, or the key is gone.
        if key not in full or full[key] is None:
            del old[key]
        elif not _spelled_out(old[key], full[key]):
            # Set back to the default: keep the line (and its comment) with the default value.
            old[key] = _merge(old[key], full[key], {} if isinstance(full[key], dict) else full[key])
    order = order or list(full)
    for key in order:
        if key not in minimal:
            continue
        if key in old:
            old[key] = _merge(old[key], full[key], minimal[key])
            continue
        # New key: after the nearest key that comes before it in the model's order.
        before = [k for k in order[: order.index(key)] if k in old]
        at = list(old).index(before[-1]) + 1 if before else 0
        old.insert(at, key, _fresh(minimal[key], _is_flow(old)))
    return old


def _merge(old: Any, full: Any, minimal: Any) -> Any:
    if old == full:
        return old  # unchanged: keep the node exactly as written
    if isinstance(old, CommentedMap) and isinstance(full, dict):
        return _merge_map(old, full, minimal if isinstance(minimal, dict) else {})
    if isinstance(old, CommentedSeq) and isinstance(full, list):
        return _merge_seq(old, full, minimal if isinstance(minimal, list) else full)
    if isinstance(full, dict | list):
        return _fresh(minimal, _is_flow(old))
    return _scalar(old, full)


def _minimal(preset: Preset) -> dict:
    return preset.model_dump(mode="json", exclude_defaults=True)


def as_yaml(preset: Preset) -> str:
    """A preset written out fresh (no file to keep the layout of)."""
    return _dump(_fresh(_minimal(preset), False))


def _restore_lines(original: str, baseline: str, merged: str) -> str:
    """Put the owner's own text back on every line the edit did not touch.

    The round-trip writer keeps comments but not the padding inside one-line `{...}` entries, so
    even an untouched line can come back reformatted. `baseline` is the file dumped with no change:
    it matches `original` line for line, differing only in that formatting. Lines of `merged` that
    equal baseline lines are swapped for the original lines; changed lines stay as dumped.
    """
    orig, base, new = original.splitlines(True), baseline.splitlines(True), merged.splitlines(True)
    if len(orig) != len(base):
        return merged  # the dump moved lines around; keep its text rather than guess
    out: list[str] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, base, new, autojunk=False).get_opcodes():
        out.extend(orig[i1:i2] if op == "equal" else new[j1:j2])
    return "".join(out)


def merged_text(original: str, preset: Preset) -> str:
    """The file's text with `preset` merged in, keeping everything that did not change."""
    tree = _yaml().load(original)
    if not isinstance(tree, CommentedMap):
        tree = CommentedMap()
    baseline = _dump(tree) if original.strip() else ""
    full = preset.model_dump(mode="json")
    minimal = _minimal(preset)
    minimal.setdefault("id", preset.id)
    minimal.setdefault("name", preset.name)
    _merge_map(tree, full, minimal, order=list(Preset.model_fields))
    merged = _dump(tree)
    return _restore_lines(original, baseline, merged) if baseline else merged


# ---- operations ----------------------------------------------------------------------


def _check_id(preset_id: str) -> None:
    if not PRESET_ID.match(preset_id):
        raise PresetProblem([{"path": "id", "message": "use lower-case letters, digits and _ (start with a letter, at most 40)"}])


def create(config_dir: Path, preset_id: str, name: str, copy_from: str | None) -> Preset:
    """A new preset file: a copy of another (its comments included) or a minimal start."""
    _check_id(preset_id)
    files = preset_files(config_dir)
    presets, _ = load_presets(config_dir)
    if preset_id in files or preset_id in presets:
        raise PresetProblem([{"path": "id", "message": f"a preset `{preset_id}` already exists"}], status=409)
    target = config_dir / "presets" / f"{preset_id}.yaml"
    if target.exists():
        raise PresetProblem([{"path": "id", "message": f"presets/{target.name} already exists"}], status=409)
    source = files.get(copy_from) if copy_from else None
    if copy_from and copy_from not in presets:
        raise PresetProblem([{"path": "copy_from", "message": f"no preset `{copy_from}`"}], status=404)
    if source:
        original = source.read_text(encoding="utf-8")
    else:
        original = as_yaml(presets[copy_from] if copy_from else presets["general"])
    tree = _yaml().load(original)
    baseline = _dump(tree)
    tree["id"] = preset_id
    tree["name"] = name.strip() or preset_id
    text = _restore_lines(original, baseline, _dump(tree))
    preset = validate(YAML(typ="safe").load(text))
    _write(target, text)
    return preset


def update(config_dir: Path, preset_id: str, data: dict) -> Preset:
    if data.get("id", preset_id) != preset_id:
        raise PresetProblem([{"path": "id", "message": "a preset's id cannot change; make a copy instead"}])
    preset = validate(data | {"id": preset_id})
    path = preset_files(config_dir).get(preset_id)
    if path is None:
        if preset_id != "general":
            raise PresetProblem([{"path": "", "message": f"no preset `{preset_id}`"}], status=404)
        path = config_dir / "presets" / "general.yaml"  # the built-in copy gets a file on first save
        original = ""
    else:
        original = path.read_text(encoding="utf-8")
    text = merged_text(original, preset)
    validate(YAML(typ="safe").load(text))  # the file as written must load back to the same preset
    _write(path, text)
    return preset


def write_yaml(config_dir: Path, preset_id: str, text: str) -> Preset:
    """The raw editor: the text is saved as typed, once it parses and validates."""
    data = parse_yaml(text)
    if not isinstance(data, dict):
        raise PresetProblem([{"path": "", "message": "a preset is a mapping of keys"}])
    if data.get("id") != preset_id:
        raise PresetProblem([{"path": "id", "message": f"the id must stay `{preset_id}`"}])
    preset = validate(data)
    path = preset_files(config_dir).get(preset_id) or config_dir / "presets" / f"{preset_id}.yaml"
    _write(path, text if text.endswith("\n") else text + "\n")
    return preset


def delete(config_dir: Path, preset_id: str) -> None:
    if preset_id == "general":
        raise PresetProblem([{"path": "", "message": "General cannot be deleted"}], status=409)
    path = preset_files(config_dir).get(preset_id)
    if path is None:
        raise PresetProblem([{"path": "", "message": f"no preset `{preset_id}`"}], status=404)
    path.unlink()
