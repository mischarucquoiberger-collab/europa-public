"""The valuation panel: each method against hand numbers, every not-priced reason, peer
percentiles, the share-count rule, the original's blending rules, the quality score, and no advice
wording anywhere."""
import math
import re

import pytest

from backend.analysis import ratios, valuation as val
from backend.ledger import Fact, Ledger, Source

K = Source(id="", type="edinet", url="https://www.sec.gov/ix?doc=/Archives/edgar/data/1/k25.htm",
           title="Form 10-K, filed 2026-02-01", date="2026-02-01")
YE, COVER, DAY = "2025-12-31", "2026-01-31", "2026-03-02"
BASE = {
    ("eps_diluted", "FY2025"): 5.0, ("net_income", "FY2025"): 500.0, ("revenue", "FY2025"): 4000.0,
    ("operating_income", "FY2025"): 800.0, ("operating_cash_flow", "FY2025"): 700.0,
    ("capex", "FY2025"): 200.0, ("shareholders_equity", YE): 2000.0, ("total_assets", YE): 6000.0,
    ("long_term_debt", YE): 1500.0, ("cash", YE): 500.0,                     # net debt 1,000
    ("shares_outstanding", COVER): 100.0,
}
UNITS = {"eps_diluted": "USD/share", "shares_outstanding": "shares"}
# 6 P/E peers, 6 EV/EBIT, 5 usable EV/Sales (one None, one out of bounds), 4 P/B (thin)
PEERS = {"rows": [
    {"ticker": "A", "multiples": {"pe": 10.0, "ev_ebit": 8.0, "ev_sales": 1.0, "pb": 1.0}},
    {"ticker": "B", "multiples": {"pe": 12.0, "ev_ebit": 10.0, "ev_sales": 2.0, "pb": 2.0}},
    {"ticker": "C", "multiples": {"pe": 14.0, "ev_ebit": 12.0, "ev_sales": 3.0, "pb": 3.0}},
    {"ticker": "D", "multiples": {"pe": 16.0, "ev_ebit": 14.0, "ev_sales": None, "pb": 4.0}},
    {"ticker": "E", "multiples": {"pe": 18.0, "ev_ebit": 16.0, "ev_sales": 2.5, "pb": None}},
    {"ticker": "F", "multiples": {"pe": 20.0, "ev_ebit": 18.0, "ev_sales": 1.5, "pb": None}},
    {"ticker": "G", "multiples": {"pe": None, "ev_ebit": None, "ev_sales": 50.0, "pb": None}},
]}
# the scenario arithmetic's cases (enterprise values)
SCEN = {"cases": [{"key": "bear", "low": 7000.0, "base": 8000.0, "high": 9000.0},
                  {"key": "base", "low": 9000.0, "base": 10000.0, "high": 11500.0, "base_text": "$10,000"},
                  {"key": "bull", "low": 11000.0, "base": 12500.0, "high": 14000.0}],
        "assumptions": [{"label": "Beta", "value_html": "1.00 against the market index (assumption: no price history was used)"}]}
BANNED = re.compile(r"\b(?:target\s+price|upside|downside|undervalued|overvalued|buy|sell|hold|"
                    r"rating|recommend\w*)\b", re.IGNORECASE)


def _ledger(values=None, units=None):
    ledger = Ledger()
    sid = ledger.add_source(K)
    for (key, period), value in (BASE if values is None else values).items():
        unit = {**UNITS, **(units or {})}.get(key, "USD")
        ledger.add_fact(Fact(key=key, period=period, value=value, unit=unit, source_ids=(sid,)))
    ledger.set_period_end("FY2025", YE)
    ratios.compute(ledger)
    return ledger


def _with(**changes):
    values = dict(BASE)
    for name, value in changes.items():
        key, period = name.rsplit("__", 1)
        period = {"YE": YE, "COVER": COVER}.get(period, period)
        if value is None:
            values.pop((key, period), None)
        else:
            values[(key, period)] = value
    return values


def _compute(ledger=None, **kw):
    args = {"price": 100.0, "price_date": DAY, "scenarios": SCEN, "peer_table": PEERS}
    args.update(kw)
    return val.compute(ledger or _ledger(), **args)


def _m(out, key):
    return next(m for m in out["methods"] if m["key"] == key)


def _strings(obj):
    if isinstance(obj, str):
        yield re.sub(r"<[^>]+>", " ", obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _strings(v)


# ---- methods ---------------------------------------------------------------------------------
def test_shape():
    out = _compute()
    assert [m["key"] for m in out["methods"]] == list(val.KEYS)
    assert out["period_label"] == "fiscal 2025" and out["total"] == 6 and out["priced"] == 6
    assert out["price"] == 100.0 and out["price_text"] == "$100.00" and out["price_date_text"] == "2 Mar 2026"
    assert out["shares_text"] == "100 shares" and "from the filings" in out["shares_note"]
    fields = {"key", "label", "basis", "inputs_html", "value", "low", "high", "value_text", "range_text",
              "reason", "n_peers", "data_quality", "floor", "default_weight"}
    for m in out["methods"]:
        assert fields <= set(m)
        assert m["floor"] == (m["key"] != "dcf")


def test_dcf_from_the_scenario_cases():
    m = _m(_compute(), "dcf")
    # (10,000 - 1,000) / 100; bear low (7,000 - 1,000) / 100; bull high (14,000 - 1,000) / 100
    assert (m["value"], m["low"], m["high"]) == pytest.approx((90.0, 60.0, 130.0))
    assert m["value_text"] == "$90.00" and m["range_text"] == "$60.00 – $130.00"
    assert 'href="#calc-' in m["inputs_html"] or 'class="src"' in m["inputs_html"]
    assert m["data_quality"] == 0.5 and m["uses_assumption"]        # no growth estimate in the ledger


def test_pe_peer():
    m = _m(_compute(), "pe_peer")
    # median of 10..20 = 15; P25 = 12.5, P75 = 17.5 (linear); x EPS 5
    assert (m["value"], m["low"], m["high"]) == pytest.approx((75.0, 62.5, 87.5))
    assert m["n_peers"] == 6 and m["data_quality"] == 1.0
    assert "n=6" in m["inputs_html"] and "15.0x" in m["inputs_html"]


def test_ev_ebit_peer():
    m = _m(_compute(), "ev_ebit_peer")
    # median 13, P25 10.5, P75 15.5; (13 x 800 - 1,000) / 100
    assert (m["value"], m["low"], m["high"]) == pytest.approx((94.0, 74.0, 114.0))


def test_ev_sales_peer_skips_none_and_out_of_bounds():
    m = _m(_compute(), "ev_sales_peer")
    # 1.0, 1.5, 2.0, 2.5, 3.0 (None and 50x left out): median 2, P25 1.5, P75 2.5
    assert m["n_peers"] == 5 and m["data_quality"] == 1.0
    assert (m["value"], m["low"], m["high"]) == pytest.approx((70.0, 50.0, 90.0))


def test_net_cash_raises_the_equity_value():
    out = _compute(_ledger(_with(cash__YE=2500.0)))                      # net debt -1,000
    assert _m(out, "ev_sales_peer")["value"] == pytest.approx((2 * 4000 + 1000) / 100)
    assert _m(out, "dcf")["value"] == pytest.approx((10000 + 1000) / 100)


def test_pb_peer_thin_sample():
    m = _m(_compute(), "pb_peer")
    # BVPS 2,000 / 100 = 20; median 2.5, P25 1.75, P75 3.25 over four peers
    assert (m["value"], m["low"], m["high"]) == pytest.approx((50.0, 35.0, 65.0))
    assert m["n_peers"] == 4 and m["data_quality"] == 0.6


def test_graham():
    m = _m(_compute(), "graham")
    g = math.sqrt(22.5 * 5.0 * 20.0)
    assert (m["value"], m["low"], m["high"]) == pytest.approx((g, g * 0.85, g * 1.15))


def test_the_ledger_net_debt_fact_is_preferred():
    from backend.analysis import scenarios
    ledger = _ledger()
    scenarios.compute(ledger)                                             # adds net_debt FY2025
    m = _m(_compute(ledger), "dcf")
    assert 'href="#calc-net_debt-FY2025"' in m["inputs_html"]


@pytest.mark.parametrize("values,kw,key,reason", [
    (None, {"scenarios": None}, "dcf", "free cash flow"),
    (_with(cash__YE=None), {}, "dcf", "net debt is not available"),
    (_with(eps_diluted__FY2025=-1.0), {}, "pe_peer", "zero or negative"),
    (_with(eps_diluted__FY2025=None), {}, "pe_peer", "not in the sources"),
    (_with(operating_income__FY2025=-5.0), {}, "ev_ebit_peer", "zero or negative"),
    (_with(long_term_debt__YE=None), {}, "ev_sales_peer", "net debt is not available"),
    (_with(shareholders_equity__YE=-10.0), {}, "pb_peer", "zero or negative"),
    (_with(eps_diluted__FY2025=-1.0), {}, "graham", "positive diluted EPS"),
    (None, {"peer_table": {"rows": PEERS["rows"][:2]}}, "pe_peer", "at least 3 peers"),
    (None, {"peer_table": None}, "ev_ebit_peer", "at least 3 peers"),
])
def test_not_priced_reasons(values, kw, key, reason):
    m = _m(_compute(_ledger(values) if values else None, **kw), key)
    assert m["value"] is None and m["low"] is None and m["value_text"] is None
    assert reason in m["reason"]


def test_ev_not_covering_net_debt_is_not_priced():
    m = _m(_compute(_ledger(_with(long_term_debt__YE=20000.0))), "ev_sales_peer")
    assert m["value"] is None and "does not cover net debt" in m["reason"]


@pytest.mark.parametrize("values,median,p25,p75", [
    ([10.0, 20.0, 30.0], 20.0, 15.0, 25.0),
    ([1.0, 2.0, 3.0, 4.0], 2.5, 1.75, 3.25),
    ([10.0, 12.0, 14.0, 16.0, 18.0, 20.0], 15.0, 12.5, 17.5),
])
def test_peer_percentiles(values, median, p25, p75):
    assert val.percentile(values, 50) == pytest.approx(median)
    assert val.percentile(values, 25) == pytest.approx(p25)
    assert val.percentile(values, 75) == pytest.approx(p75)
    multiple = "pe" if min(values) >= 2.0 else "pb"                      # P/E bounds are 2x-100x
    table = {"rows": [{"multiples": {multiple: v}} for v in values]
             + [{"multiples": {multiple: None}}, {"multiples": {}}, {}]}
    assert val.peer_values(table, multiple) == values


def test_three_peers_are_enough_and_thin():
    table = {"rows": [{"multiples": {"pe": v}} for v in (10.0, 20.0, 30.0)]}
    m = _m(_compute(peer_table=table), "pe_peer")
    assert m["value"] == pytest.approx(100.0) and m["data_quality"] == 0.6 and m["n_peers"] == 3


# ---- share count -------------------------------------------------------------------------------
def test_stale_share_count_falls_back_to_the_supplied_one():
    stale = _with(shares_outstanding__COVER=None)
    stale[("shares_outstanding", "2024-06-30")] = 100.0
    out = _compute(_ledger(stale), shares=200.0, shares_note="Massive, 1 Mar 2026")
    assert out["shares_text"] == "200 shares" and out["shares_note"] == "Massive, 1 Mar 2026"
    assert _m(out, "pb_peer")["value"] == pytest.approx(2.5 * 2000 / 200)
    out = _compute(_ledger(stale))
    for key in ("dcf", "ev_ebit_peer", "ev_sales_peer", "pb_peer", "graham"):
        assert _m(out, key)["value"] is None and "400 days" in _m(out, key)["reason"]
    assert _m(out, "pe_peer")["value"] == pytest.approx(75.0)          # needs no share count
    assert out["shares_text"] is None


def test_no_fiscal_year_gives_none():
    assert val.compute(Ledger(), price=1.0, price_date=DAY) is None


# ---- blend -------------------------------------------------------------------------------------
def test_default_weights_times_data_quality():
    out = val.blend(_compute())
    rel = {"dcf": 60 * 0.5, "pe_peer": 50, "ev_ebit_peer": 40, "ev_sales_peer": 30, "pb_peer": 30 * 0.6, "graham": 20}
    values = {m["key"]: m["value"] for m in out["methods"]}
    expected = sum(values[k] * w for k, w in rel.items()) / sum(rel.values())
    assert out["blend"]["value"] == pytest.approx(expected)
    assert out["blend"]["label"] == "Model value"
    assert out["blend"]["basis"] == "Weight-blended average of 6 priced methods"
    assert out["advisor"] == {"method": "default", "rationale_html": None}
    by = {m["key"]: m for m in out["methods"]}
    assert by["dcf"]["weight"] == 60 and by["dcf"]["share"] == pytest.approx(30 / 188)
    assert sum(m["share"] for m in out["methods"]) == pytest.approx(1.0)
    assert sum(int(m["share_text"][:-1]) for m in out["methods"]) == 100
    assert "thin peer sample (n=4)" in by["pb_peer"]["note"] and "assumed growth input" in by["dcf"]["note"]
    lows = sum(by[k]["low"] * w for k, w in rel.items()) / 188
    assert out["blend"]["low"] == pytest.approx(min(lows, expected))
    assert val.blend(_compute(), {})["blend"]["value"] == pytest.approx(expected)


def test_floors_explicit_zero_and_absent_weights():
    out = val.blend(_compute(), {"dcf": 50, "pe_peer": 5, "graham": 0})
    by = {m["key"]: m for m in out["methods"]}
    assert by["pe_peer"]["blend_weight"] == 20 and "floor weight of 20" in by["pe_peer"]["note"]
    assert by["ev_ebit_peer"]["blend_weight"] == 20                     # absent, lifted to its floor
    assert by["ev_sales_peer"]["blend_weight"] == 15
    assert by["pb_peer"]["blend_weight"] == pytest.approx(20 * 0.6)
    assert by["graham"]["blend_weight"] == 0 and by["graham"]["share"] == 0
    assert by["graham"]["share_text"] == "0%" and "excluded by the advisor" in by["graham"]["note"]
    out = val.blend(_compute(), {"pe_peer": 50})
    dcf = next(m for m in out["methods"] if m["key"] == "dcf")
    assert dcf["share"] == 0 and "no weight" in dcf["note"]             # no floor for the DCF


def _synthetic(methods, price=100.0, context=None):
    rows = []
    for key, value, low, high in methods:
        rows.append({"key": key, "label": val.LABELS[key], "basis": "", "inputs_html": "", "value": value,
                     "low": low, "high": high, "value_text": None, "range_text": None,
                     "reason": None if value is not None else "not priced", "n_peers": None,
                     "data_quality": 1.0, "floor": key in val.FLOOR_WEIGHTS, "default_weight": 50,
                     "own_multiple": None, "peer_median": None, "uses_assumption": False})
    return {"period_label": "fiscal 2025", "price": price, "methods": rows,
            "priced": sum(1 for r in rows if r["value"] is not None), "total": len(rows),
            "context": context or {"period_end": YE, "price_date": DAY, "years": 5,
                                   "completeness": {k: True for k in range(7)}, "beta_assumed": False}}


def test_outlier_capped_at_five():
    v = _synthetic([("dcf", 300.0, 250.0, 350.0), ("pe_peer", 100.0, 80.0, 120.0)])
    out = val.blend(v, {"dcf": 60, "pe_peer": 50})
    dcf = next(m for m in out["methods"] if m["key"] == "dcf")
    assert dcf["blend_weight"] == 5 and "outlier: capped at 5%" in dcf["note"]
    assert out["blend"]["value"] == pytest.approx((300 * 5 + 100 * 50) / 55)
    # no price: no outlier rule, no comparison
    out = val.blend(_synthetic([("dcf", 300.0, 250.0, 350.0), ("pe_peer", 100.0, 80.0, 120.0)], price=None),
                    {"dcf": 60, "pe_peer": 50})
    assert out["blend"]["value"] == pytest.approx((300 * 60 + 100 * 50) / 110)
    assert out["blend"]["vs_price"] is None and out["blend"]["vs_price_text"] is None


def test_ranges_widened_to_ten_percent_and_default_band():
    v = _synthetic([("dcf", 100.0, 98.0, 102.0), ("pe_peer", 100.0, None, None)])
    out = val.blend(v, {"dcf": 50, "pe_peer": 50})
    dcf, pe = out["methods"]
    assert (dcf["low"], dcf["high"]) == pytest.approx((90.0, 110.0)) and "plus or minus 10%" in dcf["note"]
    assert (pe["low"], pe["high"]) == pytest.approx((85.0, 115.0))
    assert out["blend"]["low"] == pytest.approx(87.5) and out["blend"]["high"] == pytest.approx(112.5)


def test_vs_price_sign_and_text():
    up = val.blend(_synthetic([("dcf", 110.0, 90.0, 130.0)]), {"dcf": 50})["blend"]
    down = val.blend(_synthetic([("dcf", 90.0, 70.0, 110.0)]), {"dcf": 50})["blend"]
    assert up["vs_price"] == pytest.approx(0.10) and up["vs_price_text"] == "+10.0%"
    assert down["vs_price"] == pytest.approx(-0.10) and down["vs_price_text"] == "-10.0%"
    assert up["value_text"] == "$110.00" and up["range_text"] == "$90.00 – $130.00"


def test_no_priced_method():
    out = val.blend(_synthetic([("dcf", None, None, None), ("pe_peer", None, None, None)]))
    assert out["blend"]["value"] is None and out["blend"]["value_text"] is None
    assert out["blend"]["basis"] == "No method priced"
    assert all(m["share"] == 0 and m["share_text"] is None for m in out["methods"])


def test_cohort_not_comparable_is_reference_only():
    v = _synthetic([("pe_peer", 100.0, 80.0, 120.0), ("pb_peer", 90.0, 70.0, 110.0)])
    v["methods"][0].update(own_multiple=40.0, peer_median=10.0)          # 4x apart
    out = val.blend(v, {"pe_peer": 50, "pb_peer": 50})
    pe = out["methods"][0]
    assert pe["blend_weight"] == 0 and "reference only" in pe["note"]
    assert out["blend"]["value"] == pytest.approx(90.0)


def test_quality_score_parts():
    v = _synthetic([("dcf", 100.0, 90.0, 110.0), ("pe_peer", 110.0, 99.0, 121.0)])
    q = val.blend(v, {"dcf": 50, "pe_peer": 50})["quality"]
    # 20 + 2 x 10 = 40; recency (2 months) +15; agreement (cv 4.8%) +15; 5 years +10; 7 of 7 +5
    assert q["score"] == 85 and q["text"] == "85"
    labels = [p["label"] for p in q["parts"]]
    assert labels[:5] == ["Priced methods in the blend", "Data recency", "Agreement between methods",
                          "History", "Completeness"]
    ctx = {"period_end": "2023-12-31", "price_date": DAY, "years": 2, "completeness": {},
           "beta_assumed": True}
    v = _synthetic([("dcf", 100.0, 90.0, 110.0), ("pe_peer", 250.0, 225.0, 275.0)], context=ctx)
    v["methods"][0]["uses_assumption"] = True
    q = val.blend(v, {"dcf": 50, "pe_peer": 50})["quality"]
    # 40 + 0 (26 months) - 5 (cv 42.9%) + 0 + 0 - 5 (assumption) - 3 (beta assumed) = 27
    assert q["score"] == 27 and "assumed growth input -5" in q["parts"][-2]["text"]


def test_blend_never_raises_and_returns_a_new_dict():
    v = _compute()
    before = repr(v)
    out = val.blend(v, {"dcf": "lots", "pe_peer": float("nan")})
    assert repr(v) == before and out is not v and "blend" in out
    assert val.blend({"methods": "broken"})["blend"]["value"] is None


def test_no_advice_words_anywhere():
    for weights in (None, {"dcf": 0, "pe_peer": 80}):
        out = val.blend(_compute(), weights)
        for text in _strings(out):
            assert not BANNED.search(text), text
        assert "Model value" == out["blend"]["label"]
        assert out["methodology"].startswith("Methodology:")


# ---- review round -------------------------------------------------------------------------------
def test_fallback_net_debt_subtracts_short_term_investments():
    out = _compute(_ledger({**BASE, ("short_term_investments", YE): 2000.0}))
    m = _m(out, "ev_sales_peer")
    # net debt 1,500 - 500 - 2,000 = -1,000 (net cash): (2 x 4,000 + 1,000) / 100
    assert m["value"] == pytest.approx(90.0)
    assert "less short-term investments" in m["inputs_html"]
    assert _m(_compute(), "ev_sales_peer")["value"] == pytest.approx(70.0)     # without them


def test_financial_company():
    out = _compute(financial=True)
    assert out["financial"] is True
    for key in val.FINANCIAL_KEYS:
        m = _m(out, key)
        assert m["value"] is None and m["reason"] == val.FINANCIAL_REASON and m["default_weight"] == 0
    for key in ("pe_peer", "pb_peer", "graham"):
        assert _m(out, key)["value"] is not None
    assert {m["key"]: m["default_weight"] for m in out["methods"]} == {
        "dcf": 0, "pe_peer": 50, "ev_ebit_peer": 0, "ev_sales_peer": 0, "pb_peer": 60, "graham": 20}
    b = val.blend(out)
    # P/B thin sample: 60 x 0.6 = 36; P/E 50; Graham 20
    values = {m["key"]: m["value"] for m in b["methods"]}
    expected = (values["pb_peer"] * 36 + values["pe_peer"] * 50 + values["graham"] * 20) / 106
    assert b["blend"]["value"] == pytest.approx(expected)
    assert "For a bank or insurer the DCF and the enterprise-value multiples are not used" in b["methodology"]
    assert "bank or insurer" not in val.blend(_compute())["methodology"]


def test_no_output_names_the_original_product():
    for kw in ({}, {"financial": True}, {"price": None}, {"scenarios": None}):
        out = val.blend(_compute(**kw))
        for text in _strings(out):
            assert "original" not in text.lower(), text
