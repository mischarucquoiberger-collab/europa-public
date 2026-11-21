"""The valuation advisor: one model call through backend.model.ask, weights checked in code, the
rationale audited, every failure falls back to the default weights."""
import json

import pytest

import llm
from backend import model
from backend.analysis import advisor, ratios, valuation as val
from backend.ledger import Fact, Ledger, Source

K = Source(id="", type="edinet", url="https://www.sec.gov/ix?doc=/Archives/edgar/data/1/k25.htm",
           title="Form 10-K, filed 2026-02-01", date="2026-02-01")
YE = "2025-12-31"
# distinctive figures: none of them may reach the prompt
VALUES = {("eps_diluted", "FY2025"): 5.37, ("net_income", "FY2025"): 537.0, ("revenue", "FY2025"): 4321.0,
          ("revenue", "FY2024"): 3917.0, ("operating_income", "FY2025"): 873.0,
          ("operating_cash_flow", "FY2025"): 761.0, ("capex", "FY2025"): 219.0,
          ("shareholders_equity", YE): 2143.0, ("total_assets", YE): 6789.0,
          ("long_term_debt", YE): 1511.0, ("cash", YE): 499.0, ("shares_outstanding", "2026-01-31"): 103.0}
PEERS = {"rows": [{"multiples": {"pe": v, "ev_ebit": v, "ev_sales": v / 5, "pb": v / 5}}
                  for v in (10.0, 12.0, 14.0, 16.0, 18.0)]}
COMPANY = {"name": "Orchard Devices Inc.", "ticker": "ORCH", "details": {"sic_description": "ELECTRONIC COMPUTERS"}}


def _ledger():
    ledger = Ledger()
    sid = ledger.add_source(K)
    units = {"eps_diluted": "USD/share", "shares_outstanding": "shares"}
    for (key, period), value in VALUES.items():
        ledger.add_fact(Fact(key=key, period=period, value=value, unit=units.get(key, "USD"), source_ids=(sid,)))
    ledger.set_period_end("FY2025", YE)
    ledger.set_period_end("FY2024", "2024-12-31")
    ratios.compute(ledger)
    return ledger


def _valuation(ledger):
    # no scenarios: the DCF is not priced; the five others are
    return val.compute(ledger, price=100.0, price_date="2026-03-02", peer_table=PEERS)


class Fake:
    def __init__(self, reply=None, exc=None):
        self.reply, self.exc, self.calls = reply, exc, []

    def __call__(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if self.exc:
            raise self.exc
        return self.reply


def _weigh(reply=None, exc=None):
    ledger = _ledger()
    fake = Fake(reply, exc)
    out = advisor.weigh(_valuation(ledger), COMPANY, ledger, session_id="valuation-test", ask=fake)
    return out, fake


CLEAN = {"weights": {"pe_peer": 70, "ev_ebit_peer": 40, "graham": 10},
         "rationale": "Peer earnings multiples fit a steady, profitable hardware maker. "
                      "Book value matters less for an asset-light business."}


def test_clean_json():
    out, fake = _weigh(json.dumps(CLEAN))
    assert out["method"] == "model" and out["weights"] == {"pe_peer": 70, "ev_ebit_peer": 40, "graham": 10}
    assert "Peer earnings multiples fit" in out["rationale_html"] and "Book value matters less" in out["rationale_html"]
    assert "<p>" not in out["rationale_html"] and out["withheld"] == []
    assert len(fake.calls) == 1


def test_fenced_json():
    out, _ = _weigh("Here you are:\n```json\n" + json.dumps(CLEAN) + "\n```")
    assert out["method"] == "model" and out["weights"]["pe_peer"] == 70


def test_cut_off_json_keeps_the_complete_pairs():
    reply = '{"weights": {"pe_peer": 70, "ev_ebit_peer": 40, "graham": 3'
    out, _ = _weigh(reply)
    assert out["weights"] == {"pe_peer": 70, "ev_ebit_peer": 40}       # "graham": 3 may be cut
    assert out["rationale_html"] is None
    reply = json.dumps(CLEAN)[:-25]                                       # rationale cut, weights whole
    out, _ = _weigh(reply)
    assert out["weights"] == CLEAN["weights"] and out["rationale_html"] is None


@pytest.mark.parametrize("reply", ["I cannot help with that.", "", "{}", "[1, 2, 3]", '{"weights": "many"}'])
def test_garbage_gives_the_default(reply):
    out, _ = _weigh(reply)
    assert out == {"weights": {}, "rationale_html": None, "method": "default", "withheld": []}


def test_model_error_gives_the_default():
    out, _ = _weigh(exc=llm.LLMError("HTTP 500"))
    assert out["method"] == "default" and out["weights"] == {}
    out, _ = _weigh(exc=RuntimeError("boom"))
    assert out["method"] == "default"


def test_weights_checked_in_code():
    reply = json.dumps({"weights": {"pe_peer": 150, "ev_ebit_peer": -5, "graham": "high", "bogus": 50,
                                    "dcf": 60, "pb_peer": 33.6, "ev_sales_peer": True}, "rationale": ""})
    out, _ = _weigh(reply)
    # dcf is not priced here (no scenarios); strings and booleans are not numbers
    assert out["weights"] == {"pe_peer": 100, "ev_ebit_peer": 0, "pb_peer": 34}


def test_rationale_sentences_with_digits_or_advice_are_withheld():
    reply = json.dumps({"weights": {"pe_peer": 60},
                        "rationale": "Peer multiples fit this business. Margins near 30 percent are stable. "
                                     "Investors should buy the shares. The rating is strong. "
                                     "Cash flow methods add a second view."})
    out, _ = _weigh(reply)
    html = out["rationale_html"]
    assert "Peer multiples fit this business." in html and "Cash flow methods add a second view." in html
    assert "30" not in html and "buy" not in html.lower() and "rating" not in html.lower()
    assert len(out["withheld"]) == 3


def test_agent_temperature_and_tokens_are_passed():
    _, fake = _weigh(json.dumps(CLEAN))
    messages, kwargs = fake.calls[0]
    assert kwargs == {"session_id": "valuation-test", "agent_id": "europa-valuation-advisor",
                      "temperature": 0.2, "max_tokens": 900}
    assert messages[0]["role"] == "system" and messages[1]["role"] == "user"
    prompt = messages[1]["content"]
    assert "ELECTRONIC COMPUTERS" in prompt and "Orchard Devices Inc." in prompt
    assert "profitable in the latest fiscal year" in prompt and "revenue growing" in prompt
    assert "dcf (DCF (two-stage)): not priced" in prompt and "pe_peer (P/E peer relative): priced" in prompt
    for figure in ("4321", "4,321", "537", "5.37", "873", "2143", "6789", "1511"):
        assert figure not in prompt


def test_the_call_goes_through_backend_model_ask(monkeypatch):
    fake = Fake(json.dumps(CLEAN))
    monkeypatch.setattr(model, "ask", fake)                              # resolved at call time
    ledger = _ledger()
    out = advisor.weigh(_valuation(ledger), COMPANY, ledger, session_id="s1")
    assert out["method"] == "model" and len(fake.calls) == 1


def test_no_priced_method_makes_no_call():
    ledger = Ledger()
    fake = Fake(json.dumps(CLEAN))
    v = {"methods": [{"key": "dcf", "value": None}]}
    assert advisor.weigh(v, COMPANY, ledger, session_id="s", ask=fake)["method"] == "default"
    assert fake.calls == []


def test_weights_feed_the_blend():
    out, _ = _weigh(json.dumps(CLEAN))
    ledger = _ledger()
    blended = val.blend(_valuation(ledger), out["weights"], rationale_html=out["rationale_html"],
                        advisor_method=out["method"])
    assert blended["advisor"]["method"] == "model" and blended["blend"]["value"] is not None
    by = {m["key"]: m for m in blended["methods"]}
    assert by["pe_peer"]["weight"] == 70


def test_the_prompt_carries_the_bank_or_insurer_flag():
    ledger = _ledger()
    fake = Fake(json.dumps(CLEAN))
    advisor.weigh(_valuation(ledger), COMPANY, ledger, session_id="s", ask=fake, financial=True)
    prompt = fake.calls[0][0][1]["content"]
    assert advisor.FINANCIAL_LINE in prompt and "weigh the book value method (P/B)" in prompt
    fake = Fake(json.dumps(CLEAN))
    advisor.weigh(_valuation(ledger), COMPANY, ledger, session_id="s", ask=fake)
    assert advisor.OPERATING_LINE in fake.calls[0][0][1]["content"]
