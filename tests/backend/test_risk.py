import json
import re
from pathlib import Path

import pytest

import llm
from backend.analysis import risk
from backend.filings.passages import Passage, is_furniture, risk_passages
from backend.sources.sec import Filing

TEXT = (Path(__file__).parent / "fixtures" / "filing_10k_sample.txt").read_text(encoding="utf-8")
PASSAGES = risk_passages(TEXT)
FILING = Filing(accession="0000000000-25-000001", form="10-K", filed="2025-11-14", period="2025-09-27",
                primary_doc="calder-20250927.htm", cik="999999")

# sentences of the fixture (P1 and P8)
TWO_MAKERS = "Two contract manufacturers assembled substantially all of our instruments in fiscal 2025."
IF_EITHER = ("If either of them suffers a fire, a labor dispute, a loss of key staff or a financial failure, "
             "we may be unable to ship instruments for several months while we qualify a replacement.")
QUALIFYING = ("Qualifying a new manufacturer requires us to transfer tooling, train its staff and repeat our "
              "acceptance tests, and our customers may cancel orders during that period.")
AS_A_RESULT = "As a result, our results for any quarter may not be indicative of future periods."
MARKET_PRICE = ("The market price of our common stock may fall sharply if our results do not meet the "
                "expectations of securities analysts, and stockholders could lose part of their investment.")

GOOD = [
    {"title": "Reliance on contract manufacturers", "passage": "P1",
     # a double space: still the filing's sentence
     "quote": IF_EITHER.replace("ship instruments", "ship  instruments"),
     "summary": "The company relies on two outside assemblers and could not ship quickly if one failed."},
    {"title": "Information security", "passage": "P4",
     "quote": "A successful attack could interrupt our order processing for an extended period and require "
              "us to notify customers and regulators.",
     "summary": "Attacks on the company's systems or its vendors' systems could stop order processing."},
    {"title": "Trade policy and component costs", "passage": "P6",
     "quote": "New or higher tariffs, export restrictions or customs delays could raise the cost of these "
              "components or interrupt their supply, and we may not be able to pass the higher costs on "
              "to our customers.",
     "summary": "Tariffs on imported parts could raise costs that the company may not pass on."},
]
INVENTED = {"title": "Competitive pressure", "passage": "P3",
            "quote": "Our rivals are much bigger than we are and they always win the largest contracts.",
            "summary": "Larger rivals with bundled offers could take sales from the company."}
NUMBER = {"title": "Funding of laboratories", "passage": "P2",
          "quote": "These budgets depend on public funding decisions, grant cycles and our customers' own "
                   "financial results, and they can be cut or postponed with little notice.",
          "summary": "Most sales come from budgets that fell 12% last year."}
ADVICE = {"title": "Volatile share price", "passage": "P8",
          "quote": AS_A_RESULT,
          "summary": "Investors should expect the share price to swing around results."}


def theme(passage, quote, title="A risk theme", summary="The filing describes a risk to the business."):
    return {"title": title, "passage": passage, "quote": quote, "summary": summary}


def fake_model(reply, calls):
    def call(messages, *, session_id, model=None, **params):
        calls.append({"messages": messages, "session_id": session_id, "params": params})
        if isinstance(reply, Exception):
            raise reply
        return reply
    return call


def run(monkeypatch, reply, passages=None, **kwargs):
    calls = []
    # the shared model door retries a busy model after a pause; not in these tests
    monkeypatch.setattr("backend.model.RETRY_PAUSES", ())
    monkeypatch.setattr(llm, "call_llm", fake_model(reply, calls))
    out = risk.themes(PASSAGES if passages is None else passages, FILING, session_id="risk-job-7", **kwargs)
    return out, calls


def assert_grounded(out, text=TEXT):
    quotes = [t["quote"] for t in out]
    assert len(set(quotes)) == len(quotes)                      # no two themes share a quote
    for theme_ in out:
        q = theme_["quote"]
        assert q in text                                        # literally the filing's characters
        assert risk.QUOTE_MIN_CHARS <= len(q) <= risk.QUOTE_MAX_CHARS
        assert re.match(r"[\"“(]?[A-Z0-9]", q) and re.search(r"[.!?][\"”)]?$", q)   # whole sentences
        assert theme_["item"] == "1A"
        assert theme_["source"] == {"title": "Form 10-K, filed 2025-11-14, Item 1A",
                                    "url": FILING.viewer_url, "date": "2025-11-14"}


def test_keeps_exact_quotes_and_drops_invented_number_and_advice(monkeypatch):
    reply = json.dumps(GOOD[:1] + [INVENTED, NUMBER] + GOOD[1:] + [ADVICE])
    out, calls = run(monkeypatch, reply)
    assert [t["title"] for t in out] == [t["title"] for t in GOOD]
    assert [t["passage"] for t in out] == ["P1", "P4", "P6"]
    assert all(t["method"] == "llm" for t in out)
    assert_grounded(out)
    # the served quote is the filing's text, not the model's re-typing
    assert out[0]["quote"] == IF_EITHER
    assert out[1]["summary_html"] == "Attacks on the company&#x27;s systems or its vendors&#x27; systems could stop order processing."
    # one call, with the given session and parameters
    assert len(calls) == 1
    assert calls[0]["session_id"] == "risk-job-7"
    assert calls[0]["params"] == {"agent_id": "europa-risk-themes", "temperature": 0.2, "max_tokens": risk.MAX_TOKENS}
    system, user = calls[0]["messages"]
    assert system["role"] == "system" and "must not contain any digit" in system["content"]
    assert "Do not recommend, rate or predict" in system["content"]
    assert "states the risk or the harm" in system["content"] and "readable on its own" in system["content"]
    assert "answer []" in system["content"]
    assert "P1: We depend on a small number of contract manufacturers" in user["content"]
    assert user["content"].count("\nP") >= len(PASSAGES) - 1


def test_the_excerpt_shown_to_the_model_ends_at_a_sentence_end(monkeypatch):
    _, calls = run(monkeypatch, json.dumps(GOOD))
    user = calls[0]["messages"][1]["content"]
    blocks = re.findall(r"^P\d+: .*$", user, re.MULTILINE)
    assert len(blocks) == len(PASSAGES)
    for block, p in zip(blocks, PASSAGES):
        excerpt = block.split(" — ", 1)[1]
        assert excerpt.endswith("."), block[-60:]
        assert len(excerpt) <= risk.EXCERPT_CHARS
        # the passage's own words, page furniture ("Table of Contents", a page number) left out
        clean = " ".join(" ".join(line.split()) for line in p.text.split("\n")
                         if line.strip() and not is_furniture(line))
        assert excerpt in clean
    # P1's body is longer than the excerpt: it stops after the last whole sentence that fits
    p1 = blocks[0].split(" — ", 1)[1]
    assert p1.endswith("give priority to larger customers.") and "Any of these events" not in p1


def test_fenced_json_with_prose_is_parsed(monkeypatch):
    reply = "Here are the themes you asked for:\n```json\n" + json.dumps(GOOD, indent=2) + "\n```\nDone."
    out, _ = run(monkeypatch, reply)
    assert [t["passage"] for t in out] == ["P1", "P4", "P6"]
    assert_grounded(out)


def test_duplicates_by_passage_and_max_themes(monkeypatch):
    twice = dict(GOOD[0], title="Manufacturing partners")
    out, _ = run(monkeypatch, json.dumps([GOOD[0], twice] + GOOD[1:]), max_themes=2)
    assert [t["title"] for t in out] == ["Reliance on contract manufacturers", "Information security"]


# --- whole sentences ------------------------------------------------------------------------

def test_a_quote_cut_mid_word_is_extended_to_its_sentence_end(monkeypatch):
    cut = IF_EITHER[:IF_EITHER.index("instruments") + 5]       # "... we may be unable to ship instr"
    out, _ = run(monkeypatch, json.dumps([theme("P1", cut)] + GOOD[1:]))
    assert out[0]["passage"] == "P1" and out[0]["method"] == "llm"
    assert out[0]["quote"] == IF_EITHER
    assert_grounded(out)


def test_a_quote_starting_mid_sentence_is_extended_back(monkeypatch):
    tail = IF_EITHER[IF_EITHER.index("a labor dispute"):]
    out, _ = run(monkeypatch, json.dumps([theme("P1", tail)] + GOOD[1:]))
    assert out[0]["quote"] == IF_EITHER
    assert_grounded(out)


def test_an_extension_over_the_limit_is_cut_back_to_whole_sentences(monkeypatch):
    # three sentences would be 440 characters: the cut third one is dropped, not completed
    quote = TWO_MAKERS + " " + IF_EITHER + " " + QUALIFYING[:60]
    assert len(TWO_MAKERS + " " + IF_EITHER + " " + QUALIFYING) > risk.QUOTE_MAX_CHARS
    out, _ = run(monkeypatch, json.dumps([theme("P1", quote)] + GOOD[1:]))
    assert out[0]["quote"] == TWO_MAKERS + " " + IF_EITHER
    assert_grounded(out)


def test_a_quote_inside_one_overlong_sentence_drops_the_theme(monkeypatch):
    long_sentence = ("A failure of our systems could " + ", ".join(["delay orders from customers"] * 20) +
                     " and harm our results.")
    assert len(long_sentence) > risk.QUOTE_MAX_CHARS
    text = ("Our systems may fail.\n\n" + long_sentence + "\n\n")
    p = Passage(id="P1", item="1A", heading="Our systems may fail.", text=text.strip(), start=0,
                end=len(text.strip()))
    out, _ = run(monkeypatch, json.dumps([theme("P1", long_sentence[:120])]), passages=[p])
    # no whole sentence of 40 to 400 characters contains the quote: no model theme, only the fallback
    assert all(t["method"] == "heading-fallback" for t in out)
    assert all(long_sentence[:120] not in t["quote"] for t in out)


# --- no shared quotes, and at least three themes -------------------------------------------

SHARED = "The loss of a key supplier could have a material adverse effect on our business and results of operations."


def _passage(n, heading, body, offset):
    text = heading + "\n\n" + body
    return Passage(id=f"P{n}", item="1A", heading=heading, text=text, start=offset, end=offset + len(text))


def test_no_two_themes_share_a_quote(monkeypatch):
    ps = [_passage(1, "We depend on suppliers for our components.",
                   "We buy most of our components from outside suppliers in several countries. " + SHARED, 0),
          _passage(2, "We depend on a few distributors for our sales.",
                   "We sell most of our instruments through independent distributors in many regions. " + SHARED,
                   1_000),
          _passage(3, "Our facilities could be damaged by natural disasters.",
                   "A fire, flood or earthquake at our main site could halt production for an extended period.",
                   2_000)]
    text = "\n\n".join(p.text for p in ps)
    reply = json.dumps([theme("P1", SHARED, "Supplier dependence"), theme("P2", SHARED, "Distributor dependence")])
    out, _ = run(monkeypatch, reply, passages=ps)
    quotes = [t["quote"] for t in out]
    assert quotes.count(SHARED) == 1
    assert len(set(quotes)) == len(quotes) == 3
    assert out[0] == dict(out[0], passage="P1", quote=SHARED, method="llm")
    # P2's theme would repeat P1's quote and P2 has no other sentence stating a risk: dropped
    assert [t["method"] for t in out[1:]] == ["heading-fallback", "heading-fallback"]
    for t in out:
        assert t["quote"] in text


def test_fewer_than_three_model_themes_are_filled_up_from_unused_passages(monkeypatch):
    out, _ = run(monkeypatch, json.dumps([GOOD[1]]))
    assert [t["passage"] for t in out] == ["P4", "P1", "P2"]
    assert [t["method"] for t in out] == ["llm", "heading-fallback", "heading-fallback"]
    assert out[1]["title"] == PASSAGES[0].heading and out[1]["summary_html"] == ""
    assert_grounded(out)
    # with max_themes below three, no more than max_themes
    out, _ = run(monkeypatch, json.dumps([GOOD[1]]), max_themes=2)
    assert [t["method"] for t in out] == ["llm", "heading-fallback"]


# --- a quote that states the risk ------------------------------------------------------------

def test_a_neutral_quote_is_replaced_by_the_sentence_that_states_the_risk(monkeypatch):
    out, _ = run(monkeypatch, json.dumps([theme("P1", TWO_MAKERS)] + GOOD[1:]))
    assert out[0]["passage"] == "P1" and out[0]["quote"] == IF_EITHER     # the nearest adverse sentence
    assert_grounded(out)


def test_a_quote_leaning_on_the_sentence_before_is_replaced(monkeypatch):
    out, _ = run(monkeypatch, json.dumps(GOOD[1:] + [theme("P8", AS_A_RESULT)]))
    assert out[2]["passage"] == "P8" and out[2]["quote"] == MARKET_PRICE
    assert_grounded(out)


def test_a_neutral_quote_stays_when_the_passage_states_no_risk_in_other_words(monkeypatch):
    neutral = "We sell our instruments to universities, laboratories and manufacturers in many regions."
    ps = [_passage(1, "Customers", neutral + " Our sales force covers each region directly.", 0)]
    out, _ = run(monkeypatch, json.dumps([theme("P1", neutral)]), passages=ps)
    assert out == [dict(out[0], quote=neutral, method="llm")]


# --- the fallback ----------------------------------------------------------------------------

@pytest.mark.parametrize("reply", [llm.LLMError("Nicrron answered HTTP 503"), "I cannot help with that.",
                                   "[{not json", "[]", json.dumps([INVENTED, NUMBER, ADVICE]), ""])
def test_model_failure_gives_the_heading_fallback(monkeypatch, reply):
    out, calls = run(monkeypatch, reply)
    assert len(calls) == 1
    assert [t["title"] for t in out] == [p.heading for p in PASSAGES[:5]]
    assert all(t["summary_html"] == "" and t["method"] == "heading-fallback" for t in out)
    assert out[0]["quote"] == IF_EITHER              # the first body sentence that states the risk
    assert_grounded(out)


def test_no_passages_and_dict_filing(monkeypatch):
    out, calls = run(monkeypatch, json.dumps(GOOD))
    assert out
    monkeypatch.setattr(llm, "call_llm", fake_model(json.dumps(GOOD), calls := []))
    assert risk.themes([], FILING, session_id="s") == []
    assert calls == []                                          # no passages: no call
    as_dict = {"form": "10-K", "filed": "2025-11-14", "url": "https://www.sec.gov/Archives/x.htm"}
    out = risk.themes(PASSAGES, as_dict, session_id="s")
    assert out[0]["source"]["url"] == "https://www.sec.gov/Archives/x.htm"   # no viewer url: the archive url
    assert out[0]["source"]["title"] == "Form 10-K, filed 2025-11-14, Item 1A"


def test_never_raises_on_a_broken_model(monkeypatch):
    def boom(messages, **kwargs):
        raise ValueError("unexpected")
    monkeypatch.setattr(llm, "call_llm", boom)
    out = risk.themes(PASSAGES, FILING, session_id="s")
    assert [t["method"] for t in out] == ["heading-fallback"] * 5
    monkeypatch.setattr(llm, "call_llm", fake_model(json.dumps([{"passage": None, "quote": 7}]), []))
    assert risk.themes(PASSAGES, None, session_id="s")[0]["source"]["url"] == ""


def test_a_reply_cut_off_inside_the_array_keeps_its_complete_themes(monkeypatch):
    whole = json.dumps(GOOD)
    cut = whole[: whole.rindex('{"') + 30]            # the last theme is cut off mid-object
    out, calls = run(monkeypatch, cut)
    assert len(calls) == 1
    assert [t["passage"] for t in out[:2]] == ["P1", "P4"]  # the two complete themes, from the model
    assert [t["method"] for t in out] == ["llm", "llm", "heading-fallback"]   # topped up to three
    assert_grounded(out)
