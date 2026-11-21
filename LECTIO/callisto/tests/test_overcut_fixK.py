"""'Closing price was $X on the last trading day, down from $Y on <prior date>' is true and must not be cut."""
from backend import gate
from tests.test_checker_holes import _market_pack


def _check(p, text):
    return gate.final_check("AAPL", {"status": "ANSWERED", "claims": [], "answer": text}, [p])["status"]


def test_last_trading_day_with_the_prior_date_passes_and_wrong_pairings_are_cut(monkeypatch):
    p = _market_pack(monkeypatch)
    last, prior = p["facts"]["px_close_last"], p["facts"]["px_close_prior"]
    way = "up" if last["value"] > prior["value"] else "down"
    ok = f"Closing price was {last['display']} on the last trading day, {way} from {prior['display']} on {prior['as_of']}."
    assert _check(p, ok) == "ANSWERED"
    # wrong direction, a date that is neither bar, the prior close passed off as the latest: all still cut
    flip = "down" if way == "up" else "up"
    assert _check(p, ok.replace(f", {way} from", f", {flip} from")) == "I_DONT_KNOW"
    assert _check(p, f"Closing price was {last['display']} on the last trading day, 2026-11-10.") == "I_DONT_KNOW"
    assert _check(p, f"Closing price was {prior['display']} on the last trading day.") == "I_DONT_KNOW"
    assert _check(p, f"Closing price was {last['display']} on {prior['as_of']}.") == "I_DONT_KNOW"


def test_one_day_move_next_to_the_prior_date_passes_only_with_the_last_day_cue(monkeypatch):
    p = _market_pack(monkeypatch)
    f = p["facts"]
    last, prior, r1 = f["px_close_last"], f["px_close_prior"], f["ret_1d_pct"]
    way = "up" if last["value"] > prior["value"] else "down"
    ok = (f"Closing price was {last['display']} on the last trading day, {way} from {prior['display']} on "
          f"{prior['as_of']}, and price return was {r1['display']} over one day.")
    assert _check(p, ok) == "ANSWERED"
    assert _check(p, f"Price return was {r1['display']} over one day on {prior['as_of']}.") == "I_DONT_KNOW"


def test_six_month_return_is_a_checked_fact_with_its_own_window(monkeypatch):
    from backend import specialists as sp
    p = _market_pack(monkeypatch)
    src = "Massive market data (end-of-day)"
    p["facts"]["ret_3m_pct"] = sp._fact("Price return, three months (about sixty-three trading days)", -4.2, "pct", src, p["as_of"], "-4.2%")
    p["facts"]["ret_6m_pct"] = sp._fact("Price return, six months (about one hundred twenty-six trading days)", 11.3, "pct", src, p["as_of"], "+11.3%")
    assert _check(p, "Price return was +11.3% over the past six months.") == "ANSWERED"
    # the three-month figure may not be passed off as the six-month one, or the other way round
    assert _check(p, "Price return was -4.2% over the past six months.") == "I_DONT_KNOW"
    assert _check(p, "Price return was +11.3% over the past three months.") == "I_DONT_KNOW"
