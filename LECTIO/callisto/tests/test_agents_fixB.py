from backend import agents


def test_writer_prompt_has_fixB_rules():
    p = " ".join(agents.WRITER_SYSTEM.split())
    assert "wrong number or wrong claim" in p
    assert "never repeat the user's wrong number" in p
    assert "which grew faster" in p
    assert "separate short sentences" in p
    assert "percentage measure" in p
    assert "the percentage itself in a short sentence of its own" in p
