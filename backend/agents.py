"""The name each part of the report system carries in its PRISM traces.

One model, several roles: giving each role its own agent name lets PRISM show the writer, the two
independent reviewers, the risk reader, the bull and bear wording and the chat as separate agents
of one system (they share the report's session id). The name goes to the trace only, never to
the model (see llm.call_llm)."""

WRITER = "europa-report-writer"
AUDITOR = "europa-self-check-auditor"
SKEPTIC = "europa-self-check-skeptic"
RISK = "europa-risk-themes"
THESIS = "europa-bull-bear"
CHAT = "europa-report-chat"
BRIEF = "europa-market-brief"     # the markets app's "Quick brief" (backend.research.brief)

REVIEWERS = {"auditor": AUDITOR, "skeptic": SKEPTIC}
ALL = (WRITER, AUDITOR, SKEPTIC, RISK, THESIS, CHAT, BRIEF)
