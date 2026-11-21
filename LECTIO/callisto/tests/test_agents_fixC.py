from backend import agents


def _p(s):
    return " ".join(s.split())


def test_skeptic_prompt_fixC():
    p = _p(agents.SKEPTIC_SYSTEM)
    assert "contradicts a specific figure or direction" in p
    assert "name that figure" in p
    assert "Correct arithmetic consequences" in p
    assert "grew faster than" in p
    assert "Plain-English definitions" in p
    for bad in ("wrong number", "wrong year", "invented cause", "forecast"):
        assert bad in p


def test_writer_prompt_followup_rule_and_old_rules_kept():
    p = _p(agents.WRITER_SYSTEM)
    assert "depends on an earlier question you cannot see" in p
    assert "which measure and year you are assuming" in p
    assert "wrong number or wrong claim" in p


def test_mistral_large4_gets_extra_params_only():
    assert agents._EXTRA_PARAMS("mistral/mistral-large-4") == {"reasoning_effort": "low", "top_p": 1}
    assert agents._EXTRA_PARAMS("openai/gpt-5.4-mini") == {}
