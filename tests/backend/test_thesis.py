"""Thesis and bull / bear points: code picks the side by fixed rules, the model only words it, and
every sentence passes the audit (or the code sentence is used). Offline: the model is faked."""
import html as _html
import json
import re

import llm
from backend import format as fmt
from backend.analysis import ratios
from backend.draft import thesis
from backend.facts import metrics
from backend.ledger import Fact, Ledger, Source
from backend.verify import audit

SRC = Source("x", "edinet", "https://www.sec.gov/Archives/edgar/data/1/k.htm", "Form 10-K", "2025-11-01")
_YEAR = re.compile(r"\b(?:199\d|20\d\d|2100)\b")
_ANCHOR = re.compile(r"<a\b[^>]*>.*?</a>", re.DOTALL)


def _lg(reported=None, computed=None):
    """reported / computed: {key: {year: value}}. Instant metrics sit on the fiscal year end;
    computed facts (ratios, free cash flow) cite a capex fact of the same year as their input."""
    reported, computed = reported or {}, computed or {}
    lg = Ledger()
    sid = lg.add_source(SRC)
    years = {y for series in (*reported.values(), *computed.values()) for y in series}
    for y in sorted(years):
        lg.set_period_end(f"FY{y}", f"{y}-12-31")
    for key, series in reported.items():
        m = metrics.METRICS[key]
        for y, v in series.items():
            period = f"{y}-12-31" if m.kind == "instant" else f"FY{y}"
            lg.add_fact(Fact(key, period, v, m.unit, source_ids=(sid,)))
    for key, series in computed.items():
        for y, v in series.items():
            if lg.get("capex", f"FY{y}") is None:
                lg.add_fact(Fact("capex", f"FY{y}", 1.0, "USD", source_ids=(sid,)))
            unit = "USD" if key == "free_cash_flow" else "ratio"
            lg.add_fact(Fact(key, f"FY{y}", v, unit, inputs=(("capex", f"FY{y}"),), formula="test"))
    return lg


def _ids(lg):
    return {s.id: s for s in thesis.signals(lg)}


M = 1e6
BULL = dict(
    reported={"revenue": {2022: 100 * M, 2023: 110 * M, 2024: 121 * M, 2025: 133.1 * M},
              "net_income": {2024: 10 * M, 2025: 12 * M},
              "operating_cash_flow": {2025: 18 * M},
              "cash": {2025: 50 * M}, "long_term_debt": {2025: 40 * M},
              "shareholders_equity": {2025: 100 * M},
              "eps_diluted": {2024: 2.00, 2025: 2.10},
              "shares_outstanding": {2024: 100 * M, 2025: 99 * M},
              "dividends_per_share": {2024: 1.00, 2025: 1.10}},
    computed={"revenue_growth": {2025: 0.10}, "net_income_growth": {2025: 0.20},
              "operating_margin": {2024: 0.20, 2025: 0.25}, "gross_margin": {2024: 0.45, 2025: 0.50},
              "return_on_equity": {2024: 0.15, 2025: 0.20}, "debt_to_equity": {2024: 0.50, 2025: 0.40},
              "free_cash_flow": {2024: 10 * M, 2025: 15 * M}})
BEAR = dict(
    reported={"revenue": {2022: 133 * M, 2023: 121 * M, 2024: 125 * M, 2025: 100 * M},
              "net_income": {2024: 10 * M, 2025: -5 * M},
              "shareholders_equity": {2025: -10 * M},
              "eps_diluted": {2024: 2.00, 2025: 0.50},
              "shares_outstanding": {2024: 100 * M, 2025: 103 * M},
              "dividends_per_share": {2024: 1.00, 2025: 0.50}},
    computed={"revenue_growth": {2025: -0.20}, "net_income_growth": {2025: -1.5},
              "operating_margin": {2024: 0.20, 2025: 0.10}, "gross_margin": {2024: 0.40, 2025: 0.30},
              "return_on_equity": {2024: 0.10, 2025: -0.10}, "debt_to_equity": {2024: 0.40, 2025: 0.60},
              "free_cash_flow": {2024: 10 * M, 2025: -3 * M}})
BEAR2 = dict(   # the other bear variants
    reported={"revenue": {2022: 130 * M, 2023: 120 * M, 2024: 110 * M, 2025: 100 * M},
              "net_income": {2024: 12 * M, 2025: 10 * M}, "operating_cash_flow": {2025: 6 * M}},
    computed={"free_cash_flow": {2024: 10 * M, 2025: 8 * M}, "net_income_growth": {2025: 10 / 12 - 1}})
EDGE = dict(    # matched cash conversion, cash equal to debt, negative cash flow with no prior year
    reported={"net_income": {2025: 10 * M}, "operating_cash_flow": {2025: 10 * M},
              "cash": {2025: 40 * M}, "long_term_debt": {2025: 40 * M}},
    computed={"free_cash_flow": {2025: -2 * M}})


def _all_ledgers():
    return [_lg(**BULL), _lg(**BEAR), _lg(**BEAR2), _lg(**EDGE)]


def _visible_digits(html):
    """Digits a reader sees once the linked figures are taken out and years are allowed (entities
    such as &#x27; are unescaped first: they are not typed digits)."""
    return re.findall(r"\d", _YEAR.sub(" ", _html.unescape(_ANCHOR.sub(" ", html))))


# ---- the rules ---------------------------------------------------------------------------------
def test_bull_ledger_fires_every_bull_rule_on_the_bull_side():
    found = _ids(_lg(**BULL))
    expected = {"revenue_growth_up", "revenue_trend_up", "net_income_growth_up", "operating_margin_up",
                "gross_margin_up", "return_on_equity_up", "free_cash_flow_up", "cash_conversion_high",
                "debt_to_equity_down", "cash_covers_debt", "eps_diluted_up", "share_count_down",
                "dividends_per_share_up"}
    assert set(found) == expected
    assert all(s.side == "bull" for s in found.values())
    assert found["revenue_growth_up"].tokens == (("revenue", "FY2025"), ("revenue_growth", "FY2025"),
                                                 ("revenue", "FY2024"))
    assert found["revenue_growth_up"].template == (
        "Revenue rose to [[F:revenue|FY2025]] in fiscal 2025 from [[F:revenue|FY2024]] a year earlier, "
        "a change of [[F:revenue_growth|FY2025]].")
    assert found["cash_covers_debt"].tokens == (("cash", "2025-12-31"), ("long_term_debt", "2025-12-31"))


def test_bear_ledgers_fire_every_bear_rule_on_the_bear_side():
    found = _ids(_lg(**BEAR))
    # net income went from a profit to a loss: the loss is a point, the percentage is not
    expected = {"revenue_growth_down", "revenue_trend_down", "net_loss",
                "operating_margin_down", "gross_margin_down", "return_on_equity_down",
                "free_cash_flow_negative", "debt_to_equity_up", "negative_equity", "eps_diluted_down",
                "share_count_up", "dividends_per_share_down"}
    assert set(found) == expected
    assert all(s.side == "bear" for s in found.values())
    assert "two of the last three" in found["revenue_trend_down"].template
    assert "down from" in found["free_cash_flow_negative"].template
    found2 = _ids(_lg(**BEAR2))
    assert {"free_cash_flow_down", "cash_conversion_low", "revenue_trend_down",
            "net_income_growth_down"} <= set(found2)
    assert "each of the last three" in found2["revenue_trend_down"].template


def test_every_rule_in_the_table_is_reachable():
    seen = set()
    for lg in _all_ledgers():
        seen |= set(_ids(lg))
    assert seen == set(thesis.RULES)


def test_growth_rules_stay_silent_without_facts_or_under_the_threshold():
    rev = {"revenue": {2024: 100 * M, 2025: 100.05 * M}}
    assert not _ids(_lg(rev, {"revenue_growth": {2025: 0.0005}}))          # under 0.1 point
    assert not _ids(_lg({"revenue": {2025: 110 * M}}, {"revenue_growth": {2025: 0.10}}))   # no prior
    assert not _ids(_lg({"revenue": {2024: 100 * M, 2025: 110 * M}}))     # no growth fact
    # three years only: no three-step trend
    three = _lg({"revenue": {2023: 100 * M, 2024: 110 * M, 2025: 121 * M}}, {"revenue_growth": {2025: 0.1}})
    assert set(_ids(three)) == {"revenue_growth_up"}
    # rose, fell, rose: one fall of three is not a bear trend, and not a bull trend
    mixed = _lg({"revenue": {2022: 100 * M, 2023: 110 * M, 2024: 105 * M, 2025: 120 * M}})
    assert not _ids(mixed)


def test_margins_returns_and_debt_to_equity_need_half_a_point():
    for key in ("operating_margin", "gross_margin", "return_on_equity", "debt_to_equity"):
        assert not _ids(_lg(computed={key: {2024: 0.179, 2025: 0.180}})), key    # 0.1 point
        assert not _ids(_lg(computed={key: {2024: 0.2000, 2025: 0.2049}})), key  # 0.49 point
        assert not _ids(_lg(computed={key: {2025: 0.30}})), key            # no prior year
        up = _ids(_lg(computed={key: {2024: 0.200, 2025: 0.205}}))         # exactly half a point
        down = _ids(_lg(computed={key: {2024: 0.205, 2025: 0.200}}))
        assert len(up) == 1 and len(down) == 1, key
        assert {s.side for s in up.values()} != {s.side for s in down.values()}, key
    # growth rates keep the tenth of a point
    rev = {"revenue": {2024: 100 * M, 2025: 100.2 * M}}
    assert set(_ids(_lg(rev, {"revenue_growth": {2025: 0.002}}))) == {"revenue_growth_up"}


def test_profitability_cash_and_balance_rules_need_their_facts():
    assert set(_ids(_lg({"net_income": {2025: -1 * M}}))) == {"net_loss"}
    assert not _ids(_lg({"net_income": {2025: 1 * M}}))
    assert not _ids(_lg({"cash": {2025: 50 * M}}))                         # no debt to compare
    assert set(_ids(_lg({"cash": {2025: 30 * M}, "long_term_debt": {2025: 40 * M}}))) == set()
    assert set(_ids(_lg({"shareholders_equity": {2025: -1 * M}}))) == {"negative_equity"}
    # free cash flow that does not change once formatted is not a change
    assert not _ids(_lg(computed={"free_cash_flow": {2024: 100.00 * M, 2025: 100.01 * M}}))
    # negative cash flow with no prior year still fires, on its own
    alone = _ids(_lg(computed={"free_cash_flow": {2025: -2 * M}}))
    assert alone["free_cash_flow_negative"].tokens == (("free_cash_flow", "FY2025"),)


def _conversion(ocf, ni=10 * M):
    lg = _lg({"net_income": {2025: ni}, "operating_cash_flow": {2025: ocf}})
    return lg, _ids(lg)


def test_cash_conversion_is_a_computed_fact_and_only_for_positive_net_income():
    lg, found = _conversion(7 * M)
    assert set(found) == {"cash_conversion_low"}
    f = lg.get("cash_conversion", "FY2025")
    assert f.is_computed and f.formula == "operating_cash_flow / net_income"
    assert f.inputs == (("operating_cash_flow", "FY2025"), ("net_income", "FY2025"))
    assert abs(f.value - 0.7) < 1e-12 and f.unit == "ratio"
    loss, found = _conversion(9 * M, ni=-10 * M)
    assert "cash_conversion_high" not in found and loss.get("cash_conversion", "FY2025") is None


def test_cash_conversion_bull_only_from_one_to_two_times_and_worded_plainly():
    for ocf, expected in ((10 * M, "cash_conversion_high"), (15 * M, "cash_conversion_high"),
                          (20 * M, "cash_conversion_high"), (7.9 * M, "cash_conversion_low")):
        lg, found = _conversion(ocf)
        assert set(found) == {expected}, ocf
        assert found[expected].template == (
            "Operating cash flow was [[F:cash_conversion|FY2025]] of net income in fiscal 2025, at "
            "[[F:operating_cash_flow|FY2025]] against [[F:net_income|FY2025]].")
        assert "matched or exceeded" not in found[expected].rule
    # above twice net income (earnings collapsed) and between the bounds: no point, and no fact
    for ocf in (20.1 * M, 38.87 * M, 9 * M, 8 * M):
        lg, found = _conversion(ocf)
        assert not found and lg.get("cash_conversion", "FY2025") is None, ocf


def test_per_share_rules():
    up_small = _lg({"shares_outstanding": {2024: 100 * M, 2025: 100.5 * M}})
    assert not _ids(up_small)                                              # under one per cent
    assert set(_ids(_lg({"shares_outstanding": {2024: 100 * M, 2025: 102 * M}}))) == {"share_count_up"}
    assert set(_ids(_lg({"eps_diluted": {2024: 2.0, 2025: 2.001}}))) == set()   # same once shown
    assert set(_ids(_lg({"dividends_per_share": {2024: 1.0}}))) == set()


def test_signals_twice_is_stable_and_ordered_by_weight_then_id():
    lg = _lg(**BULL)
    first = thesis.signals(lg)
    second = thesis.signals(lg)
    assert first == second and first
    assert [(-s.weight, s.id) for s in first] == sorted((-s.weight, s.id) for s in first)
    assert thesis.signals(Ledger()) == []


def test_every_template_survives_the_audit_with_its_figures_linked():
    for lg in _all_ledgers():
        for s in thesis.signals(lg):
            assert not re.search(r"\d", audit.PLACEHOLDER.sub(" ", s.rule))
            html, withheld = audit.apply(s.template, lg)
            assert withheld == [] and html.startswith("<p>"), (s.id, withheld)
            assert html.count("<a ") == len(audit.find_placeholders(s.template)) == len(s.tokens)
            assert set(audit.find_placeholders(s.template)) == set(s.tokens)
            assert _visible_digits(html) == [], (s.id, html)
        for dimension, tokens, template in thesis.thesis_lines(lg):
            html, withheld = audit.apply(template, lg)
            assert withheld == [] and html.count("<a ") == len(tokens), (dimension, template)
            assert _visible_digits(html) == []


# ---- build -------------------------------------------------------------------------------------
def _reply(bullets=None, thesis_lines=None):
    return json.dumps({"thesis": thesis_lines or {}, "bullets": bullets or {}})


def _fake(reply, calls=None):
    def ask(messages, *, session_id, **params):
        if calls is not None:
            calls.append((messages, session_id, params))
        if isinstance(reply, Exception):
            raise reply
        return reply
    return ask


def test_build_uses_clean_model_wording_with_linked_figures():
    lg = _lg(**BULL)
    found = thesis.signals(lg)
    calls = []
    reply = _reply({"revenue_growth_up": "Revenue grew to [[F:revenue|FY2025]] from [[F:revenue|FY2024]]."},
                   {"growth": "Revenue reached [[F:revenue|FY2025]] in fiscal 2025."})
    out = thesis.build(lg, {"name": "Orchard Inc.", "ticker": "ORC"}, session_id="conv-t",
                       found=found, ask=_fake(reply, calls))
    assert out["method"] == "model"
    item = next(b for b in out["bull"] if b["signal"] == "revenue_growth_up")
    assert item["method"] == "model" and item["html"].startswith("Revenue grew to <a")
    assert fmt.cited(lg.get("revenue", "FY2025"), lg) in item["html"]
    assert item["rule"] == "Revenue rose from the year before"
    assert out["thesis"][0] == {"title": "Growth", "method": "model",
                                "html": f"Revenue reached {fmt.cited(lg.get('revenue', 'FY2025'), lg)} in fiscal 2025."}
    assert all(b["method"] == "code" for b in out["bull"] if b["signal"] != "revenue_growth_up")
    # one call, the agreed parameters, tokens and directions in the prompt and no values
    assert len(calls) == 1
    messages, session_id, params = calls[0]
    assert session_id == "conv-t" and params == {"temperature": 0.2, "max_tokens": thesis.MAX_TOKENS}
    user = messages[1]["content"]
    assert "revenue_growth_up | bull | Revenue rose from the year before | tokens:" in user
    assert "[[F:revenue|FY2025]] | Revenue | fiscal 2025 | up" in user
    assert "[[F:revenue_growth|FY2025]] | Revenue growth | fiscal 2025 | none" in user
    assert "growth | Growth | the first token is higher than the second | tokens:" in user
    assert "  [[F:revenue|FY2022]] | Revenue | fiscal 2022 | none" in user
    assert "cash | Cash flow | no comparison: use no direction word | tokens:" in user
    for value in ("133100000", "133.1", "0.25", "25.0%", "10.0%", "18000000"):
        assert value not in user and value not in messages[0]["content"]
    assert out["counts"] == {"signals": len(found), "bull": len(out["bull"]), "bear": 0}


def test_typed_number_advice_contrary_direction_and_foreign_tokens_fall_back_to_code():
    lg = _lg(**BULL)
    found = thesis.signals(lg)
    bullets = {
        "revenue_growth_up": "Revenue rose 10% to [[F:revenue|FY2025]].",
        "operating_margin_up": "The operating margin widened to [[F:operating_margin|FY2025]], so investors should buy.",
        "free_cash_flow_up": "Free cash flow fell to [[F:free_cash_flow|FY2025]].",
        "cash_conversion_high": "Net income was [[F:net_income|FY2024]].",
    }
    out = thesis.build(lg, {}, session_id="s", found=found, ask=_fake(_reply(bullets)))
    by = {b["signal"]: b for b in out["bull"]}
    for sid in ("revenue_growth_up", "operating_margin_up", "free_cash_flow_up"):
        signal = next(s for s in found if s.id == sid)
        assert by[sid]["method"] == "code"
        assert by[sid]["html"] == audit.apply(signal.template, lg)[0][3:-4]
    assert "Revenue rose 10% to [figure]." in out["withheld"]
    assert "The operating margin widened to [figure], so investors should buy." in out["withheld"]
    assert "Free cash flow fell to [figure]." in out["withheld"]
    assert out["method"] == "code"


def test_model_failure_and_garbage_give_code_sentences(monkeypatch):
    lg = _lg(**BEAR)
    found = thesis.signals(lg)

    def broken(messages, *, session_id, **params):
        raise llm.LLMError("Nicrron answered HTTP 400")
    monkeypatch.setattr(llm, "call_llm", broken)              # the default ask goes through it
    out = thesis.build(lg, {}, session_id="s", found=found)
    assert out["bear"] and out["method"] == "code" and out["withheld"] == []
    assert all(i["method"] == "code" for i in out["thesis"] + out["bull"] + out["bear"])

    for reply in ("not json {oops", "", "[1, 2, 3]", json.dumps({"bullets": ["x"]}), None):
        again = thesis.build(lg, {}, session_id="s", found=found, ask=_fake(reply))
        assert again["method"] == "code" and len(again["bear"]) == len(out["bear"])
    assert thesis.build(lg, {}, session_id="s", found=found,
                        ask=_fake(RuntimeError("boom")))["bear"] == out["bear"]


def test_default_ask_is_resolved_at_call_time(monkeypatch):
    lg = _lg(**BULL)
    found = thesis.signals(lg)
    wrapped = ("Sure.\n```json\n" + _reply({"revenue_growth_up":
               "Revenue increased to [[F:revenue|FY2025]] from [[F:revenue|FY2024]]."}) + "\n```\nDone.")
    monkeypatch.setattr(llm, "call_llm", lambda messages, *, session_id, **params: wrapped)
    out = thesis.build(lg, {}, session_id="s", found=found)
    item = next(b for b in out["bull"] if b["signal"] == "revenue_growth_up")
    assert item["method"] == "model" and out["method"] == "model"


def test_at_most_four_per_side_spread_over_dimensions():
    lg = _lg(**BULL)
    found = thesis.signals(lg)
    out = thesis.build(lg, {}, session_id="s", found=found, ask=_fake("{}"))
    assert len(out["bull"]) == 4 and out["bear"] == []
    assert out["counts"] == {"signals": len(found), "bull": 4, "bear": 0}
    dims = [next(s for s in found if s.id == b["signal"]).dimension for b in out["bull"]]
    assert max(dims.count(d) for d in dims) <= 2
    assert len(out["thesis"]) == 4 and [t["title"] for t in out["thesis"]] == [
        "Growth", "Profitability", "Cash flow", "Balance sheet"]


def test_empty_ledger_and_found_none_give_empty_lists_without_a_call():
    calls = []
    lg = Ledger()
    out = thesis.build(lg, {}, session_id="s", found=thesis.signals(lg), ask=_fake("{}", calls))
    assert out == {"thesis": [], "bull": [], "bear": [], "withheld": [], "method": "code",
                   "counts": {"signals": 0, "bull": 0, "bear": 0}}
    full = _lg(**BULL)
    none = thesis.build(full, {}, session_id="s", found=None, ask=_fake("{}", calls))
    assert none["thesis"] == none["bull"] == none["bear"] == [] and none["method"] == "code"
    assert calls == []
    # anything in `found` that is not a Signal (e.g. risk passages) is ignored, never counted
    odd = thesis.build(full, {}, session_id="s", found=[{"text": "x"}, "y"], ask=_fake("{}"))
    assert odd["bull"] == odd["bear"] == [] and odd["counts"]["signals"] == 0


def test_no_typed_digit_reaches_the_html_and_the_ledger_is_unchanged():
    for spec in (BULL, BEAR, BEAR2, EDGE):
        lg = _lg(**spec)
        found = thesis.signals(lg)
        before = json.dumps(lg.to_json(), sort_keys=True)
        sneaky = {s.id: f"{s.rule} by 12 points to [[F:{s.tokens[0][0]}|{s.tokens[0][1]}]]." for s in found}
        for ask in (_fake("garbage"), _fake(_reply(sneaky, {"growth": "Revenue was 5 billion."}))):
            out = thesis.build(lg, {"name": "X"}, session_id="s", found=found, ask=ask)
            for item in out["thesis"] + out["bull"] + out["bear"]:
                assert not item["html"].startswith("<p>")
                assert _visible_digits(item["html"]) == [], item["html"]
        assert json.dumps(lg.to_json(), sort_keys=True) == before


def test_with_the_real_ratios_module():
    lg = Ledger()
    sid = lg.add_source(SRC)
    for y, end in ((2023, "2023-09-30"), (2024, "2024-09-28")):
        lg.set_period_end(f"FY{y}", end)
    values = {("revenue", "FY2024"): 391.035e9, ("revenue", "FY2023"): 383.285e9,
              ("operating_income", "FY2024"): 123.216e9, ("operating_income", "FY2023"): 114.301e9,
              ("net_income", "FY2024"): 93.736e9, ("net_income", "FY2023"): 96.995e9,
              ("operating_cash_flow", "FY2024"): 118.254e9, ("capex", "FY2024"): 9.447e9,
              ("cash", "2024-09-28"): 29.943e9, ("long_term_debt", "2024-09-28"): 85.75e9,
              ("shareholders_equity", "2024-09-28"): 56.95e9}
    for (key, period), v in values.items():
        lg.add_fact(Fact(key, period, v, metrics.METRICS[key].unit, source_ids=(sid,)))
    ratios.compute(lg)
    found = {s.id for s in thesis.signals(lg)}
    assert {"revenue_growth_up", "net_income_growth_down", "operating_margin_up",
            "cash_conversion_high"} <= found
    out = thesis.build(lg, {"name": "Orchard Inc."}, session_id="s", found=thesis.signals(lg),
                       ask=_fake("{}"))
    assert out["bull"] and out["bear"] and len(out["thesis"]) == 4
    assert all("<a " in i["html"] for i in out["thesis"] + out["bull"] + out["bear"])


def test_a_reply_cut_off_before_the_json_closes_is_still_used():
    from backend.draft import thesis as t
    cut = ('{"thesis": {"growth": "Revenue was [[F:revenue|FY2025]].", "cash": "Free cash flow was [[F:free_cash_flow|FY2025]]."}, '
           '"bullets": {"revenue_growth_up": "Revenue rose to [[F:revenue|FY2025]].", '
           '"operating_margin_up": "The operating margin widened to [[F:operating_margin|FY2025]].", '
           '"free_cash_flow_up": "Free cash flow rose to [[F:free')            # cut off mid-sentence
    assert t.parse_reply(cut) is None or "bullets" not in t.parse_reply(cut)   # strict parsing cannot use it
    got = t.salvage(cut, {"growth", "cash"}, {"revenue_growth_up", "operating_margin_up", "free_cash_flow_up"})
    assert got["thesis"] == {"growth": "Revenue was [[F:revenue|FY2025]].", "cash": "Free cash flow was [[F:free_cash_flow|FY2025]]."}
    assert set(got["bullets"]) == {"revenue_growth_up", "operating_margin_up"}      # the cut-off one is not taken
    assert t.salvage(None, set(), set()) == {"thesis": {}, "bullets": {}}
    assert t.salvage('{"other": "x"}', {"growth"}, {"a"}) == {"thesis": {}, "bullets": {}}


def test_a_metric_the_company_stopped_reporting_years_ago_makes_no_point():
    """Free cash flow held only for old years (the capital-spending tag changed) must not give a
    bull point about a year long past."""
    from backend.ledger import Fact, Ledger, Source
    led = Ledger()
    sid = led.add_source(Source(id="", type="edinet", url="https://www.sec.gov/x", title="10-K", date="2026-02-01", snippet=""))
    for year, rev in ((2024, 100.0), (2025, 130.0), (2026, 216.0)):
        led.add_fact(Fact(key="revenue", period=f"FY{year}", value=rev * 1e9, unit="USD", source_ids=(sid,)))
    for year, ocf, capex in ((2011, 0.7, 0.1), (2012, 0.9, 0.13)):
        led.add_fact(Fact(key="operating_cash_flow", period=f"FY{year}", value=ocf * 1e9, unit="USD", source_ids=(sid,)))
        led.add_fact(Fact(key="capex", period=f"FY{year}", value=capex * 1e9, unit="USD", source_ids=(sid,)))
    ratios.compute(led)
    assert led.get("free_cash_flow", "FY2012") is not None          # the old figure exists
    found = thesis.signals(led)
    assert not [s for s in found if s.id.startswith(("free_cash_flow", "cash_conversion"))]
    assert all("FY2012" not in str(s.tokens) and "FY2011" not in str(s.tokens) for s in found)
    assert any(s.id == "revenue_growth_up" for s in found)          # the current year still speaks
    assert all("2012" not in text for _d, _t, text in thesis.thesis_lines(led))


# ---- review round 1: banks, the growth line, negative bases ----------------------------------
def _bank_like():
    spec = {k: dict(v) for k, v in BULL["reported"].items()}
    spec["total_assets"] = {2025: 4000 * M}
    return _lg(spec, BULL["computed"])


def test_financial_companies_skip_the_cash_debt_and_gross_margin_rules():
    off = _ids(_bank_like())
    lg = _bank_like()
    on = {s.id: s for s in thesis.signals(lg, financial=True)}
    assert thesis.NOT_FOR_FINANCIALS & set(off)                    # they fire for an industrial
    assert not thesis.NOT_FOR_FINANCIALS & set(on)                 # and never for a bank
    assert set(off) - thesis.NOT_FOR_FINANCIALS == set(on)         # the other rules are untouched
    assert {"revenue_growth_up", "operating_margin_up", "return_on_equity_up", "eps_diluted_up"} <= set(on)
    assert lg.get("cash_conversion", "FY2025") is None             # no fact added for a bank
    for spec in (BEAR, BEAR2, EDGE):
        assert not thesis.NOT_FOR_FINANCIALS & {s.id for s in thesis.signals(_lg(**spec), financial=True)}


def test_financial_thesis_lines_have_no_cash_line_and_an_assets_and_equity_balance_line():
    lg = _bank_like()
    plain = {d: (t, x) for d, t, x in thesis.thesis_lines(lg)}
    bank = {d: (t, x) for d, t, x in thesis.thesis_lines(lg, financial=True)}
    assert set(plain) == {"growth", "profitability", "cash", "balance_sheet"}
    assert set(bank) == {"growth", "profitability", "balance_sheet"}
    assert plain["balance_sheet"][0][0] == ("cash", "2025-12-31")
    assert bank["balance_sheet"] == (
        (("total_assets", "2025-12-31"), ("shareholders_equity", "2025-12-31")),
        "At the end of fiscal 2025 total assets were [[F:total_assets|2025-12-31]] and shareholders' "
        "equity was [[F:shareholders_equity|2025-12-31]].")
    for _d, tokens, template in thesis.thesis_lines(lg, financial=True):
        html, withheld = audit.apply(template, lg)
        assert withheld == [] and html.count("<a ") == len(tokens) and _visible_digits(html) == []
    # only one of the two balances held: the line keeps what there is
    only_equity = _lg({"revenue": {2025: 1 * M}, "shareholders_equity": {2025: 5 * M}})
    assert dict((d, t) for d, t, _x in thesis.thesis_lines(only_equity, financial=True))["balance_sheet"] == (
        ("shareholders_equity", "2025-12-31"),)
    out = thesis.build(lg, {}, session_id="s", found=thesis.signals(lg, financial=True),
                       ask=_fake("{}"), financial=True)
    assert [t["title"] for t in out["thesis"]] == ["Growth", "Profitability", "Balance sheet"]
    assert not {b["signal"] for b in out["bull"] + out["bear"]} & thesis.NOT_FOR_FINANCIALS
    assert [t["title"] for t in thesis.build(lg, {}, session_id="s", found=[], ask=_fake("{}"))["thesis"]] == [
        "Growth", "Profitability", "Cash flow", "Balance sheet"]


def test_growth_line_takes_the_three_year_view_and_falls_back():
    lg = _lg(**BULL)
    lines = {d: (t, x) for d, t, x in thesis.thesis_lines(lg)}
    assert lines["growth"] == ((("revenue", "FY2025"), ("revenue", "FY2022")),
                               "Revenue was [[F:revenue|FY2025]] in fiscal 2025, against "
                               "[[F:revenue|FY2022]] in fiscal 2022.")
    first_bull = thesis.signals(lg)[0]
    assert first_bull.id == "revenue_growth_up" and first_bull.template != lines["growth"][1]
    assert not any(k.endswith("_growth") for k, _p in lines["growth"][0])     # no growth rate
    # three years earlier not held: today's line with the growth rate, then revenue alone
    short = _lg({"revenue": {2024: 100 * M, 2025: 110 * M}}, {"revenue_growth": {2025: 0.1}})
    assert dict((d, x) for d, _t, x in thesis.thesis_lines(short))["growth"] == (
        "Revenue was [[F:revenue|FY2025]] in fiscal 2025, a change of [[F:revenue_growth|FY2025]] "
        "from the year before.")
    alone = _lg({"revenue": {2025: 110 * M}})
    assert dict((d, x) for d, _t, x in thesis.thesis_lines(alone))["growth"] == (
        "Revenue was [[F:revenue|FY2025]] in fiscal 2025.")


def test_thesis_wording_may_only_use_the_direction_its_line_shows():
    rose = "Revenue rose to [[F:revenue|FY2025]] from [[F:revenue|FY2022]] in fiscal 2022."
    up = _lg(**BULL)              # 133.1 against 100: up
    out = thesis.build(up, {}, session_id="s", found=[], ask=_fake(_reply({}, {
        "growth": rose, "cash": "Operating cash flow rose to [[F:operating_cash_flow|FY2025]]."})))
    by = {t["title"]: t for t in out["thesis"]}
    assert by["Growth"]["method"] == "model"
    assert by["Cash flow"]["method"] == "code"                     # no comparison, no direction word
    assert "Operating cash flow rose to [figure]." in out["withheld"]
    down = _lg(**BEAR)            # 100 against 133: down, so "rose" is refused
    out = thesis.build(down, {}, session_id="s", found=[], ask=_fake(_reply({}, {"growth": rose})))
    assert out["thesis"][0]["method"] == "code" and "Revenue rose to [figure] from [figure] in fiscal 2022." in out["withheld"]
    assert thesis.line_direction(up, (("revenue", "FY2025"), ("revenue", "FY2022"))) == "up"
    assert thesis.line_direction(down, (("revenue", "FY2025"), ("revenue", "FY2022"))) == "down"
    assert thesis.line_direction(up, (("operating_cash_flow", "FY2025"),)) is None


def _real(values, ends=((2024, "2024-12-31"), (2025, "2025-12-31"))):
    lg = Ledger()
    sid = lg.add_source(SRC)
    for y, end in ends:
        lg.set_period_end(f"FY{y}", end)
    for (key, period), v in values.items():
        lg.add_fact(Fact(key, period, v, metrics.METRICS[key].unit, source_ids=(sid,)))
    ratios.compute(lg)
    return lg


def test_no_growth_point_from_or_to_a_negative_base():
    # profit to loss: the ratios module gives -108.5%, which is not a meaningful growth rate
    swing = _real({("revenue", "FY2024"): 4100 * M, ("revenue", "FY2025"): 4040.6 * M,
                   ("net_income", "FY2024"): 950.1 * M, ("net_income", "FY2025"): -81.2 * M,
                   ("operating_income", "FY2024"): 127 * M, ("operating_income", "FY2025"): -80 * M,
                   ("eps_diluted", "FY2024"): 15.88, ("eps_diluted", "FY2025"): -1.50})
    assert swing.get("net_income_growth", "FY2025").value is not None
    found = {s.id: s for s in thesis.signals(swing)}
    assert "net_income_growth_down" not in found and "net_income_growth_up" not in found
    assert found["net_loss"].template == (
        "The company reported a net loss in fiscal 2025, with net income of [[F:net_income|FY2025]] "
        "against [[F:net_income|FY2024]] a year earlier.")
    # a loss is not "fell to minus X": the signed wording has no direction word
    assert found["eps_diluted_down"].template == (
        "Diluted earnings per share were [[F:eps_diluted|FY2025]] in fiscal 2025, against "
        "[[F:eps_diluted|FY2024]] a year earlier.")
    assert found["operating_margin_down"].template.startswith("The operating margin was ")
    # loss to profit: the ratios module marks the growth rate not meaningful (None): no point
    back = _real({("net_income", "FY2024"): -50 * M, ("net_income", "FY2025"): 30 * M})
    assert back.get("net_income_growth", "FY2025").value is None
    assert not [s for s in thesis.signals(back) if s.id.startswith("net_income_growth")]
    # no point anywhere cites a fact without a value
    for lg in (swing, back, *_all_ledgers()):
        for s in thesis.signals(lg):
            assert all(lg.get(*tok) is not None and lg.get(*tok).value is not None for tok in s.tokens), s.id
            html, withheld = audit.apply(s.template, lg)
            assert withheld == [] and _visible_digits(html) == [], s.id


def test_profitability_line_does_not_restate_the_margin_point():
    lg = _real({("revenue", "FY2024"): 4100 * M, ("revenue", "FY2025"): 4040.6 * M,
                ("operating_income", "FY2024"): 127 * M, ("operating_income", "FY2025"): -80 * M,
                ("net_income", "FY2024"): 950.1 * M, ("net_income", "FY2025"): -81.2 * M})
    lines = {d: (t, x) for d, t, x in thesis.thesis_lines(lg)}
    assert lines["profitability"] == (
        (("operating_margin", "FY2025"), ("net_margin", "FY2025")),
        "The operating margin was [[F:operating_margin|FY2025]] in fiscal 2025 and the net margin "
        "[[F:net_margin|FY2025]].")
    point = next(s for s in thesis.signals(lg) if s.id == "operating_margin_down")
    assert point.template != lines["profitability"][1] and set(point.tokens) != set(lines["profitability"][0])
    assert thesis.line_direction(lg, lines["profitability"][0]) is None      # two metrics: no direction word
    # a bank with no operating income still gets a profitability line from the net margin
    bank = _real({("revenue", "FY2025"): 100 * M, ("net_income", "FY2025"): 30 * M})
    assert dict((d, x) for d, _t, x in thesis.thesis_lines(bank, financial=True))["profitability"] == (
        "The net margin was [[F:net_margin|FY2025]] in fiscal 2025.")


def test_a_direction_word_around_a_negative_figure_falls_back_to_the_neutral_sentence():
    """"The operating margin widened to -66.5% from -94.3%" reads as worse when the loss narrowed."""
    from backend.ledger import Fact, Ledger, Source
    led = Ledger()
    sid = led.add_source(Source(id="", type="edinet", url="https://www.sec.gov/x", title="10-K", date="2026-02-01", snippet=""))
    for year, rev, op in ((2024, 100.0, -94.3), (2025, 100.0, -66.5)):
        led.add_fact(Fact(key="revenue", period=f"FY{year}", value=rev, unit="USD", source_ids=(sid,)))
        led.add_fact(Fact(key="operating_income", period=f"FY{year}", value=op, unit="USD", source_ids=(sid,)))
    ratios.compute(led)
    tokens = (("operating_margin", "FY2025"), ("operating_margin", "FY2024"))
    withheld = []
    model = "The operating margin widened to [[F:operating_margin|FY2025]] from [[F:operating_margin|FY2024]]."
    neutral = "The operating margin was [[F:operating_margin|FY2025]] in fiscal 2025, against [[F:operating_margin|FY2024]] a year earlier."
    html, method = thesis._word(led, model, neutral, tokens, None, withheld)
    assert method == "code" and "widened" not in html and len(withheld) == 1
    assert thesis._negative_with_direction(led, model, tokens) is True
    assert thesis._negative_with_direction(led, neutral, tokens) is False
