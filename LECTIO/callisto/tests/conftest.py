"""Shared test setup: keep legacy tests on the single-agent path and make sure no test reaches Massive."""
import pytest


@pytest.fixture(autouse=True)
def _offline_single_pipeline(monkeypatch):
    monkeypatch.setenv("EUROPA_PIPELINE", "single")
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    try:
        from backend import massive
        massive.clear_cache()
    except ImportError:
        pass
    yield
