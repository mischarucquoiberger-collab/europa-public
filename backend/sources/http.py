"""One HTTP client for every data source.

Why one client: the retry rules, the per-host rate limits, the disk cache and the three source
modes (live, record, replay) must be the same for the SEC and for Massive, and the network must be
reachable from exactly one function (`transport`) so tests can replace it.

Storage rules (cache and recordings):
- the key is a hash of the URL and the sorted params, never the headers: one header carries the
  SEC contact address, another the Massive key;
- a stored file holds `url`, `params`, `status`, `fetched_at` and `body`, and no request header;
- only a 200 is ever stored;
- Massive responses are licensed provider data: they go to the (git-ignored) cache only, never to
  the replay folder, which is committed.
"""
from __future__ import annotations

import gzip
import hashlib
import http.client
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from collections import deque
from pathlib import Path
from typing import Any, Callable, Mapping

from backend import settings

Transport = Callable[[str, dict, float], tuple[int, bytes]]

MODES = ("live", "record", "replay")
ATTEMPTS = 3                       # in total, for a 429, a 5xx or an unreachable host
BACKOFF = (1.0, 3.0)               # seconds before the second and the third attempt
RATE_LIMITS = {                    # requests per second, per host
    "www.sec.gov": 8,
    "data.sec.gov": 8,
    "api.massive.com": 5,
}
CACHE_ONLY_HOSTS = frozenset({"api.massive.com"})
SLUG_MAX = 60


class SourceUnavailable(RuntimeError):
    """A source could not answer: not found, not entitled, rate-limited or down after retries,
    unreachable, missing from the recordings in replay mode, or not configured (missing key)."""

    def __init__(self, url: str, reason: str):
        super().__init__(url, reason)
        self.url = url
        self.reason = reason

    def __str__(self) -> str:
        return f"{self.reason}: {self.url}"


# --- the network (the only function that touches it) ---------------------------------------

def _inflate(raw: bytes, encoding: str | None) -> bytes:
    """Undo gzip or deflate content encoding (urllib does not)."""
    enc = (encoding or "").strip().lower()
    try:
        if enc in ("gzip", "x-gzip") or (not enc and raw[:2] == b"\x1f\x8b"):
            return gzip.decompress(raw)
        if enc == "deflate":
            try:
                return zlib.decompress(raw)
            except zlib.error:
                return zlib.decompress(raw, -zlib.MAX_WBITS)   # raw deflate without a header
    except zlib.error as error:
        raise OSError(f"bad {enc or 'gzip'} body: {error}") from error
    return raw


def urllib_transport(url: str, headers: dict, timeout: float) -> tuple[int, bytes]:
    """GET `url`. Returns (status, body) for every HTTP answer, errors included, so the client
    decides what to retry; raises OSError when the host cannot be reached."""
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, _inflate(response.read(), response.headers.get("Content-Encoding"))
    except urllib.error.HTTPError as error:       # an answer, not an outage
        try:
            raw = error.read() or b""
        except OSError:
            raw = b""
        encoding = error.headers.get("Content-Encoding") if error.headers else None
        try:
            return error.code, _inflate(raw, encoding)
        except OSError:
            return error.code, b""
    except http.client.HTTPException as error:    # e.g. a truncated body
        raise OSError(f"{type(error).__name__}: {error}") from error


# --- storage names -------------------------------------------------------------------------

def _param_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _sorted_params(params: Mapping[str, Any] | None) -> list[tuple[str, str]]:
    return sorted((str(k), _param_value(v)) for k, v in (params or {}).items())


def _request_url(url: str, params: list[tuple[str, str]]) -> str:
    if not params:
        return url
    return url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)


def storage_key(url: str, params: Mapping[str, Any] | None = None) -> str:
    """sha256 of the URL plus the sorted params. Headers are never part of it."""
    material = json.dumps([url, _sorted_params(params)], separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-._")


def storage_name(url: str, params: Mapping[str, Any] | None = None) -> str:
    """`{host}/{slug of the path, max 60 chars}-{first 12 hex of the key}.json`, relative to the
    cache or replay folder. The slug only keeps letters, digits, dot, dash and underscore."""
    parts = urllib.parse.urlsplit(url)
    host = _safe(parts.hostname or "") or "nohost"
    slug = _safe(parts.path)[:SLUG_MAX].rstrip("-._") or "root"
    return f"{host}/{slug}-{storage_key(url, params)[:12]}.json"


# --- the client ----------------------------------------------------------------------------

class Client:
    """GET JSON or text with a disk cache, retries, per-host rate limits and three modes:

    - live:   the disk cache in `cache_dir` while younger than `ttl`, else the network;
    - record: always the network, and the answer is saved in `replay_dir` (and the cache);
    - replay: `replay_dir` only; the transport is never called; a missing recording raises.
    """

    timeout = 30.0          # seconds per request

    def __init__(self, mode: str | None = None, *, cache_dir: str | Path | None = None,
                 replay_dir: str | Path | None = None, transport: Transport | None = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.time):
        mode = (mode or settings.source_mode()).strip().lower()
        if mode not in MODES:
            raise ValueError(f"source mode must be one of {MODES}, not {mode!r}")
        self.mode = mode
        self._cache_dir = Path(cache_dir) if cache_dir is not None else None
        self._replay_dir = Path(replay_dir) if replay_dir is not None else None
        self._transport = transport or urllib_transport
        self._sleep = sleep
        self._clock = clock
        self._lock = threading.Lock()
        self._windows: dict[str, deque] = {}
        self.recorded: list[tuple[str, str]] = []    # (request URL, storage name) saved in record mode

    # folders are resolved when used, so a test (or OUTPUT_DIR) can move them after import
    def cache_dir(self) -> Path:
        return self._cache_dir if self._cache_dir is not None else settings.cache_dir()

    def replay_dir(self) -> Path:
        return self._replay_dir if self._replay_dir is not None else settings.replay_dir()

    # -- public --
    def get_json(self, url: str, *, params: Mapping[str, Any] | None = None,
                 headers: Mapping[str, str] | None = None, ttl: float = 3600) -> dict | list:
        """The parsed JSON body of a 200 answer; raises SourceUnavailable otherwise."""
        return self._get(url, params, headers, ttl, "json")

    def get_text(self, url: str, *, params: Mapping[str, Any] | None = None,
                 headers: Mapping[str, str] | None = None, ttl: float = 3600) -> str:
        """The decoded text body of a 200 answer; raises SourceUnavailable otherwise."""
        return self._get(url, params, headers, ttl, "text")

    # -- the flow --
    def _get(self, url: str, params, headers, ttl: float, kind: str):
        if not isinstance(url, str) or not url.startswith(("https://", "http://")):
            raise ValueError(f"not an http(s) URL: {url!r}")
        pairs = _sorted_params(params)
        full = _request_url(url, pairs)
        name = storage_name(url, params)

        if self.mode == "replay":
            stored = self._read(self.replay_dir() / name)
            if stored is None:
                raise SourceUnavailable(full, "no recording for this request (replay mode)")
            return self._body(stored, kind, full)

        if self.mode == "live":
            stored = self._read(self.cache_dir() / name)
            if stored is not None and self._fresh(stored, ttl):
                try:
                    return self._body(stored, kind, full)
                except SourceUnavailable:
                    pass                                   # a damaged cache file: fetch again

        raw = self._fetch(full, headers)
        body = self._decode(raw, kind, full)
        record = {"url": url, "params": dict(pairs), "status": 200,
                  "fetched_at": self._clock(), "body": body}
        self._write(self.cache_dir() / name, record)
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        if self.mode == "record" and host not in CACHE_ONLY_HOSTS:
            self._write(self.replay_dir() / name, record)
            self.recorded.append((full, name))
        return body

    def _fetch(self, full_url: str, headers) -> bytes:
        """Up to ATTEMPTS tries for 429, 5xx and unreachable; 404, 401 and 403 fail at once."""
        host = (urllib.parse.urlsplit(full_url).hostname or "").lower()
        last = "no answer"
        for attempt in range(ATTEMPTS):
            if attempt:
                self._sleep(BACKOFF[min(attempt, len(BACKOFF)) - 1])
            self._throttle(host)
            try:
                status, raw = self._transport(full_url, dict(headers or {}), self.timeout)
            except OSError as error:
                last = f"unreachable ({type(error).__name__})"
                continue
            if status == 200:
                return raw
            if status == 404:
                raise SourceUnavailable(full_url, "not found")
            if status in (401, 403):
                raise SourceUnavailable(full_url, "not entitled")
            if status == 429 or 500 <= status <= 599:
                last = f"HTTP {status}"
                continue
            raise SourceUnavailable(full_url, f"HTTP {status}")
        raise SourceUnavailable(full_url, f"{last} after {ATTEMPTS} attempts")

    def _throttle(self, host: str) -> None:
        """Sliding one-second window per host. A slot is reserved under the lock and the wait
        happens outside it, so threads for other hosts are never held up."""
        limit = RATE_LIMITS.get(host)
        if not limit:
            return
        with self._lock:
            window = self._windows.setdefault(host, deque())
            now = self._clock()
            while window and window[0] <= now - 1.0:
                window.popleft()
            at = now
            if len(window) >= limit:
                at = max(now, window[-limit] + 1.0, window[-1])
            window.append(at)
        if at > now:
            self._sleep(at - now)

    # -- storage --
    def _fresh(self, stored: dict, ttl: float) -> bool:
        fetched = stored.get("fetched_at")
        if not isinstance(fetched, (int, float)) or isinstance(fetched, bool):
            return False
        return self._clock() - fetched < ttl

    @staticmethod
    def _read(path: Path) -> dict | None:
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(stored, dict) or stored.get("status") != 200 or "body" not in stored:
            return None
        return stored

    @staticmethod
    def _write(path: Path, record: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        temp.write_text(json.dumps(record, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(temp, path)

    @staticmethod
    def _decode(raw: bytes, kind: str, url: str):
        if kind == "json":
            try:
                return json.loads(raw)
            except ValueError:
                raise SourceUnavailable(url, "the answer was not JSON") from None
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("cp1252", errors="replace")   # older EDGAR documents

    @staticmethod
    def _body(stored: dict, kind: str, url: str):
        body = stored["body"]
        if kind == "json":
            if isinstance(body, str):
                try:
                    return json.loads(body)
                except ValueError:
                    raise SourceUnavailable(url, "the stored answer is not JSON") from None
            return body
        return body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)


# --- one shared client ---------------------------------------------------------------------

_default: Client | None = None
_default_lock = threading.Lock()


def default_client() -> Client:
    """The process-wide client (so the rate limits are shared). Created on first use."""
    global _default
    with _default_lock:
        if _default is None:
            _default = Client()
        return _default


def set_default_client(client: Client | None) -> None:
    """Replace the shared client (tests); None makes the next default_client() build a new one."""
    global _default
    with _default_lock:
        _default = client
