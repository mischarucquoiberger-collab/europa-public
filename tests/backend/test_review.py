"""backend.verify.review: two independent readers, at the same time (offline: the model is faked)."""
import threading

import pytest

import llm
from backend.verify import review
from backend.verify.review import Verdict

PACKET = {
    "company": {"name": "Apple Inc.", "ticker": "AAPL"},
    "facts": [
        {"token": "[[F:revenue|FY2024]]", "label": "Revenue", "period": "fiscal 2024", "kind": "reported",
         "direction": "up"},
        {"token": "[[F:net_income|FY2024]]", "label": "Net income", "period": "fiscal 2024",
         "kind": "reported", "direction": "down"},
        {"token": "[[F:revenue|FY2023]]", "label": "Revenue", "period": "fiscal 2023", "kind": "reported",
         "direction": None},
    ],
    "periods": ["FY2024", "FY2023"],
}
TEXT = ("Revenue rose to [[F:revenue|FY2024]]. Net income rose to [[F:net_income|FY2024]].\n\n"
        "Apple Inc. reported both figures for fiscal 2024.")


def _reviewer(messages) -> str:
    system = messages[0]["content"]
    return "auditor" if system.startswith("You are the auditor") else "skeptic"


def _section(messages) -> str:
    return messages[1]["content"].split("\n", 1)[0]


def test_material_is_the_fact_list_without_values_and_numbered_sentences():
    msgs = review.messages_for("auditor", "results", review.numbered(TEXT), PACKET)
    user = msgs[1]["content"]
    assert "[[F:revenue|FY2024]] | Revenue | fiscal 2024 | up" in user
    assert "[[F:revenue|FY2023]] | Revenue | fiscal 2023 | none" in user
    assert "1. Revenue rose to [[F:revenue|FY2024]]." in user
    assert "3. Apple Inc. reported both figures for fiscal 2024." in user
    assert "391" not in user
    skeptic = review.messages_for("skeptic", "results", ["x."], PACKET)[0]["content"]
    assert msgs[0]["content"] != skeptic and "Assume each numbered sentence is wrong" in skeptic
    assert "rose, fell, increased, decreased, higher, lower, grew, declined" in msgs[0]["content"]


def test_both_readers_run_for_every_section_at_the_same_time():
    sections = {"overview": "Revenue rose to [[F:revenue|FY2024]].",
                "results": "Net income fell to [[F:net_income|FY2024]]."}
    # all four calls (2 sections x 2 readers) must be inside together, or the barrier breaks
    barrier = threading.Barrier(4, timeout=5)
    lock, seen, params = threading.Lock(), [], []

    def ask_json(messages, *, session_id, **p):
        with lock:
            seen.append((_section(messages), _reviewer(messages), session_id))
            params.append(p)
        barrier.wait()
        return [{"n": 1, "ok": True}]
    out = review.review_sections(sections, PACKET, session_id="report-x", ask_json=ask_json)
    assert sorted(seen) == sorted([(f"Section: {s}", r, "report-x") for s in ("Overview", "Results")
                                   for r in review.REVIEWERS])
    assert all({k: v for k, v in p.items() if k != "agent_id"} == {"temperature": 0, "max_tokens": 500}
               for p in params)
    # each reader is traced under its own agent name
    assert sorted(p["agent_id"] for p in params) == sorted(
        ["europa-self-check-auditor", "europa-self-check-skeptic"] * 2)
    assert set(out) == {"overview", "results"}
    assert out["results"] == [Verdict(1, "Net income fell to [[F:net_income|FY2024]].",
                                      ("auditor", "skeptic"), (), ())]


def test_review_section_runs_both_readers_concurrently():
    barrier = threading.Barrier(2, timeout=5)

    def ask_json(messages, *, session_id, **p):
        barrier.wait()          # breaks unless the two readers are asked at the same time
        return [{"n": 1, "ok": True}]
    out = review.review_section("results", "Revenue rose to [[F:revenue|FY2024]].", PACKET,
                                session_id="s", ask_json=ask_json)
    assert out[0].confirmed_by == ("auditor", "skeptic")


def test_one_rejection_removes_the_sentence_with_its_reason_and_paragraphs_are_kept():
    def ask_json(messages, *, session_id, **p):
        if _reviewer(messages) == "skeptic":
            return [{"n": 1, "ok": True}, {"n": 2, "ok": False, "why": "says rose; the listed direction is down"},
                    {"n": 3, "ok": True}]
        return [{"n": 1, "ok": True}, {"n": 2, "ok": True}, {"n": 3, "ok": True}]
    verdicts = review.review_section("results", TEXT, PACKET, session_id="s", ask_json=ask_json)
    assert [v.n for v in verdicts] == [1, 2, 3]
    assert verdicts[1].rejected_by == ("skeptic",) and verdicts[1].confirmed_by == ("auditor",)
    text, removed = review.keep(TEXT, verdicts)
    assert text == "Revenue rose to [[F:revenue|FY2024]].\n\nApple Inc. reported both figures for fiscal 2024."
    assert removed == ["Removed by review (says rose; the listed direction is down): Net income rose to [figure]."]
    counts = review.summary({"results": verdicts})
    assert counts["sentences"] == 3 and counts["confirmed_by_both"] == 2 and counts["rejected"] == 1
    assert counts["abstained_only"] == 0 and counts["reviewers_answered"] == 2


def test_an_abstaining_reader_removes_nothing():
    def ask_json(messages, *, session_id, **p):
        if _reviewer(messages) == "auditor":
            raise llm.LLMError("Nicrron answered HTTP 503")
        return [{"n": 1, "ok": True}]          # says nothing about sentences 2 and 3
    verdicts = review.review_section("results", TEXT, PACKET, session_id="s", ask_json=ask_json)
    assert verdicts[0].confirmed_by == ("skeptic",)
    assert all(not v.rejected_by for v in verdicts)
    assert review.keep(TEXT, verdicts) == (TEXT, [])
    counts = review.summary(verdicts)
    assert counts["confirmed_by_one"] == 1 and counts["abstained_only"] == 2
    assert counts["confirmed_by_both"] == 0 and counts["reviewers_answered"] == 1


def test_no_reader_answering_keeps_everything():
    replies = iter(["not json at all", {"n": 1}])

    def ask_json(messages, *, session_id, **p):
        return next(replies)
    out = review.review_sections({"results": TEXT}, PACKET, session_id="s", ask_json=ask_json)
    assert review.keep(TEXT, out["results"]) == (TEXT, [])
    counts = review.summary(out)
    assert counts["reviewers_answered"] == 0 and counts["sentences"] == 3 and counts["abstained_only"] == 3
    assert review.describe(counts) == "Self-check: no reader answered; nothing was removed"


def test_unusable_items_are_ignored_and_a_rejection_stands():
    def ask_json(messages, *, session_id, **p):
        return [{"n": 9, "ok": False}, {"n": "x", "ok": False}, {"n": 1, "ok": "maybe"},
                {"n": 2, "ok": False}, {"n": 2, "ok": True}, "junk"]
    verdicts = review.review_section("results", TEXT, PACKET, session_id="s", ask_json=ask_json)
    assert verdicts[0].rejected_by == () and verdicts[0].confirmed_by == ()
    assert verdicts[1].rejected_by == ("auditor", "skeptic")
    assert verdicts[1].reasons == ("the auditor did not confirm it", "the skeptic did not confirm it")
    text, removed = review.keep(TEXT, verdicts)
    assert "Net income" not in text and len(removed) == 1
    assert review.describe(review.summary(verdicts)) == "Self-check: 3 sentences, 0 confirmed by both readers, 1 removed"


def test_through_the_real_model_door(monkeypatch):
    """review -> backend.model.ask_json -> llm.call_llm, fenced JSON included."""
    def fake(messages, *, session_id, **params):
        assert params.pop("agent_id") in ("europa-self-check-auditor", "europa-self-check-skeptic")
        assert params == {"temperature": 0, "max_tokens": 500}
        return '```json\n[{"n": 1, "ok": false, "why": "no such figure"}]\n```'
    monkeypatch.setattr(llm, "call_llm", fake)
    verdicts = review.review_section("results", "Revenue rose.", PACKET, session_id="s")
    assert verdicts[0].rejected_by == review.REVIEWERS


def test_empty_sections_ask_nobody_and_never_raise():
    def ask_json(messages, *, session_id, **p):
        raise AssertionError("must not be asked")
    assert review.review_sections({"results": "  "}, PACKET, session_id="s", ask_json=ask_json) == {"results": []}
    assert review.keep("", []) == ("", [])
    assert review.summary(None)["sentences"] == 0
    assert review.keep("Some text.", [object()]) == ("Some text.", [])      # never raises



# ---- 2026-11-22 bug-hunt round ---------------------------------------------------------------
def _nobody(messages, *, session_id, **p):
    return None                                   # both readers abstain: only the code rules act


def _rejects(reasons_by_reader):
    def ask_json(messages, *, session_id, **p):
        why = reasons_by_reader.get(_reviewer(messages))
        return [{"n": 1, "ok": why is None, **({"why": why} if why else {})}]
    return ask_json


def test_the_new_rejection_rules_are_in_both_readers_prompts():
    for reviewer in review.REVIEWERS:
        system = review.messages_for(reviewer, "results", ["x."], PACKET)[0]["content"]
        assert "says a growth rate rose, fell" in system
        assert "three or more periods of the same figure" in system
        assert "describes the data instead of the company" in system
        assert "increases seen in [[F:revenue|FY2023]]" in system
        assert "older than the latest fiscal year" in system
        assert "little changed" in system


def test_fact_lines_show_little_changed_growth_rates_and_signs():
    packet = {"facts": [
        {"token": "[[F:revenue|FY2025]]", "label": "Revenue", "period": "fiscal 2025", "direction": "flat"},
        {"token": "[[F:revenue_growth|FY2025]]", "label": "Revenue growth", "period": "fiscal 2025",
         "direction": None, "rate": True},
        {"token": "[[F:net_income|FY2025]]", "label": "Net income", "period": "fiscal 2025",
         "direction": "down", "sign": "turned negative"}]}
    assert review.fact_lines(packet) == [
        "[[F:revenue|FY2025]] | Revenue | fiscal 2025 | flat (little changed)",
        "[[F:revenue_growth|FY2025]] | Revenue growth | fiscal 2025 | none (a growth rate: stated, never said to rise or fall)",
        "[[F:net_income|FY2025]] | Net income | fiscal 2025 | down, turned negative"]


@pytest.mark.parametrize("sentence, reason", [
    ("Revenue rose to [[F:revenue|FY2025]], continuing increases from [[F:revenue|FY2024]] and "
     "[[F:revenue|FY2023]].", "three or more periods"),
    ("Net income rose to [[F:net_income|FY2025]], although net income growth fell to "
     "[[F:net_income_growth|FY2025]].", "growth rate rose or fell"),
    ("Revenue growth slowed to [[F:revenue_growth|FY2025]].", "growth rate rose or fell"),
    ("The figures for UnitedHealth Group cover four fiscal years of reported income.", "describes the data"),
    ("The most recent long-term debt figure available is [[F:long_term_debt|2023-12-31]].", "describes the data"),
    ("Revenue rose to [[F:revenue|FY2025]], continuing increases seen in [[F:revenue|FY2023]].",
     "as if it were a period"),
])
def test_the_code_rules_reject_without_any_reader(sentence, reason):
    verdicts = review.review_section("overview", sentence, PACKET, session_id="s", ask_json=_nobody)
    assert verdicts[0].rejected_by == (review.RULES,)
    assert any(reason in r for r in verdicts[0].reasons)
    text, removed = review.keep(sentence, verdicts)
    assert text == "" and len(removed) == 1 and "[[" not in removed[0]
    counts = review.summary(verdicts)
    assert counts["rejected"] == counts["rejected_by_rules"] == 1 and counts["reviewers_answered"] == 0
    assert review.describe(counts) == "Self-check: no reader answered; the code rules removed 1"


@pytest.mark.parametrize("sentence", [
    "Revenue grew [[F:revenue_growth|FY2025]] in fiscal 2025.",
    "Revenue growth was [[F:revenue_growth|FY2025]] in fiscal 2025, as net income rose to [[F:net_income|FY2025]].",
    "Revenue rose to [[F:revenue|FY2025]] in fiscal 2025 from [[F:revenue|FY2024]] in fiscal 2024.",
])
def test_the_code_rules_leave_good_sentences_alone(sentence):
    assert review.rule_reasons(sentence) == []


def test_the_same_reason_from_both_readers_is_shown_once():
    ask = _rejects({"auditor": "'As a result' states a cause that the list does not contain",
                    "skeptic": "'As a result' asserts a cause the list does not contain"})
    sentence = "As a result, net income rose to [[F:net_income|FY2024]]."
    _, removed = review.keep(sentence, review.review_section("results", sentence, PACKET, session_id="s", ask_json=ask))
    assert removed == ["Removed by review ('As a result' states a cause that the list does not contain): "
                       "As a result, net income rose to [figure]."]


def test_different_reasons_show_at_most_two():
    assert review.reason_text(["says rose; the listed direction is down", "grammatical nonsense",
                               "a third reason"]) == "says rose; the listed direction is down; grammatical nonsense"
    assert review.reason_text(["same thing", "Same thing."]) == "same thing"
    assert review.reason_text([]) == "a reader did not confirm it"


def test_removed_text_is_readable_even_for_a_cut_off_placeholder():
    sentence = "Net margin rose to [[F:net_margin|FY2024]] from [[F:net_margin|FY2023."
    ask = _rejects({"auditor": "a cut-off token [[F:net_margin|FY2023", "skeptic": None})
    _, removed = review.keep(sentence, review.review_section("results", sentence, PACKET, session_id="s", ask_json=ask))
    assert removed == ["Removed by review (a cut-off token [figure, cut off]): "
                       "Net margin rose to [figure] from [figure, cut off]"]


def test_survivors_are_repaired_and_back_references_go_too():
    text = ("Total assets rose to [[F:total_assets|2025-12-31]]. Total liabilities also rose to "
            "[[F:total_liabilities|2025-12-31]]. Revenue rose in each of those years.\n\n"
            "Operating cash flow rose to [[F:operating_cash_flow|FY2025]]. Also, capital expenditure "
            "rose to [[F:capex|FY2025]], which also rose the year before.")

    def ask_json(messages, *, session_id, **p):
        return [{"n": 1, "ok": False, "why": "wrong direction"}, {"n": 2, "ok": True}, {"n": 3, "ok": True},
                {"n": 4, "ok": False, "why": "wrong direction"}, {"n": 5, "ok": True}]
    verdicts = review.review_section("financial_position", text, PACKET, session_id="s", ask_json=ask_json)
    kept, removed = review.keep(text, verdicts)
    assert kept == ("Total liabilities rose to [[F:total_liabilities|2025-12-31]].\n\n"
                    "Capital expenditure rose to [[F:capex|FY2025]], which rose the year before.")
    assert removed[1] == "Removed by review (refers to a removed sentence): Revenue rose in each of those years."
    assert len(removed) == 3
    assert review.share_removed(text, verdicts) == pytest.approx(3 / 5)
    assert review.share_removed(TEXT, []) == 0.0 and review.share_removed("", []) == 0.0


def test_a_back_reference_with_nothing_removed_stays():
    text = "Revenue rose to [[F:revenue|FY2024]]. Net income rose in that year."
    verdicts = review.review_section("results", text, PACKET, session_id="s",
                                     ask_json=lambda m, *, session_id, **p: [{"n": 1, "ok": True}, {"n": 2, "ok": True}])
    assert review.keep(text, verdicts) == (text, [])
