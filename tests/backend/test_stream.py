import itertools
import json
import threading
import time

from fastapi.testclient import TestClient

from backend import events, jobs, main


def _collect(gen, limit=500, timeout=10.0):
    """Run a generator in a thread with a deadline; returns (chunks, finished)."""
    out: list[str] = []
    worker = threading.Thread(target=lambda: out.extend(itertools.islice(gen, limit)), daemon=True)
    worker.start()
    worker.join(timeout)
    return out, not worker.is_alive()


def _parse(chunk: str) -> tuple[str, dict]:
    head, data = chunk.rstrip("\n").split("\n", 1)
    assert head.startswith("event: ") and data.startswith("data: ")
    return head[len("event: "):], json.loads(data[len("data: "):])


def test_format_event():
    assert events.format_event("stage", {"m": "é"}) == 'event: stage\ndata: {"m": "é"}\n\n'
    assert events.format_event("bad\nname", {}).startswith("event: message\n")


def test_a_finishing_job_streams_its_stages_then_done():
    reg = jobs.registry()
    job = reg.create("AAPL", "", "full")

    def work():
        for step in ("Starting", "Company Info", "Data Fetch"):
            time.sleep(0.03)
            reg.update(job.job_id, step=step, status="running", message=f"doing {step}")
        time.sleep(0.03)
        reg.update(job.job_id, step="Complete", status="complete", message="Report ready",
                   finished_at=jobs.now_iso(), html_file="report_AAPL_12345678.html")

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    chunks, finished = _collect(events.stream(job.job_id, reg, poll_seconds=0.01, keepalive_seconds=0.02))
    worker.join(5)
    assert finished
    parsed = [_parse(c) for c in chunks if not c.startswith(":")]
    stages = [data["message"] for kind, data in parsed if kind == "stage"]
    assert stages == ["Starting — doing Starting", "Company Info — doing Company Info",
                      "Data Fetch — doing Data Fetch", "Complete — Report ready"]
    kind, data = parsed[-1]
    assert kind == "done" and data["status"] == "complete" and data["html_file"] == "report_AAPL_12345678.html"
    assert all(set(d) == {"ts", "type", "message", "meta"} for k, d in parsed if k == "stage")


def test_an_unknown_job_yields_error_and_ends():
    chunks, finished = _collect(events.stream("0" * 32, jobs.registry(), poll_seconds=0.01))
    assert finished and len(chunks) == 2                 # the error, then `done`: a reader always gets an end
    assert _parse(chunks[0]) == ("error", {"message": "Job not found."})
    assert _parse(chunks[1])[0] == "done"


def test_an_idle_job_gets_keepalives_and_the_cap_ends_the_stream():
    reg = jobs.registry()
    job = reg.create("AAPL", "", "full")
    reg.update(job.job_id, step="Starting", status="running")
    chunks, finished = _collect(events.stream(job.job_id, reg, poll_seconds=0.005, keepalive_seconds=0.01,
                                              max_seconds=0.2))
    assert finished
    assert _parse(chunks[0])[0] == "stage"
    assert events.KEEPALIVE in chunks
    kind, data = _parse(chunks[-1])
    assert kind == "error" and "timed out" in data["message"]


def test_a_reader_behind_the_window_resumes_at_the_oldest_event():
    reg = jobs.registry()
    job = reg.create("AAPL", "", "full")
    for i in range(230):
        reg.append_event(job.job_id, "log", f"e{i}")
    reg.update(job.job_id, status="error", error="x", message="x", finished_at=jobs.now_iso())
    chunks, finished = _collect(events.stream(job.job_id, reg, poll_seconds=0.01))
    assert finished
    logs = [d["message"] for k, d in map(_parse, chunks) if k == "log"]
    assert logs == [f"e{i}" for i in range(30, 230)]
    assert _parse(chunks[-1]) == ("done", {"status": "error", "html_file": None, "error": "x"})


def test_stream_route():
    reg = jobs.registry()
    job = reg.create("AAPL", "", "full")
    reg.update(job.job_id, step="Starting", status="running", message="go")
    reg.update(job.job_id, step="Complete", status="warning", message="Report ready", finished_at=jobs.now_iso())
    client = TestClient(main.app)
    r = client.get(f"/stream/{job.job_id}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-store"
    assert "event: stage" in r.text and r.text.rstrip().split("\n")[-2] == "event: done"
    assert '"status": "warning"' in r.text
    r = client.get(f"/stream/{'0' * 32}")
    assert r.status_code == 200 and "event: error" in r.text
    assert client.get("/stream/not-a-job").status_code == 404


def test_status_adds_eta_details_but_never_events():
    reg = jobs.registry()
    client = TestClient(main.app)
    job = reg.create("AAPL", "", "full")
    reg.update(job.job_id, step="Starting", status="running", started_at=jobs.now_iso(), progress=2)
    reg.update(job.job_id, step="Company Info", progress=8)
    body = client.get(f"/status/{job.job_id}").json()
    assert "events" not in body and "event_offset" not in body
    assert body["eta_seconds"] > 0 and 8 <= body["interpolated_progress"] < 15
    assert list(body["completed"]) == ["Starting"]
    # queued behind three running jobs: its place in line
    others = [reg.create(code, "", "full") for code in ("MSFT", "NVDA", "META")]
    for other in others[:2]:
        assert reg.claim(other.job_id)
    waiting = others[2]
    assert reg.claim(waiting.job_id) is False
    body = client.get(f"/status/{waiting.job_id}").json()
    assert body["status"] == "queued" and body["queue_position"] == {"position": 1, "running": 3}
    reg.update(job.job_id, step="Complete", status="complete", progress=100, finished_at=jobs.now_iso())
    body = client.get(f"/status/{job.job_id}").json()
    assert body["eta_seconds"] == 0 and "events" not in body
