import sys
import types

import pytest
from fastapi.testclient import TestClient

from backend import contract, jobs, main, pipeline, settings


@pytest.fixture
def client(monkeypatch):
    started = []
    monkeypatch.setattr(pipeline, "start", lambda job_id: started.append(job_id))

    def normalise(symbol):
        s = symbol.strip().upper().replace("-", ".")
        if not contract.TICKER_RE.fullmatch(s):
            raise ValueError(symbol)
        return s
    from backend.sources import tickers
    monkeypatch.setattr(tickers, "normalise", normalise)
    c = TestClient(main.app)
    c.started = started
    return c


def _finished_report(ticker="AAPL"):
    reg = jobs.registry()
    job = reg.create(ticker, "Apple Inc.", "full")
    name = contract.report_file_name(ticker, job.job_id[:8])
    settings.reports_dir().mkdir(parents=True, exist_ok=True)
    (settings.reports_dir() / name).write_text("<!doctype html><p>hello</p>", encoding="utf-8")
    (settings.reports_dir() / pipeline.ledger_file_name(name)).write_text("{}", encoding="utf-8")
    reg.update(job.job_id, status="complete", step="Complete", progress=100, html_file=name,
               finished_at="2026-11-22T00:00:00Z", source_count=0)
    return job.job_id, name


def test_health(client):
    assert client.get("/health").json() == {"ok": True}


def test_start_normalises_and_dedupes(client):
    a = client.post("/start", data={"stock_code": " BRK-B ", "company_name": "Berkshire"})
    b = client.post("/start", data={"stock_code": "brk.b", "mode": "weird"})
    assert a.status_code == 200 and b.status_code == 200
    assert a.json()["job_id"] == b.json()["job_id"]
    assert a.json()["received"] == {"stock_code": "BRK.B", "company_name": "Berkshire", "mode": "full"}
    assert b.json()["received"]["mode"] == "full"
    assert client.started == [a.json()["job_id"]]  # started once
    assert jobs.registry().get(a.json()["job_id"]).stock_code == "BRK.B"


@pytest.mark.parametrize("code", ["7203", "TOOLONGX", "", "AB$"])
def test_start_rejects_bad_codes(client, code):
    r = client.post("/start", data={"stock_code": code})
    assert r.status_code == 400 and r.json()["detail"] == "Invalid stock code."


def test_status_fields(client):
    job_id = client.post("/start", data={"stock_code": "AAPL"}).json()["job_id"]
    r = client.get(f"/status/{job_id}")
    body = r.json()
    assert r.status_code == 200 and set(body) == set(contract.STATUS_FIELDS)
    assert body["job_id"] == job_id and body["status"] == "queued" and body["eta_seconds"] == 60
    assert client.get(f"/status/{'0' * 32}").status_code == 404
    bad = client.get("/status/not-a-job")
    assert bad.status_code == 404 and bad.json()["detail"] == "Job not found."


def test_download_guards_and_inline(client):
    job_id, name = _finished_report()
    for bad in ("../x", "report_AAPL_zz.html", "x.html", ""):
        r = client.get("/download", params={"file": bad})
        assert r.status_code == 400 and r.json()["detail"] == "Invalid file."
    target = settings.reports_dir() / name
    link = settings.reports_dir() / "report_EVIL_deadbeef.html"
    link.symlink_to(target)
    assert client.get("/download", params={"file": link.name}).status_code == 400
    assert client.get("/download", params={"file": "report_NONE_12345678.html"}).status_code == 404
    r = client.get("/download", params={"file": name, "inline": "1"})
    assert r.status_code == 200 and r.text.startswith("<!doctype html>")
    assert r.headers["content-type"] == "text/html; charset=utf-8"
    assert r.headers["content-security-policy"] == main.download.REPORT_CSP
    assert r.headers["content-disposition"] == "inline"
    r = client.get("/download", params={"file": name})
    assert r.headers["content-disposition"] == f'attachment; filename="{name}"'


def test_reports_mine_rows(client):
    job_id, name = _finished_report()
    client.post("/start", data={"stock_code": "MSFT"})  # queued: not listed
    r = client.get("/api/reports/mine")
    assert r.headers["cache-control"] == "no-store"
    rows = r.json()["reports"]
    assert len(rows) == 1 and tuple(rows[0]) == contract.REPORT_ROW_FIELDS
    assert rows[0]["ticker"] == "AAPL" and rows[0]["html_file"] == name and rows[0]["job_id"] == job_id


def test_delete_removes_files(client):
    job_id, name = _finished_report()
    r = client.delete(f"/jobs/{job_id}")
    assert r.status_code == 200 and r.json() == {"deleted": True}
    assert not (settings.reports_dir() / name).exists()
    assert not (settings.reports_dir() / pipeline.ledger_file_name(name)).exists()
    assert client.get(f"/status/{job_id}").status_code == 404
    assert client.delete(f"/jobs/{job_id}").status_code == 404


def test_report_chat_streams_fake(client, monkeypatch):
    fake = types.ModuleType("backend.chat")
    fake.stream = lambda payload: iter(['event: text\ndata: {"text": "hi"}\n\n', "event: done\ndata: {}\n\n"])
    monkeypatch.setitem(sys.modules, "backend.chat", fake)
    import backend
    monkeypatch.setattr(backend, "chat", fake, raising=False)
    r = client.post("/api/report-chat", json={"messages": []})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-store" and r.headers["x-accel-buffering"] == "no"
    assert '"hi"' in r.text and r.text.rstrip().endswith("data: {}")


def test_report_chat_unavailable(client, monkeypatch):
    fake = types.ModuleType("backend.chat")

    def broken(payload):
        raise RuntimeError("no model")
    fake.stream = broken
    monkeypatch.setitem(sys.modules, "backend.chat", fake)
    import backend
    monkeypatch.setattr(backend, "chat", fake, raising=False)
    r = client.post("/api/report-chat", json={"messages": []})
    assert "event: error" in r.text and "The report chat is unavailable." in r.text
    assert r.text.rstrip().endswith("event: done\ndata: {}")


def test_a_file_name_the_system_refuses_is_a_bad_request_not_a_crash(client):
    long_name = "report_" + "A" * 10000 + "_abcd1234.html"
    assert client.get("/download", params={"file": long_name}).status_code == 400
    assert client.get("/download", params={"file": "report_" + "A" * 13 + "_abcd1234.html"}).status_code == 400
    headers = client.get("/download", params={"file": "report_AAPL_ffffffff.html"}).headers
    assert client.get("/download", params={"file": "report_AAPL_ffffffff.html"}).status_code == 404


def test_start_has_one_mode_and_a_plain_bounded_name(client, monkeypatch):
    from backend import pipeline as _pipeline
    monkeypatch.setattr(_pipeline, "start", lambda job_id: None)
    first = client.post("/start", data={"stock_code": "aapl", "company_name": "<script>x</script>{{7*7}}" + "n" * 500, "mode": "fast"}).json()
    again = client.post("/start", data={"stock_code": "AAPL", "mode": "full"}).json()
    assert first["job_id"] == again["job_id"]                      # one open job per company, whatever the mode
    assert first["received"]["mode"] == "full"
    name = first["received"]["company_name"]
    assert len(name) <= 120 and "<" not in name and "{" not in name


# --- POST /api/brief (backend.research.brief) ---------------------------------------------------

BRIEF_BODY = {"ticker": "MSFT",
              "headlines": [{"source": "N1", "title": "Microsoft opens a data centre in Osaka",
                             "date": "2026-11-18", "publisher": "Example Wire", "description": ""}],
              "quarters": [{"fiscal_year": 2026, "fiscal_quarter": 3, "period_end": "2026-03-31",
                            "revenue": 82_940_000_000, "diluted_eps": 4.271, "filing_url": None,
                            "source": "F1"}]}


def _fake_brief_model(monkeypatch, reply):
    from backend import model
    asked = []

    def ask(messages, *, session_id, **params):
        asked.append(params)
        return reply
    monkeypatch.setattr(model, "ask", ask)
    return asked


def test_brief_route_returns_the_checked_brief(client, monkeypatch):
    asked = _fake_brief_model(monkeypatch, "Revenue was $82.9 billion in Q3 fiscal 2026 [F1]. "
                                           "You should buy the shares [N1].")
    r = client.post("/api/brief", json=BRIEF_BODY)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert set(body) == {"summary", "model", "withheld", "checked", "method"}
    assert body["summary"] == "Revenue was $82.9 billion in Q3 fiscal 2026 [F1]."
    assert body["withheld"] == ["You should buy the shares [N1]."]
    assert body["checked"] is True and body["method"] == "model"
    assert asked[0]["agent_id"] == "europa-market-brief"


@pytest.mark.parametrize("body", [{**BRIEF_BODY, "ticker": "7203"}, [1, 2], "MSFT"])
def test_brief_route_bad_requests(client, monkeypatch, body):
    asked = _fake_brief_model(monkeypatch, "unused")
    r = client.post("/api/brief", json=body)
    assert r.status_code == 400 and isinstance(r.json()["detail"], str) and asked == []


def test_brief_route_body_that_is_not_json(client, monkeypatch):
    _fake_brief_model(monkeypatch, "unused")
    for raw in (b"{not json", b"\xff\xfe", b"[" * 40000):
        r = client.post("/api/brief", content=raw, headers={"Content-Type": "application/json"})
        assert r.status_code == 400 and r.json() == {"detail": "The request body must be JSON."}


def test_brief_route_body_too_large(client, monkeypatch):
    asked = _fake_brief_model(monkeypatch, "unused")
    big = {**BRIEF_BODY, "padding": "x" * (64 * 1024)}
    r = client.post("/api/brief", json=big)
    assert r.status_code == 413 and r.json() == {"detail": "The request body is too large."}

    def chunks():                       # no Content-Length: the size is counted while reading
        for _ in range(70):
            yield b" " * 1024
    r = client.post("/api/brief", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413 and asked == []


def test_brief_route_no_source_data(client, monkeypatch):
    asked = _fake_brief_model(monkeypatch, "unused")
    r = client.post("/api/brief", json={"ticker": "MSFT", "headlines": [], "quarters": [{"fiscal_year": "x"}]})
    assert r.status_code == 422 and r.json() == {"detail": "No source data was available for that ticker."}
    assert asked == []


def test_brief_route_unexpected_failure_is_502_without_a_traceback(client, monkeypatch):
    from backend.research import brief

    def broken(payload, **kwargs):
        raise RuntimeError("secret internal detail")
    monkeypatch.setattr(brief, "write", broken)
    r = client.post("/api/brief", json=BRIEF_BODY)
    assert r.status_code == 502 and r.json() == {"detail": "The brief could not be written."}
    assert "secret" not in r.text and "Traceback" not in r.text


def test_brief_route_failure_inside_the_brief_is_502(client, monkeypatch):
    from backend import model

    def gate_broke(messages, **kwargs):
        raise KeyError("gate")
    monkeypatch.setattr(model, "ask", gate_broke)
    r = client.post("/api/brief", json=BRIEF_BODY)
    assert r.status_code == 502 and r.json() == {"detail": "The brief could not be written."}
