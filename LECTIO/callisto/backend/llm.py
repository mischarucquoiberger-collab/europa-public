"""Nicrron models. Every model call goes through the repo-root call_llm() (prism-nicrron/llm.py),
which calls Nicrron and sends a redacted trace to PRISM.

Public surface (unchanged for the rest of the package and the tests):
  MODEL_FAST, MODEL_STRONG, model(name) -> object with .bind(**params) and .invoke(messages, config=None)
  returning a message with .content, and chat(prompt, model_name, system) -> str.
Keys come from the repo-root .env only (backend/_env.py).
"""
import importlib.util
import os
import sys
import threading
import uuid

from langchain_core.messages import AIMessage

from backend import tracing
from backend._env import REPO_ROOT, load_env

load_env()

BASE_URL = os.environ.get("NICRRON_BASE_URL", "https://api.nicrron.ai/v1")
MODEL_FAST = os.environ.get("MODEL_FAST", "anthropic/claude-haiku-5-5")      # reading / extraction
MODEL_STRONG = os.environ.get("MODEL_STRONG", "anthropic/claude-sonnet-5-5")  # comparing / writing

TIMEOUT_S = "30"   # the old ChatOpenAI timeout; root config reads NICRRON_TIMEOUT_S (real env wins)
MAX_RETRIES = 1

_root_llm = None
_root_lock = threading.Lock()


def _root():
    """Load prism-nicrron/llm.py by path under a distinct name, so the root `backend` package (reports)
    and this package (`backend`) never shadow each other. Root llm.py imports config, prism, redact as
    top-level modules; the repo root is on sys.path only while it loads."""
    global _root_llm
    if _root_llm is not None:
        return _root_llm
    with _root_lock:
        if _root_llm is not None:
            return _root_llm
        root = str(REPO_ROOT)
        for name in ("config", "prism", "redact"):
            m = sys.modules.get(name)
            if m is not None and not str(getattr(m, "__file__", "") or "").startswith(root):
                raise ImportError(f"a different top-level '{name}' module is already loaded")
        os.environ.setdefault("NICRRON_TIMEOUT_S", TIMEOUT_S)
        saved = sys.path[:]
        sys.path.insert(0, root)
        try:
            spec = importlib.util.spec_from_file_location("_prism_root_llm", REPO_ROOT / "llm.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        finally:
            sys.path[:] = saved
        _root_llm = mod
        return mod


# caller function -> PRISM agent role (callisto-<role>)
_ROLES = {"route": "router", "pick_news": "news", "write": "writer", "review": "skeptic",
          "_rewrite": "council-merge", "_ask_member": "council", "_write": "writer", "chat": "desk"}


def _role() -> str:
    f = sys._getframe(2)
    for _ in range(8):
        if f is None:
            break
        role = _ROLES.get(f.f_code.co_name)
        if role and f.f_code.co_filename != __file__:
            return role
        f = f.f_back
    return "desk"


_ROLE_OF = {"system": "system", "human": "user", "user": "user", "ai": "assistant", "assistant": "assistant"}


def _to_dicts(messages) -> list:
    out = []
    for m in messages:
        if isinstance(m, tuple):
            role, content = m
        elif isinstance(m, dict):
            role, content = m.get("role", "user"), m.get("content", "")
        else:  # a langchain message object
            role, content = getattr(m, "type", "user"), getattr(m, "content", "")
        out.append({"role": _ROLE_OF.get(role, role), "content": content})
    return out


def _transient(err: Exception) -> bool:
    text = str(err)
    return "unreachable" in text or "HTTP 5" in text or "HTTP 429" in text


class NicrronModel:
    """Stand-in for the old ChatOpenAI object: .bind(**params) and .invoke(messages, config=None)."""

    def __init__(self, name: str, params: dict | None = None):
        self.model_name = name
        self.params = dict(params or {})

    def bind(self, **params) -> "NicrronModel":
        return NicrronModel(self.model_name, {**self.params, **params})

    def invoke(self, messages, config=None, **kwargs) -> AIMessage:
        if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("CALLISTO_TEST_LIVE"):
            # tests run with no live model, exactly as the original did without a key
            raise RuntimeError("live model calls are off under pytest")
        root = _root()
        sid = tracing.current_session() or f"callisto-{uuid.uuid4().hex[:12]}"
        role = _role()
        # temperature=0 lets Nicrron cache repeat answers (faster rehearsed demos)
        params = {"temperature": 0, **self.params}
        for attempt in range(MAX_RETRIES + 1):
            try:
                text = root.call_llm(_to_dicts(messages), session_id=sid, model=self.model_name,
                                     agent_id=f"callisto-{role}", **params)
                return AIMessage(content=text)
            except root.LLMError as e:
                if attempt >= MAX_RETRIES or not _transient(e):
                    raise


def model(name: str = MODEL_FAST) -> NicrronModel:
    return NicrronModel(name)


def chat(prompt: str, model_name: str = MODEL_FAST, system: str | None = None) -> str:
    messages = ([("system", system)] if system else []) + [("human", prompt)]
    return model(model_name).invoke(messages).content
