from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_OPTIONAL_FIELDS = {"analysis_fps", "analysis_media_resolution"}


class Settings(BaseSettings):
    """Environment-driven settings. Model ids are never hard-coded; they come from the env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str = ""
    gemini_video_model: str = ""
    anthropic_api_key: str = ""
    anthropic_model: str = ""
    youtube_api_key: str = ""
    higgsfield_api_key: str = ""     # thumbnail generation (7.13): the console's API key, "id:secret" in one value
    higgsfield_key_id: str = ""      # or the two halves separately
    higgsfield_key_secret: str = ""
    higgsfield_base_url: str = "https://api.higgsfield.ai"

    data_dir: Path = Path("/data")
    db_path: Path = Path("/db/app.db")
    config_dir: Path = Path("/config")
    inbox_dir: Path = Path("/inbox")
    eval_dir: Path = Path("/eval")
    web_origin: str = "http://localhost:3000"

    analysis_fps: float | None = 1.0
    analysis_media_resolution: Literal["low", "medium", "high"] | None = None
    event_detectors: str = "gemini"  # comma-separated detector ids, in merge priority order
    event_snap: Literal["off", "visual"] = "off"
    search_demand: Literal["youtube_suggest", "off"] = "youtube_suggest"  # free search-suggestion harvest (7.7.1)
    dead_time_threshold: float = 0.08
    export_vertical_size: str = "1080x1920"

    @property
    def detector_ids(self) -> list[str]:
        return [d.strip() for d in self.event_detectors.split(",") if d.strip()]

    @property
    def higgsfield_credential(self) -> str:
        """"id:secret" for the `Authorization: Key` header, from whichever variables are set; "" when none."""
        if self.higgsfield_api_key:
            return self.higgsfield_api_key
        if self.higgsfield_key_id and self.higgsfield_key_secret:
            return f"{self.higgsfield_key_id}:{self.higgsfield_key_secret}"
        if ":" in self.higgsfield_key_secret:  # the combined key put in the secret's place
            return self.higgsfield_key_secret
        return ""

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def playbook_dir(self) -> Path:
        return self.config_dir / "playbooks"

    @field_validator("*", mode="before")
    @classmethod
    def _clean_env_value(cls, value: object, info: ValidationInfo) -> object:
        """Drop `# comments` that Docker's env_file leaves on values, and treat blanks as unset.

        `KEY=value   # note` arrives as `value   # note`; `KEY=   # note` arrives as `# note`.
        """
        if not isinstance(value, str):
            return value
        value = value.strip()
        if value.startswith("#"):
            value = ""
        elif " #" in value:
            value = value.split(" #", 1)[0].strip()
        if not value and info.field_name in _OPTIONAL_FIELDS:
            return None
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
