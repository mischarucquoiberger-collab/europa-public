"""Settings. Everything secret comes from .env (or the real environment); nothing is hardcoded."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_env(path: Path = ROOT / ".env") -> None:
    """Minimal .env reader. Real environment variables win over the file."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and value:
            os.environ.setdefault(key, value)


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, "")))
    except ValueError:
        return default


load_env()

# --- model provider (Nicrron, OpenAI-compatible) ---
NICRRON_BASE_URL = os.environ.get("NICRRON_BASE_URL", "https://api.nicrron.ai/v1").rstrip("/")
NICRRON_MODEL = os.environ.get("NICRRON_MODEL", "nicrron/auto")
NICRRON_TIMEOUT_S = float(os.environ.get("NICRRON_TIMEOUT_S", "60"))

# --- PRISM ---
PRISMTRACE_HOST = os.environ.get("PRISMTRACE_HOST", "https://api.prism.blockconvey.com").rstrip("/")
PRISM_TIMEOUT_S = float(os.environ.get("PRISM_TIMEOUT_S", "3"))
PRISM_ENABLED = _bool("PRISM_ENABLED", True)

# --- privacy ---
PRISM_HIDE_SYSTEM_PROMPT = _bool("PRISM_HIDE_SYSTEM_PROMPT", True)
PRISM_MAX_CHARS = _int("PRISM_MAX_CHARS", 500)
SYSTEM_PROMPT_VERSION = os.environ.get("PRISM_SYSTEM_PROMPT_VERSION", "v1")
# latency_ms is a required field of POST /api/traces. 0 = "unmeasured"; set true to send the real value.
PRISM_SEND_LATENCY = _bool("PRISM_SEND_LATENCY", False)

# One stable id for this agent. Do not change it between runs.
AGENT_ID = os.environ.get("PRISM_AGENT_ID", "prism-nicrron-agent")


def secret(name: str) -> str:
    """Read a secret at call time. Returns '' when unset. Never log the result."""
    return os.environ.get(name, "").strip()
