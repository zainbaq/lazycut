"""Small, comment-keeping writes to config/channel.yaml (Phase 3): adding the channel's playlists."""

from pathlib import Path

from ruamel.yaml.comments import CommentedSeq

from app.services.preset_store import _dump, _fresh, _restore_lines, _write, _yaml


def add_playlists(config_dir: Path, rows: list[dict]) -> list[dict]:
    """Append `{topic, name, url}` entries to `playlists`, styled like the ones already there.

    Every other line of the file stays as written. Returns the entries added.
    """
    path = config_dir / "channel.yaml"
    original = path.read_text(encoding="utf-8")
    tree = _yaml().load(original)
    baseline = _dump(tree)
    seq = tree.get("playlists")
    if not isinstance(seq, CommentedSeq):
        seq = CommentedSeq()
        tree["playlists"] = seq
    like = seq[0] if len(seq) else None
    added = []
    for row in rows:
        entry = {"topic": row["topic"], "name": row["name"], "url": row["url"]}
        seq.append(_fresh(entry, True, like))
        added.append(entry)
    if added:
        _write(path, _restore_lines(original, baseline, _dump(tree)))
    return added
