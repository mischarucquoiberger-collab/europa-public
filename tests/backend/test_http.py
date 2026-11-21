"""The one HTTP client: cache, record, replay, retries, rate limits. A fake transport stands in
for the network; a fake clock and sleep stand in for time."""
import gzip
import http.server
import json
import re
import socket
import threading

import pytest

from backend.sources import http as source_http
from backend.sources.http import Client, SourceUnavailable

SEC_URL = "https://data.sec.gov/submissions/CIK0000320193.json"
SECRET_AGENT = "Secret Person secret.person@example.invalid"
SECRET_KEY = "mk-SECRET-key-0123456789"


class FakeTime:
    def __init__(self, now: float = 1_000_000.0):
        self.now = now
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeTransport:
    """Answers in order (then `default`); an exception in the list is raised."""

    def __init__(self, *answers, default=(200, b'{"ok": true}')):
        self.answers = list(answers)
        self.default = default
        self.calls: list[dict] = []

    def __call__(self, url, headers, timeout):
        self.calls.append({"url": url, "headers": dict(headers), "timeout": timeout})
        answer = self.answers.pop(0) if self.answers else self.default
        if isinstance(answer, BaseException):
            raise answer
        return answer


def make(tmp_path, mode="live", transport=None, clock=None):
    clock = clock or FakeTime()
    transport = transport if transport is not None else FakeTransport()
    client = Client(mode, cache_dir=tmp_path / "cache", replay_dir=tmp_path / "replay",
                    transport=transport, sleep=clock.sleep, clock=clock.clock)
    return client, transport, clock


def stored_files(tmp_path):
    return sorted(p for p in tmp_path.rglob("*") if p.is_file())


# --- cache ---------------------------------------------------------------------------------

def test_a_cache_hit_makes_no_second_transport_call(tmp_path):
    client, transport, _ = make(tmp_path)
    assert client.get_json(SEC_URL) == {"ok": True}
    assert client.get_json(SEC_URL) == {"ok": True}
    assert len(transport.calls) == 1


def test_ttl_expiry_refetches(tmp_path):
    client, transport, clock = make(tmp_path)
    client.get_json(SEC_URL, ttl=60)
    clock.now += 59
    client.get_json(SEC_URL, ttl=60)
    assert len(transport.calls) == 1
    clock.now += 2
    client.get_json(SEC_URL, ttl=60)
    assert len(transport.calls) == 2


def test_two_different_params_give_two_files_and_param_order_does_not(tmp_path):
    client, transport, _ = make(tmp_path)
    client.get_json(SEC_URL, params={"page": 1})
    client.get_json(SEC_URL, params={"page": 2})
    assert len(stored_files(tmp_path / "cache")) == 2
    assert transport.calls[0]["url"].endswith("?page=1")
    assert source_http.storage_name(SEC_URL, {"a": 1, "b": 2}) == source_http.storage_name(SEC_URL, {"b": 2, "a": 1})
    # headers never change where an answer is stored
    client.get_json(SEC_URL, params={"page": 1}, headers={"User-Agent": "someone else"})
    assert len(transport.calls) == 2


# --- record and replay ---------------------------------------------------------------------

def test_record_writes_a_replay_file_without_request_headers(tmp_path):
    client, transport, _ = make(tmp_path, mode="record")
    headers = {"User-Agent": SECRET_AGENT, "Authorization": f"Bearer {SECRET_KEY}"}
    client.get_json(SEC_URL, params={"limit": 5}, headers=headers)
    assert transport.calls[0]["headers"] == headers                    # sent ...

    name = source_http.storage_name(SEC_URL, {"limit": 5})
    assert re.fullmatch(r"data\.sec\.gov/[A-Za-z0-9._-]{1,60}-[0-9a-f]{12}\.json", name)
    replay_file = tmp_path / "replay" / name
    stored = json.loads(replay_file.read_text())
    assert set(stored) == {"url", "params", "status", "fetched_at", "body"}
    assert stored["url"] == SEC_URL and stored["params"] == {"limit": "5"} and stored["status"] == 200
    assert (tmp_path / "cache" / name).exists()                        # record also fills the cache
    assert client.recorded == [(SEC_URL + "?limit=5", name)]

    for path in stored_files(tmp_path):                                # ... but never stored
        text = path.read_text()
        for leaked in (SECRET_AGENT, "secret.person@example.invalid", SECRET_KEY, "User-Agent", "Authorization"):
            assert leaked not in text, (path.name, leaked)
        assert "secret" not in path.name.lower()


def test_record_always_fetches(tmp_path):
    client, transport, _ = make(tmp_path, mode="record")
    client.get_json(SEC_URL)
    client.get_json(SEC_URL)
    assert len(transport.calls) == 2


def test_replay_never_calls_the_transport(tmp_path):
    recorder, _, _ = make(tmp_path, mode="record", transport=FakeTransport((200, b'{"n": 7}')))
    recorder.get_json(SEC_URL)
    recorder.get_text("https://www.sec.gov/Archives/edgar/data/1/2/doc.htm")

    replayer, transport, _ = make(tmp_path, mode="replay")
    assert replayer.get_json(SEC_URL) == {"n": 7}
    assert replayer.get_text("https://www.sec.gov/Archives/edgar/data/1/2/doc.htm") == '{"ok": true}'
    assert transport.calls == []


def test_replay_of_a_missing_recording_names_the_url(tmp_path):
    client, transport, _ = make(tmp_path, mode="replay")
    missing = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json"
    with pytest.raises(SourceUnavailable) as caught:
        client.get_json(missing, params={"x": "y"})
    assert missing in str(caught.value)
    assert caught.value.url.startswith(missing)
    assert transport.calls == []


def test_replay_ignores_the_cache_and_live_ignores_the_recordings(tmp_path):
    live, _, _ = make(tmp_path, mode="live")
    live.get_json(SEC_URL)                                             # cache only
    replay, _, _ = make(tmp_path, mode="replay")
    with pytest.raises(SourceUnavailable):
        replay.get_json(SEC_URL)


def test_massive_answers_are_never_recorded_into_the_replay_folder(tmp_path):
    client, _, _ = make(tmp_path, mode="record")
    client.get_json("https://api.massive.com/v3/reference/tickers/AAPL")
    assert stored_files(tmp_path / "replay") == []
    assert len(stored_files(tmp_path / "cache")) == 1
    assert client.recorded == []


# --- retries and errors --------------------------------------------------------------------

def test_a_429_then_200_succeeds_after_one_sleep(tmp_path):
    client, transport, clock = make(tmp_path, transport=FakeTransport((429, b"slow down"), (200, b"[1, 2]")))
    assert client.get_json(SEC_URL) == [1, 2]
    assert len(transport.calls) == 2
    assert clock.sleeps == [1.0]


def test_three_500s_raise_and_nothing_is_stored(tmp_path):
    transport = FakeTransport(default=(500, b"oops"))
    client, _, clock = make(tmp_path, mode="record", transport=transport)
    with pytest.raises(SourceUnavailable) as caught:
        client.get_json(SEC_URL)
    assert len(transport.calls) == 3
    assert clock.sleeps == [1.0, 3.0]
    assert "500" in caught.value.reason and SEC_URL in str(caught.value)
    assert stored_files(tmp_path) == []


@pytest.mark.parametrize("status, reason", [(404, "not found"), (403, "not entitled"), (401, "not entitled")])
def test_404_401_and_403_raise_at_once_without_retry(tmp_path, status, reason):
    transport = FakeTransport(default=(status, b'{"error": "x"}'))
    client, _, clock = make(tmp_path, mode="record", transport=transport)
    with pytest.raises(SourceUnavailable) as caught:
        client.get_json(SEC_URL)
    assert caught.value.reason == reason
    assert len(transport.calls) == 1 and clock.sleeps == []
    assert stored_files(tmp_path) == []


def test_an_unreachable_host_is_retried_then_raises(tmp_path):
    transport = FakeTransport(OSError("down"), OSError("down"), OSError("down"))
    client, _, clock = make(tmp_path, transport=transport)
    with pytest.raises(SourceUnavailable) as caught:
        client.get_json(SEC_URL)
    assert "unreachable" in caught.value.reason
    assert len(transport.calls) == 3 and clock.sleeps == [1.0, 3.0]


def test_a_200_that_is_not_json_raises_and_is_not_stored(tmp_path):
    client, _, _ = make(tmp_path, transport=FakeTransport((200, b"<html>maintenance</html>")))
    with pytest.raises(SourceUnavailable):
        client.get_json(SEC_URL)
    assert stored_files(tmp_path) == []


def test_an_unknown_mode_is_refused(tmp_path):
    with pytest.raises(ValueError):
        Client("sometimes", cache_dir=tmp_path, replay_dir=tmp_path)


def test_the_mode_defaults_to_the_setting():
    assert Client().mode == "replay"                                   # tests/conftest.py sets it


# --- rate limits ---------------------------------------------------------------------------

def test_the_rate_limiter_sleeps_when_more_than_8_sec_requests_fall_within_a_second(tmp_path):
    client, transport, clock = make(tmp_path)
    for i in range(8):
        client.get_json(f"https://data.sec.gov/submissions/CIK{i:010d}.json")
    assert clock.sleeps == []
    client.get_json("https://data.sec.gov/submissions/CIK0000000099.json")
    assert clock.sleeps == [pytest.approx(1.0)]
    assert len(transport.calls) == 9


def test_requests_spread_over_time_do_not_sleep(tmp_path):
    client, _, clock = make(tmp_path)
    for i in range(20):
        client.get_json(f"https://www.sec.gov/files/x{i}.json")
        clock.now += 0.2                                               # five a second
    assert clock.sleeps == []


def test_massive_is_limited_to_5_a_second_and_other_hosts_are_not_limited(tmp_path):
    client, _, clock = make(tmp_path)
    for i in range(5):
        client.get_json(f"https://api.massive.com/v3/reference/tickers/A{i}")
    for i in range(30):
        client.get_json(f"https://example.org/x{i}.json")
    assert clock.sleeps == []
    client.get_json("https://api.massive.com/v3/reference/tickers/ZZ")
    assert clock.sleeps == [pytest.approx(1.0)]


def test_the_limiter_is_thread_safe(tmp_path):
    clock_lock = threading.Lock()
    slept: list[float] = []

    def sleep(seconds):
        with clock_lock:
            slept.append(seconds)

    client = Client("live", cache_dir=tmp_path / "c", replay_dir=tmp_path / "r", transport=FakeTransport(),
                    sleep=sleep, clock=lambda: 5000.0)                 # time stands still
    threads = [threading.Thread(target=client.get_json, args=(f"https://data.sec.gov/x{i}.json",))
               for i in range(24)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # 24 requests at one instant: 8 go now, 8 wait one second, 8 wait two
    assert sorted(slept) == [pytest.approx(1.0)] * 8 + [pytest.approx(2.0)] * 8


# --- the shared client ---------------------------------------------------------------------

def test_default_client_is_shared_and_replaceable(tmp_path):
    try:
        source_http.set_default_client(None)
        first = source_http.default_client()
        assert source_http.default_client() is first
        mine, _, _ = make(tmp_path)
        source_http.set_default_client(mine)
        assert source_http.default_client() is mine
    finally:
        source_http.set_default_client(None)


def test_default_folders_follow_output_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "elsewhere"))
    client = Client("live", transport=FakeTransport())
    client.get_json(SEC_URL)
    assert len(stored_files(tmp_path / "elsewhere" / "cache")) == 1


# --- the default transport, against a server on this machine -------------------------------

class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/gz":
            body = gzip.compress(b'{"zipped": true}')
            self.send_response(200)
            self.send_header("Content-Encoding", "gzip")
        else:
            body = b'{"error": "nothing here"}'
            self.send_response(404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def local_server():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_the_default_transport_inflates_gzip_and_returns_error_statuses(local_server):
    status, body = source_http.urllib_transport(local_server + "/gz", {"Accept-Encoding": "gzip"}, 5)
    assert (status, json.loads(body)) == (200, {"zipped": True})
    status, body = source_http.urllib_transport(local_server + "/missing", {}, 5)
    assert status == 404 and b"nothing here" in body


def test_the_default_transport_raises_oserror_when_unreachable():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()                                                      # nothing listens there now
    with pytest.raises(OSError):
        source_http.urllib_transport(f"http://127.0.0.1:{port}/", {}, 2)
