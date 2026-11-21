import json

import pytest

import llm
from backend.draft import writer
from backend.ledger import Fact, Ledger, Source


def _ledger():
    lg = Ledger()
    sid = lg.add_source(Source("x", "edinet", "https://www.sec.gov/a", "10-K", "2024-11-01"))
    lg.add_fact(Fact("revenue", "FY2024", 391035000000, "USD", source_ids=(sid,)))
    lg.add_fact(Fact("revenue", "FY2023", 383285000000, "USD", source_ids=(sid,)))
    lg.add_fact(Fact("net_income", "FY2024", 93736000000, "USD", source_ids=(sid,)))
    lg.add_fact(Fact("net_income", "FY2023", 96995000000, "USD", source_ids=(sid,)))
    lg.add_fact(Fact("net_margin", "FY2024", 0.2397123, "ratio", inputs=(("net_income", "FY2024"), ("revenue", "FY2024")),
                     formula="net_income / revenue"))
    return lg


def test_packet_has_no_values_and_directions():
    packet = writer.build_packet(_ledger(), {"name": "Apple Inc.", "ticker": "AAPL"})
    dumped = json.dumps(packet)
    for v in ("391035000000", "383285000000", "93736000000", "96995000000", "0.2397", "391.0", "23.97"):
        assert v not in dumped
    by = {f["token"]: f for f in packet["facts"]}
    assert by["[[F:revenue|FY2024]]"]["direction"] == "up"
    assert by["[[F:net_income|FY2024]]"]["direction"] == "down"
    assert by["[[F:net_margin|FY2024]]"]["kind"] == "computed"
    assert by["[[F:revenue|FY2023]]"]["direction"] is None
    assert packet["periods"] == ["FY2024", "FY2023"]


def test_write_sections_retry_and_failures(monkeypatch):
    packet = writer.build_packet(_ledger(), {"name": "Apple Inc.", "ticker": "AAPL"})
    sessions, fails = [], {"n": 0}

    def ok(messages, *, session_id, **params):
        sessions.append(session_id)
        assert messages[0]["role"] == "system" and params["temperature"] == 0.2 and params["max_tokens"] == 700
        return "Revenue rose to [[F:revenue|FY2024]]."
    monkeypatch.setattr(llm, "call_llm", ok)
    assert set(writer.write_sections(packet, session_id="conv-x", sleep=lambda s: None)) == set(writer.SECTIONS)
    assert sessions and set(sessions) == {"conv-x"}

    pauses = []

    def flaky(messages, *, session_id, **params):
        if "Section: Results" in messages[1]["content"] and fails["n"] < 2:
            fails["n"] += 1
            raise llm.LLMError("Nicrron answered HTTP 429")
        if "Section: Cash flow" in messages[1]["content"]:
            return "NOT COVERED"
        return "Text."
    monkeypatch.setattr(llm, "call_llm", flaky)
    out = writer.write_sections(packet, session_id="conv-y", sleep=pauses.append)
    assert "results" in out and "cash_flow" not in out and fails["n"] == 2 and pauses == [2.0, 5.0]

    def broken(messages, *, session_id, **params):
        raise llm.LLMError("Nicrron answered HTTP 503")
    monkeypatch.setattr(llm, "call_llm", broken)
    assert writer.write_sections(packet, session_id="conv-z", sleep=lambda s: None) == {}


def test_fallback_overview_is_built_from_linked_ledger_figures():
    from backend.ledger import Fact, Ledger, Source
    from backend.draft import writer
    lg = Ledger()
    sid = lg.add_source(Source("x", "edinet", "https://www.sec.gov/Archives/edgar/data/1/a", "Form 10-K", "2024-11-01"))
    lg.add_fact(Fact("revenue", "FY2024", 391035000000, "USD", source_ids=(sid,)))
    lg.add_fact(Fact("net_income", "FY2024", 93736000000, "USD", source_ids=(sid,)))
    html = writer.fallback_overview(lg, {"name": "Orchard <Devices> Inc.", "ticker": "SMPL"})
    assert html.startswith("<p>Orchard &lt;Devices&gt; Inc. reported revenue of <a")
    assert html.count("https://www.sec.gov/") == 2 and "fiscal 2024" in html
    assert writer.fallback_overview(Ledger(), {"name": "X"}) == ""



# ---- 2026-11-22 bug-hunt round ---------------------------------------------------------------
def _five_years():
    """FY2021-FY2025: revenue, net income, a growth rate, a balance with year ends, a stale debt
    figure that stops in FY2023, and one valuation fact."""
    lg = Ledger()
    sid = lg.add_source(Source("x", "edinet", "https://www.sec.gov/a", "10-K", "2026-02-01"))
    revenue = {2021: 300e9, 2022: 320e9, 2023: 350e9, 2024: 371433e6, 2025: 371444e6}
    income = {2021: 60e9, 2022: 55e9, 2023: 70e9, 2024: 20e9, 2025: -5e9}
    for y in range(2021, 2026):
        lg.set_period_end(f"FY{y}", f"{y}-12-31")
        lg.add_fact(Fact("revenue", f"FY{y}", revenue[y], "USD", source_ids=(sid,)))
        lg.add_fact(Fact("net_income", f"FY{y}", income[y], "USD", source_ids=(sid,)))
        lg.add_fact(Fact("total_assets", f"{y}-12-31", 1000e9 + y, "USD", source_ids=(sid,)))
    for y in (2022, 2023):
        lg.add_fact(Fact("long_term_debt", f"{y}-12-31", 125e6, "USD", source_ids=(sid,)))
    lg.add_fact(Fact("revenue_growth", "FY2025", 0.00003, "ratio",
                     inputs=(("revenue", "FY2025"), ("revenue", "FY2024")), formula="revenue / prior - 1"))
    lg.add_fact(Fact("revenue_growth_estimate", "FY2025", 0.05, "ratio",
                     inputs=(("revenue", "FY2025"),), formula="blend"))
    return lg


def test_packet_holds_the_latest_year_first_and_nothing_stale():
    packet = writer.build_packet(_five_years(), {"name": "X", "ticker": "X"})
    tokens = [f["token"] for f in packet["facts"]]
    years = [f["year"] for f in packet["facts"]]
    assert years == sorted(years, reverse=True) and years[0] == 2025          # latest year first
    assert [f["role"] for f in packet["facts"]][:4] == ["latest"] * 4
    # the year before for every metric; older years only for revenue and net income
    assert "[[F:total_assets|2024-12-31]]" in tokens and "[[F:total_assets|2023-12-31]]" not in tokens
    assert "[[F:revenue|FY2023]]" in tokens and "[[F:net_income|FY2022]]" in tokens
    assert "[[F:revenue|FY2021]]" not in tokens                               # at most two older years
    # a metric the latest year lacks is not in the packet at all; nor is the valuation arithmetic
    assert not any("long_term_debt" in t for t in tokens)
    assert not any("estimate" in t for t in tokens)
    assert packet["periods"] == ["FY2025", "FY2024", "FY2023", "FY2022"]


def test_equal_once_formatted_is_little_changed_and_growth_has_no_direction():
    packet = writer.build_packet(_five_years(), {"name": "X", "ticker": "X"})
    by = {f["token"]: f for f in packet["facts"]}
    assert by["[[F:revenue|FY2025]]"]["direction"] == "flat"     # $371.4 billion against $371.4 billion
    assert by["[[F:revenue|FY2024]]"]["direction"] == "up"
    growth = by["[[F:revenue_growth|FY2025]]"]
    assert growth["direction"] is None and growth["rate"] is True and "sign" not in growth
    assert by["[[F:net_income|FY2025]]"]["sign"] == "turned negative"
    user = writer.prompt_for("results", packet)[1]["content"]
    assert "[[F:revenue|FY2025]]: Revenue, fiscal 2025 (reported; was little changed from the year before)" in user
    assert "a growth rate: state it plainly, never say it rose or fell" in user
    assert "turned negative from a positive figure the year before" in user
    assert user.index("Latest fiscal year (fiscal 2025)") < user.index("The year before (fiscal 2024)") \
        < user.index("Older years")
    system = writer.prompt_for("results", packet)[0]["content"]
    assert '"was little changed at"' in system and "never say a growth rate rose, fell" in system
    assert "at most two periods of the same figure in one sentence" in system
    assert "LATEST fiscal year" in system and "never as the subject" in system
    assert "the most recent figure available" in system


def test_overview_prompt_is_about_the_company_not_the_data():
    packet = writer.build_packet(_five_years(), {"name": "X", "ticker": "X"})
    system, user = (m["content"] for m in writer.prompt_for("overview", packet))
    assert "Write two or three sentences on the company's latest fiscal year" in user
    assert "revenue" in user and "net income" in user and "operating margin" in user
    assert "one most notable change from the year before" in user
    assert "never describe the dataset, never count the years, never write \"the figures cover\"" in system
    assert "what the figures listed cover" not in user


@pytest.mark.parametrize("reply, expected", [
    ("Revenue rose to [[F:revenue|FY2024]]. Net margin rose to [figure] from [[F:net_margin|FY2024",
     "Revenue rose to [[F:revenue|FY2024]]."),
    ("Revenue rose to [[F:revenue|FY2024]].\n\nThe figures for UnitedHealth Group cover four fiscal years of reported income",
     "Revenue rose to [[F:revenue|FY2024]]."),
    ("Revenue rose to [[F:revenue|FY2024]]. Net income fell.\n\nIn fiscal 2025, cash con",
     "Revenue rose to [[F:revenue|FY2024]]. Net income fell."),
    ('Revenue rose to [[F:revenue|FY2024]] (see Item 7.) It was "the highest."',
     'Revenue rose to [[F:revenue|FY2024]] (see Item 7.) It was "the highest."'),
    ("Revenue rose to [[F:revenue|FY2024]]!", "Revenue rose to [[F:revenue|FY2024]]!"),
    ("In fiscal 2025, cash con", ""),
    ("Net margin rose to [[F:net_margin|FY2024", ""),
    ("", ""),
])
def test_an_unfinished_final_sentence_is_dropped(reply, expected):
    assert writer.drop_unfinished(reply) == expected


def test_a_section_that_is_only_a_fragment_is_not_written(monkeypatch):
    packet = writer.build_packet(_ledger(), {"name": "Apple Inc.", "ticker": "AAPL"})

    def fake(messages, *, session_id, **params):
        if "Section: Results" in messages[1]["content"]:
            return "The figures for UnitedHealth Group cover four fiscal years of reported income"
        return "Revenue rose to [[F:revenue|FY2024]]. Net income fell to [[F:net_income|FY2"
    monkeypatch.setattr(llm, "call_llm", fake)
    out = writer.write_sections(packet, session_id="conv-f", sleep=lambda s: None)
    assert "results" not in out
    assert out["overview"] == "Revenue rose to [[F:revenue|FY2024]]."


def _sections_ledger():
    lg = Ledger()
    sid = lg.add_source(Source("x", "edinet", "https://www.sec.gov/a", "10-K", "2026-02-01"))
    for y, (rev, ni, ta, eq, ocf, capex) in {2024: (100e9, 10e9, 500e9, 200e9, 30e9, 5e9),
                                            2025: (120e9, 10.04e9, 450e9, 210e9, 25e9, 6e9)}.items():
        lg.set_period_end(f"FY{y}", f"{y}-12-31")
        for key, value in (("revenue", rev), ("net_income", ni), ("operating_cash_flow", ocf), ("capex", capex)):
            lg.add_fact(Fact(key, f"FY{y}", value, "USD", source_ids=(sid,)))
        for key, value in (("total_assets", ta), ("shareholders_equity", eq)):
            lg.add_fact(Fact(key, f"{y}-12-31", value, "USD", source_ids=(sid,)))
        lg.add_fact(Fact("operating_margin", f"FY{y}", 0.2 + (y - 2024) * 0.01, "ratio",
                         inputs=(("revenue", f"FY{y}"),), formula="operating_income / revenue"))
    return lg


@pytest.mark.parametrize("section, words", [
    ("results", ["Revenue rose to [[F:revenue|FY2025]] in fiscal 2025 from [[F:revenue|FY2024]] in fiscal 2024.",
                 "Net income was little changed at [[F:net_income|FY2025]] in fiscal 2025, against "
                 "[[F:net_income|FY2024]] in fiscal 2024.",
                 "Operating margin rose to [[F:operating_margin|FY2025]]"]),
    ("financial_position", ["fell to [[F:total_assets|2025-12-31]] at the end of fiscal 2025 from "
                            "[[F:total_assets|2024-12-31]] at the end of fiscal 2024.",
                            "rose to [[F:shareholders_equity|2025-12-31]]"]),
    ("cash_flow", ["Operating cash flow fell to [[F:operating_cash_flow|FY2025]]",
                   "rose to [[F:capex|FY2025]] in fiscal 2025"]),
])
def test_fallback_sections_are_built_from_existing_facts_and_pass_the_audit(section, words):
    from backend import format as fmt
    from backend.verify import audit
    lg = _sections_ledger()
    text = writer.fallback_section(section, lg, {"name": "X"})
    for w in words:
        assert w in text, (w, text)
    assert 2 <= len(audit.sentences(text)) <= 3
    html, withheld = audit.apply(text, lg)
    assert withheld == []
    # unchanged in meaning: the same (escaped) words, each token now its linked value
    import html as _html
    parts, pos = [], 0
    for m in audit.PLACEHOLDER.finditer(text):
        parts += [_html.escape(text[pos:m.start()]), fmt.cited(lg.get(m.group(1), m.group(2)), lg)]
        pos = m.end()
    parts.append(_html.escape(text[pos:]))
    assert html == "<p>" + "".join(parts) + "</p>"


def test_fallback_section_is_empty_when_too_few_facts():
    lg = Ledger()
    sid = lg.add_source(Source("x", "edinet", "https://www.sec.gov/a", "10-K", "2026-02-01"))
    lg.add_fact(Fact("revenue", "FY2025", 1e9, "USD", source_ids=(sid,)))
    assert writer.fallback_section("results", lg, {}) == ""            # one sentence only
    assert writer.fallback_section("overview", _sections_ledger(), {}) == ""
    assert writer.fallback_section("cash_flow", Ledger(), {}) == ""
    one = Ledger()
    sid = one.add_source(Source("x", "edinet", "https://www.sec.gov/a", "10-K", "2026-02-01"))
    one.add_fact(Fact("revenue", "FY2025", 1e9, "USD", source_ids=(sid,)))
    one.add_fact(Fact("net_income", "FY2025", -2e8, "USD", source_ids=(sid,)))
    one.add_fact(Fact("net_income", "FY2024", 3e8, "USD", source_ids=(sid,)))
    text = writer.fallback_section("results", one, {})
    assert text == ("Revenue was [[F:revenue|FY2025]] in fiscal 2025. Net income was [[F:net_income|FY2025]] "
                    "in fiscal 2025, against [[F:net_income|FY2024]] in fiscal 2024.")
