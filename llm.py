"""The ONE place this app talks to a model. Every LLM call goes through call_llm().

    from llm import Conversation
    chat = Conversation(system_prompt="...")
    reply = chat.ask("hello")

The model (Nicrron) gets the full, unredacted messages. After the call, a
redacted copy is handed to PRISM. A PRISM problem never affects the reply.
"""
import json
import time
import urllib.error
import urllib.request
import uuid

import config
import prism
from redact import redact


class LLMError(RuntimeError):
    pass


def new_session_id() -> str:
    return "conv-" + uuid.uuid4().hex


def call_llm(messages: list, *, session_id: str, model: str | None = None,
             agent_id: str | None = None, **params) -> str:
    """Send `messages` to Nicrron, return the reply text, then trace a redacted copy to PRISM.

    `agent_id` names the part of the app that is asking (the report writer, a reviewer, the chat),
    so each one shows as its own agent in PRISM; it is not sent to the model. Default: the app's
    one agent id from the configuration."""
    model = model or config.NICRRON_MODEL
    key = config.secret("NICRRON_API_KEY")
    if not key:
        raise LLMError("NICRRON_API_KEY is not set. Put it in .env.")

    request = urllib.request.Request(
        config.NICRRON_BASE_URL + "/chat/completions",
        data=json.dumps({"model": model, "messages": messages, **params}).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=config.NICRRON_TIMEOUT_S) as response:
            data = json.loads(response.read().decode("utf-8"))
        reply = data["choices"][0]["message"].get("content") or ""
    except urllib.error.HTTPError as exc:
        raise LLMError(f"Nicrron answered HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LLMError(f"Nicrron unreachable ({type(exc).__name__})") from None
    except (KeyError, IndexError, ValueError, TypeError):
        raise LLMError("Nicrron returned an unexpected response shape") from None
    latency_ms = int((time.monotonic() - started) * 1000)

    # --- tracing: redacted copy only, and it can never break the call above ---
    try:
        payload = redact(
            messages, reply,
            model=model, session_id=session_id, agent_id=agent_id or config.AGENT_ID,
            project_id=config.secret("PRISMTRACE_PROJECT_ID"), latency_ms=latency_ms,
        )
        prism.send_trace(payload)
    except Exception:
        pass
    return reply


class Conversation:
    """One conversation = one session_id, kept for every turn."""

    def __init__(self, system_prompt: str | None = None, session_id: str | None = None):
        self.session_id = session_id or new_session_id()
        self.messages: list = []
        if system_prompt:
            self.messages.append({"role": "system", "content": system_prompt})

    def ask(self, text: str, **params) -> str:
        self.messages.append({"role": "user", "content": text})
        try:
            reply = call_llm(self.messages, session_id=self.session_id, **params)
        except Exception:
            self.messages.pop()
            raise
        self.messages.append({"role": "assistant", "content": reply})
        return reply
