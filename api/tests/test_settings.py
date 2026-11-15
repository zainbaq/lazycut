from app.settings import Settings


def test_env_file_comments_and_blanks(monkeypatch):
    # What Docker's env_file hands over for the lines in .env.example.
    monkeypatch.setenv("GEMINI_VIDEO_MODEL", "gemini-3.8-flash     # free-tier Flash model")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "# optional")
    monkeypatch.setenv("ANALYSIS_FPS", "# full-pass sampling rate")
    monkeypatch.setenv("ANALYSIS_MEDIA_RESOLUTION", "")
    monkeypatch.setenv("EVENT_SNAP", "off                          # off | visual")
    settings = Settings(_env_file=None)
    assert settings.gemini_video_model == "gemini-3.8-flash"
    assert settings.anthropic_api_key == ""
    assert settings.analysis_fps is None
    assert settings.analysis_media_resolution is None
    assert settings.event_snap == "off"


def test_real_values_pass_through(monkeypatch):
    monkeypatch.setenv("ANALYSIS_FPS", "5")
    monkeypatch.setenv("ANALYSIS_MEDIA_RESOLUTION", "high")
    settings = Settings(_env_file=None)
    assert settings.analysis_fps == 5.0
    assert settings.analysis_media_resolution == "high"
