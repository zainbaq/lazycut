"""Playbook: how a preset's event types show up in one specific topic (a game, a series).

The preset stays generic ("counter: the player lands a perfect counter"). The
playbook is the topic-specific layer on top of it, written by the research step
and cached per topic, that the video model reads before it watches.
"""

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from ruamel.yaml import YAML

from app.services.presets import Preset


class PlaybookEntry(BaseModel):
    event_type: str
    applies: bool = True  # False: this event type does not exist in this topic
    known_as: str = ""  # what the topic itself calls it
    looks_like: str = ""
    sounds_like: str = ""
    not_to_confuse_with: str = ""


class Playbook(BaseModel):
    topic: str
    summary: str = ""
    coverage: Literal["good", "partial", "thin"] = "partial"
    entries: list[PlaybookEntry] = Field(default_factory=list)
    screen_notes: str = ""  # HUD and on-screen layout, as far as research found it
    unknowns: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)

    def entries_for(self, preset: Preset) -> list[PlaybookEntry]:
        """Entries for this preset's event types, in the preset's order."""
        by_type = {e.event_type: e for e in self.entries}
        return [by_type[t] for t in preset.event_type_ids() if t in by_type]


def slugify(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")


def load_playbook(folder: Path, topic: str) -> Playbook | None:
    """Return the saved playbook for a topic, or None when there is none."""
    path = folder / f"{slugify(topic)}.yaml"
    if not topic.strip() or not path.is_file():
        return None
    return Playbook.model_validate(YAML(typ="safe").load(path.read_text(encoding="utf-8")))
