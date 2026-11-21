"""One symbol form inside (upper case, class share with a dot); each provider's form at the edge."""
import pytest

from backend.sources import tickers


@pytest.mark.parametrize("given, expected", [
    ("aapl", "AAPL"), ("BRK.B", "BRK.B"), ("brk-b", "BRK.B"), (" v ", "V"), ("GOOGL", "GOOGL"),
])
def test_normalise_round_trips(given, expected):
    assert tickers.normalise(given) == expected
    assert tickers.normalise(tickers.normalise(given)) == expected
    assert tickers.normalise(tickers.for_sec(given)) == expected
    assert tickers.normalise(tickers.for_massive(given)) == expected


def test_provider_forms():
    assert tickers.for_sec("BRK.B") == "BRK-B"
    assert tickers.for_sec("aapl") == "AAPL"
    assert tickers.for_massive("brk-b") == "BRK.B"
    assert tickers.for_massive("BRK.B") == "BRK.B"


@pytest.mark.parametrize("bad", ["7203", "TOOLONG", "A B", "", "BRK.BB", "A.B.C", "BRK_B", None, 42])
def test_anything_else_is_refused(bad):
    with pytest.raises(ValueError):
        tickers.normalise(bad)
    with pytest.raises(ValueError):
        tickers.for_sec(bad)
    with pytest.raises(ValueError):
        tickers.for_massive(bad)
