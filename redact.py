"""redact(): builds the ONLY copy of a call that is allowed to leave for PRISM.

The model always receives the full prompt; this module never touches that copy.
Order per message: mask first, then cut, so a cut can never expose half a secret.
"""
import re

import config

# --- API keys / tokens -------------------------------------------------------
_SECRET_PATTERNS = [
    # well-known prefixes
    re.compile(r"\b(?:pt-sk|sk|pk|rk)-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{8,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"\bhf_[A-Za-z0-9]{20,}"),
    # JWT
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
    # private key blocks
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S),
]
# "Bearer xyz", "api_key=xyz", "token: xyz", "password = xyz" -> keep the label, mask the value
_LABELLED_SECRET = re.compile(
    r"(?i)\b(bearer\s+|(?:api[_-]?key|secret|token|password|passwd|pwd|access[_-]?key|auth)[\"']?\s*[:=]\s*[\"']?)"
    r"([^\s\"',;]{6,})"
)
# any long unbroken string that mixes letters and digits (hex digests, random tokens)
_LONG_TOKEN = re.compile(r"(?<![A-Za-z0-9_\-])[A-Za-z0-9_\-+/=]{24,}(?![A-Za-z0-9_\-])")

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")

# digit groups joined by single separators: phones, cards, long ids, 1,234,567,890
_NUMERIC = re.compile(r"(?<![A-Za-z0-9])\+?\(?\d(?:[ \t().,\-/]{0,2}\d)+(?![A-Za-z0-9])")
_ISO_DATE = re.compile(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}$")


def _mask_long_token(m: re.Match) -> str:
    s = m.group(0)
    if re.search(r"[A-Za-z]", s) and re.search(r"\d", s):
        return "[SECRET]"
    return s


def _mask_numeric(m: re.Match) -> str:
    s = m.group(0)
    digits = sum(c.isdigit() for c in s)
    has_sep = bool(re.search(r"[ \t()\-/]", s))
    if _ISO_DATE.fullmatch(s) and digits <= 8:
        return s
    if digits > 8:
        # 9+ digits: phone if it is shaped like one, otherwise a long number
        if (s.startswith("+") or has_sep) and digits <= 15:
            return "[PHONE]"
        return "[NUMBER]"
    if digits >= 7 and (s.startswith("+") or has_sep):
        return "[PHONE]"
    return s


def mask(text: str) -> str:
    """Mask emails, phone numbers, API keys/tokens and numbers longer than 8 digits."""
    # belt and braces: our own keys can never appear, whatever shape they have
    for name in ("NICRRON_API_KEY", "PRISMTRACE_API_KEY"):
        value = config.secret(name)
        if len(value) >= 6:
            text = text.replace(value, "[SECRET]")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[SECRET]", text)
    text = _LABELLED_SECRET.sub(lambda m: m.group(1) + "[SECRET]", text)
    text = _EMAIL.sub("[EMAIL]", text)
    text = _LONG_TOKEN.sub(_mask_long_token, text)
    text = _NUMERIC.sub(_mask_numeric, text)
    return text


def cut(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _as_text(content) -> str:
    """Flatten OpenAI-style content (string, or list of parts) to text. Non-text parts are dropped."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text", "")))
            else:
                parts.append("[non-text content]")
        return "\n".join(parts)
    return str(content)


def clean(text, max_chars: int | None = None) -> str:
    return cut(mask(_as_text(text)), max_chars or config.PRISM_MAX_CHARS)


def redact(messages: list, output: str, *, model: str, session_id: str, agent_id: str,
           project_id: str, latency_ms: int = 0) -> dict:
    """Return the exact JSON body for POST /api/traces. Nothing else is ever sent.

    Fields: the five the API requires (project_id, model, input_messages,
    output_message, latency_ms) plus session_id and agent_id. No metadata object,
    no user id, no token counts, no agent name.
    """
    hide_system = config.PRISM_HIDE_SYSTEM_PROMPT
    label = f"[system prompt {config.SYSTEM_PROMPT_VERSION}]"
    safe_messages = []
    for message in messages:
        role = str(message.get("role", "user"))
        if role in ("system", "developer") and hide_system:
            content = label
        else:
            content = clean(message.get("content"))
        safe_messages.append({"role": role, "content": content})
    return {
        "project_id": project_id,
        "model": model,
        "input_messages": safe_messages,
        "output_message": clean(output),
        "latency_ms": int(latency_ms) if config.PRISM_SEND_LATENCY else 0,
        "session_id": session_id,
        "agent_id": agent_id,
    }
