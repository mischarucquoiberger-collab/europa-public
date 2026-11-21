"""Report chat: offline (llm.call_llm is faked in every test that could reach it)."""
import json
import re

import pytest

import llm
from backend import chat, settings
from backend import format as fmt
from backend.ledger import Fact, Ledger, Source

SEC_URL = "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm"


def _ledger() -> Ledger:
    led = Ledger()
    sid = led.add_source(Source(id="", type="edinet", url=SEC_URL, title="Apple 10-K 2024",
                                date="2024-11-01", snippet="Form 10-K"))
    for year, rev, ni in ((2022, 394.328e9, 99.803e9), (2023, 383.285e9, 96.995e9),
                          (2024, 391.035e9, 93.736e9)):
        led.add_fact(Fact(key="revenue", period=f"FY{year}", value=rev, unit="USD", source_ids=(sid,)))
        led.add_fact(Fact(key="net_income", period=f"FY{year}", value=ni, unit="USD", source_ids=(sid,)))
        led.add_fact(Fact(key="net_margin", period=f"FY{year}", value=ni / rev, unit="ratio",
                          inputs=(("net_income", f"FY{year}"), ("revenue", f"FY{year}")),
                          formula="net_income / revenue"))
    return led


COMPANY = {"name": "Apple Inc.", "ticker": "AAPL"}


class FakeModel:
    def __init__(self, reply="", error=False):
        self.reply, self.error, self.calls = reply, error, []

    def __call__(self, messages, *, session_id, model=None, **params):
        self.calls.append({"messages": messages, "session_id": session_id})
        if self.error:
            raise llm.LLMError("offline")
        return self.reply


@pytest.fixture
def model(monkeypatch):
    fake = FakeModel()
    monkeypatch.setattr(llm, "call_llm", fake)
    return fake


def test_resolve_named_year_latest_and_advice():
    led = _ledger()
    r = chat.resolve("What was revenue in 2023?", led)
    assert r["metrics"] == ["revenue"] and r["periods"] == ["FY2023"] and not r["advice"]
    r = chat.resolve("latest net income", led)
    assert r["metrics"] == ["net_income"] and r["periods"] == ["FY2024"]
    assert chat.resolve("Should I buy the stock?", led)["advice"] is True
    r = chat.resolve("What was the net margin last year?", led)
    assert r["metrics"] == ["net_margin"] and r["periods"] == ["FY2024"]


def test_covered_question_calls_model_once_and_links_value(model):
    led = _ledger()
    model.reply = "Revenue for fiscal 2023 came in at [[F:revenue|FY2023]]."
    model.reply = "Revenue for that year came in at [[F:revenue|FY2023]]."
    a = chat.answer("What was revenue in 2023?", led, COMPANY, session_id="t-1")
    assert len(model.calls) == 1
    assert a.kind == "answer"
    assert fmt.cited(led.get("revenue", "FY2023"), led) in a.html
    prompt = json.dumps(model.calls[0]["messages"])
    assert "[[F:revenue|FY2023]]" in prompt and "383" not in prompt  # tokens only, no values
    without_links = re.sub(r"<a [^>]*>.*?</a>", "", a.html)
    assert not re.search(r"\d", without_links)
    assert [c["url"] for c in a.citations] == [SEC_URL]


def test_uncovered_year_is_dont_know_without_model(model):
    led = _ledger()
    a = chat.answer("What was revenue in 2015?", led, COMPANY, session_id="t-2")
    assert a.kind == "dont_know" and model.calls == []
    assert a.text.startswith(chat.DONT_KNOW)
    assert chat.covered(led, ["revenue"]) in a.text          # the asked metric's own years
    assert "billion" not in a.text and "$" not in a.text and a.citations == []


def test_unknown_metric_is_dont_know_without_model(model):
    a = chat.answer("How many employees does it have?", _ledger(), COMPANY, session_id="t-3")
    assert a.kind == "dont_know" and model.calls == []
    assert a.text.startswith(chat.DONT_KNOW)


def test_advice_bait_is_refused_without_model(model):
    led = _ledger()
    a = chat.answer("Should I buy the stock given its revenue?", led, COMPANY, session_id="t-4")
    assert a.kind == "no_advice" and model.calls == []
    assert a.text.startswith(chat.NO_ADVICE)
    assert not re.search(r"\b(buy|sell|hold|undervalued|recommend)\b", a.text.replace(chat.NO_ADVICE, ""), re.I)
    assert fmt.cited(led.get("revenue", "FY2024"), led) in a.html


def test_invented_number_is_withheld_and_fallback_used(model):
    led = _ledger()
    model.reply = "Revenue was 999 billion."
    a = chat.answer("What was revenue in 2024?", led, COMPANY, session_id="t-5")
    assert "999" not in a.html and "999" not in a.text
    assert fmt.cited(led.get("revenue", "FY2024"), led) in a.html
    assert a.kind == "answer" and a.citations


def test_model_error_gives_fallback(monkeypatch):
    fake = FakeModel(error=True)
    monkeypatch.setattr(llm, "call_llm", fake)
    led = _ledger()
    a = chat.answer("What was net income in 2022?", led, COMPANY, session_id="t-6")
    assert len(fake.calls) == 1 and a.kind == "answer"
    assert fmt.cited(led.get("net_income", "FY2022"), led) in a.html


def test_not_covered_reply_gives_fallback(model):
    led = _ledger()
    model.reply = "NOT COVERED"
    a = chat.answer("latest net income", led, COMPANY, session_id="t-7")
    assert fmt.cited(led.get("net_income", "FY2024"), led) in a.html


def _save(led: Ledger, name="report_AAPL_abcd1234.html"):
    d = settings.reports_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text("<html></html>")
    data = led.to_json()
    data["company"] = COMPANY
    (d / name.replace(".html", ".ledger.json")).write_text(json.dumps(data))
    return name


def _events(chunks):
    out = []
    for chunk in chunks:
        if chunk.startswith(":"):
            continue
        lines = chunk.strip().split("\n")
        assert lines[0].startswith("event: ") and lines[1].startswith("data: ") and len(lines) == 2
        out.append((lines[0][7:], json.loads(lines[1][6:])))
    return out


def test_stream_one_text_then_done(model):
    name = _save(_ledger())
    model.reply = "Revenue was [[F:revenue|FY2024]]."
    ev = _events(chat.stream({"file": name, "messages": [{"role": "user", "content": "latest revenue"}]}))
    assert [e for e, _ in ev] == ["text", "done"]
    text = ev[0][1]["text"]
    # the interface renders Markdown, not HTML: the figure is a Markdown link to its filing,
    # and the filing is listed again under Sources
    assert "<a" not in text and "&#x27;" not in text and "<p>" not in text
    assert "](https://www.sec.gov/" in text
    assert "\n\nSources:\n- [" in text
    assert model.calls[0]["session_id"] == "chat-abcd1234"


def test_stream_by_job_id(model):
    _save(_ledger())
    model.reply = "NOT COVERED"
    ev = _events(chat.stream({"job_id": "abcd1234" + "0" * 24,
                              "messages": [{"role": "user", "content": "latest revenue"}]}))
    assert [e for e, _ in ev] == ["text", "done"]


def test_stream_unknown_report_and_bad_input(model):
    ev = _events(chat.stream({"file": "report_AAPL_ffffffff.html",
                              "messages": [{"role": "user", "content": "revenue"}]}))
    assert ev == [("error", {"message": "That report is not available."}), ("done", {})]
    ev = _events(chat.stream({"file": "report_AAPL_ffffffff.html"}))
    assert [e for e, _ in ev] == ["error", "done"]
    ev = _events(chat.stream({"file": "../etc/passwd", "messages": [{"role": "user", "content": "x"}]}))
    assert [e for e, _ in ev][-1] == "done"
    ev = _events(chat.stream({"file": "report_AAPL_ffffffff.html",
                              "messages": [{"role": "user", "content": "x" * 2001}]}))
    assert [e for e, _ in ev] == ["error", "done"]
    assert model.calls == []


def test_markdown_for_a_calculated_figure_and_plain_text(model):
    ledger = _ledger()
    margin = next(f for f in ledger.facts() if f.is_computed)
    reply = chat.Answer(html=f"<p>It was {chat.fmt.cited(margin, ledger)}.</p><p>I don&#x27;t advise.</p>", text="",
                        citations=[s.as_dict() for s in ledger.cite(margin)])
    text = chat.to_markdown(reply)
    assert "#calc-" not in text and "<" not in text          # no in-page link, no tags
    assert chat.fmt.fact(margin) in text                      # the value itself stays
    assert "I don't advise." in text                          # entities are decoded
    assert text.count("](https://www.sec.gov/") >= 1          # its filings are listed as sources
    assert chat.to_markdown(chat.Answer(html=chat.DONT_KNOW, text="")) == chat.DONT_KNOW


def test_dont_know_states_the_coverage_of_the_metric_asked_about(model):
    ledger = _ledger()
    sid = ledger.sources()[0].id
    # another metric reaches further back than revenue does
    ledger.add_fact(chat.Fact("eps_diluted", "FY2015", 1.0, "USD/share", source_ids=(sid,)))
    reply = chat.answer("What was revenue in 2015?", ledger, {"name": "X", "ticker": "X"}, session_id="t")
    assert reply.kind == "dont_know" and model.calls == []
    assert "I have revenue for fiscal 2022 to fiscal 2024" in reply.text      # revenue's own years
    assert "2015" not in reply.text


# ---- questions the saved report answers by itself -------------------------------------------
def _extras(ledger):
    rev = chat.fmt.cited(ledger.get("revenue", "FY2024"), ledger)
    margin = chat.fmt.cited(ledger.get("net_margin", "FY2024"), ledger)
    return {
        "thesis": {"thesis": [{"title": "Growth", "html": f"Revenue was {rev}.", "method": "code"}],
                   "bull": [{"html": f"Revenue rose to {rev}.", "method": "model", "signal": "g1", "rule": "Revenue rose"}],
                   "bear": [{"html": f"Net margin fell to {margin}.", "method": "code", "signal": "p1", "rule": "Margin fell"}],
                   "withheld": [], "method": "model", "counts": {}},
        "risk_themes": [{"title": "Supply chain", "summary_html": "Production depends on a few suppliers.",
                         "quote": "We depend on a small number of contract manufacturers & suppliers.",
                         "item": "Item 1A", "source": {"title": "Apple 10-K 2024, Item 1A", "url": SEC_URL, "date": "2024-11-01"}}],
        "multiples": [{"key": "pe", "label": "P/E", "value": 30.1, "text": "30.1x", "formula": "price / eps",
                       "inputs_html": [rev], "inputs": [], "price_note": "Price: $187.18, end of day 2024-05-16 (market data)"}],
        "review": {"sentences": 14, "confirmed_by_both": 13, "rejected": 1, "abstained_only": 0, "reviewers_answered": 2},
    }


def test_bull_case_is_answered_from_the_saved_report_without_the_model(model):
    led = _ledger()
    a = chat.answer("What is the bull case?", led, COMPANY, session_id="t", extras=_extras(led))
    assert a.kind == "answer" and model.calls == []
    assert "Bull case" in a.text and "Bear case" not in a.text
    assert chat.NOT_A_RECOMMENDATION in a.text
    assert [c["url"] for c in a.citations] == [SEC_URL]
    text = chat.to_markdown(a)
    assert "**Bull case**" in text and "\n- Revenue rose to [" in text and "](https://www.sec.gov/" in text
    assert "<" not in text


def test_bear_case_and_risks_together(model):
    led = _ledger()
    a = chat.answer("What are the bear case and the main risks?", led, COMPANY, session_id="t", extras=_extras(led))
    assert model.calls == [] and a.kind == "answer"
    assert "Bear case" in a.text and "Risk themes" in a.text and "Supply chain" in a.text
    text = chat.to_markdown(a)
    assert "contract manufacturers & suppliers" in text          # the filing's words, unescaped once
    assert "#calc-" not in text                                    # a calculated figure has no link in the chat
    assert chat.fmt.fact(led.get("net_margin", "FY2024")) in text


def test_valuation_and_checks_questions(model):
    led = _ledger()
    a = chat.answer("What is the P/E?", led, COMPANY, session_id="t", extras=_extras(led))
    assert model.calls == [] and "30.1x" in a.text and "end of day" in a.text
    a = chat.answer("How was this checked? Can I trust it?", led, COMPANY, session_id="t", extras=_extras(led))
    assert "Two independent reviewers read 14 sentences of this report and removed one sentence." in a.text


def test_a_part_the_report_does_not_hold_is_dont_know(model):
    led = _ledger()
    a = chat.answer("What is the bull case?", led, COMPANY, session_id="t", extras={})
    assert a.kind == "dont_know" and model.calls == []
    assert a.text == f"{chat.DONT_KNOW} {chat.NO_SUCH_PART}"
    a = chat.answer("What is the bull case?", led, COMPANY, session_id="t")          # no extras at all
    assert a.kind == "dont_know"


def test_advice_wins_over_a_report_part_and_metrics_are_unaffected(model):
    led = _ledger()
    a = chat.answer("Is the bull case strong enough to buy?", led, COMPANY, session_id="t", extras=_extras(led))
    assert a.kind == "no_advice" and "Bull case" not in a.text and model.calls == []
    model.reply = "Revenue was [[F:revenue|FY2024]]."
    a = chat.answer("What was revenue in 2024?", led, COMPANY, session_id="t", extras=_extras(led))
    assert a.kind == "answer" and len(model.calls) == 1 and "Bull case" not in a.text


def test_stream_reads_the_saved_parts(model):
    led = _ledger()
    name = _save(led)
    path = settings.reports_dir() / name.replace(".html", ".ledger.json")
    data = json.loads(path.read_text())
    data.update(_extras(led))
    path.write_text(json.dumps(data))
    ev = _events(chat.stream({"file": name, "messages": [{"role": "user", "content": "bear case?"}]}))
    assert [e for e, _ in ev] == ["text", "done"]
    assert "**Bear case**" in ev[0][1]["text"] and model.calls == []
    assert chat.load_ledger({"file": name})[1] == COMPANY                # the older loader still works


def test_a_reply_that_is_only_the_figure_becomes_a_full_sentence(model):
    led = _ledger()
    model.reply = "[[F:revenue|FY2023]]"
    a = chat.answer("What was revenue in 2023?", led, COMPANY, session_id="t")
    assert a.text.startswith("Revenue for fiscal 2023 was ") and a.kind == "answer"
    assert fmt.cited(led.get("revenue", "FY2023"), led) in a.html


@pytest.mark.parametrize("question", ["How was this report checked?", "Is this accurate?", "How were the figures verified?",
                                      "Did the AI hallucinate anything?", "Can I trust this?"])
def test_questions_about_how_the_report_was_checked(model, question):
    led = _ledger()
    a = chat.answer(question, led, COMPANY, session_id="t", extras=_extras(led))
    assert a.kind == "answer" and model.calls == []
    assert "How this report was checked" in a.text and "never types a number" in a.text


def _research_extras():
    return {
        "valuation": {"price_text": "$342.56", "methods": [
            {"key": "dcf", "label": "DCF (two-stage)", "value_text": "$152.30", "range_text": "$131.00 – $172.90", "share_text": "42%"},
            {"key": "pb_peer", "label": "P/B Peer Relative", "value_text": None, "reason": "equity is negative"}],
            "blend": {"value_text": "$148.20", "vs_price_text": "-56.7%"}},
        "news": {"window_text": "the last 45 days", "articles": [
            {"id": "N1", "title": "Apple <b>unveils</b> a product", "publisher": "Newswire", "date": "2026-11-18",
             "date_text": "18 Nov 2026", "url": "https://news.example.com/a", "summary": "Launch."},
            {"id": "N2", "title": "Insecure", "publisher": "X", "date": "2026-11-17", "url": "http://x.example.com", "summary": ""}],
            "topics": [{"title": "Products", "summary_html": "Reports cover a launch.", "articles": ["N1"]}]},
        "release": {"url": "https://www.sec.gov/Archives/edgar/data/320193/ex99.htm", "filed": "2026-10-30",
                    "source_title": "Form 8-K, filed 2026-10-30, Exhibit 99.1",
                    "statements": [{"topic": "Outlook", "quote": "We expect growth of 10% next quarter.", "summary_html": "Management gives an outlook."}]},
    }


def test_valuation_news_and_release_questions_are_answered_from_the_saved_report(model):
    led = _ledger()
    extras = _research_extras()
    a = chat.answer("What does the valuation say?", led, COMPANY, session_id="t", extras=extras)
    assert model.calls == [] and "DCF (two-stage): $152.30 per share (range $131.00 – $172.90), blend share 42%" in a.text
    assert "Model value: $148.20 per share (-56.7% against the last close of $342.56)." in a.text
    assert "P/B Peer Relative" not in a.text and "not a recommendation" in a.text
    a = chat.answer("Any recent news?", led, COMPANY, session_id="t", extras=extras)
    text = chat.to_markdown(a)
    assert "**Products**: Reports cover a launch." in text
    # markup inside a headline never reaches the reader as markup
    assert "[Apple unveils a product](https://news.example.com/a)" in text and "x.example.com" not in text
    assert "- [Apple unveils a product](https://news.example.com/a)" in text.split("Sources:")[1]
    assert "<b>" not in text
    assert "not checked against the filings" in text
    a = chat.answer("What did management say about the outlook?", led, COMPANY, session_id="t", extras=extras)
    text = chat.to_markdown(a)
    assert "**Outlook**: Management gives an outlook. *“We expect growth of 10% next quarter.”*" in text
    assert "[Form 8-K, filed 2026-10-30, Exhibit 99.1](https://www.sec.gov/Archives/edgar/data/320193/ex99.htm)" in text
    assert model.calls == []


def test_a_question_in_german_or_french_finds_the_figure(model):
    led = _ledger()
    assert chat.resolve("Wie hoch war der Umsatz 2024?", led)["metrics"] == ["revenue"]
    assert chat.resolve("Quel est le bénéfice net en 2023 ?", led)["metrics"] == ["net_income"]
    assert chat.resolve("ingresos 2022", led)["pairs"] == [("revenue", "FY2022")]
