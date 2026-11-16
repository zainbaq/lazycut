import pytest


@pytest.fixture(autouse=True)
def _no_live_search_suggestions(monkeypatch):
    """Tests never call YouTube's suggestion endpoint; a test that needs demand data sets a fake client."""
    monkeypatch.setenv("SEARCH_DEMAND", "off")
