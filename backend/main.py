"""The routes the interface calls (see the contract table in the plan). Handlers are plain `def`:
FastAPI runs them in its thread pool."""
import re
import json
import logging
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from backend import contract, download, eta, events, jobs, pipeline, settings
from backend.research import brief

log = logging.getLogger(__name__)


def _resume_pending() -> None:
    """Queued jobs never started before a restart are started again (running ones were turned
    into "Interrupted by a restart" errors by the registry)."""
    try:
        for job in jobs.registry().pending():
            pipeline.start(job.job_id)
    except Exception:
        log.exception("could not resume queued report jobs")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    _resume_pending()
    yield


app = FastAPI(title="Europa backend", lifespan=_lifespan)

ETA_SECONDS_PER_POINT = 0.6


def _simple_eta(job: jobs.Job) -> int:
    return max(0, round((100 - int(job.progress or 0)) * ETA_SECONDS_PER_POINT))


def _status_dict(job: jobs.Job) -> dict:
    d = job.as_dict()
    out = {name: d.get(name) for name in contract.STATUS_FIELDS}  # never events/event_offset
    if job.status in contract.TERMINAL:
        out["eta_seconds"] = 0
    elif job.status == "running":
        predicted = eta.predict_eta(job)
        out["eta_seconds"] = int(predicted) if predicted is not None else _simple_eta(job)
        out["interpolated_progress"] = eta.interpolate_progress(job)
        out["completed"] = eta.completed_stages(job)
    else:
        out["eta_seconds"] = _simple_eta(job)
        try:
            place = jobs.registry().queue_position(job.job_id)
        except jobs.JobStoreError:
            place = None
        # only while it actually waits: every slot taken or other queued jobs ahead of it
        if place and (place["position"] > 1 or place["running"] >= settings.MAX_RUNNING_JOBS):
            out["queue_position"] = place
    return out


def _job_or_404(job_id: str) -> jobs.Job:
    job = jobs.registry().get(job_id) if contract.JOB_ID_RE.fullmatch(job_id or "") else None
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/start")
def start(stock_code: str = Form(""), company_name: str = Form(""), mode: str = Form("full")) -> dict:
    code = (stock_code or "").strip()
    if not contract.TICKER_RE.fullmatch(code):
        raise HTTPException(status_code=400, detail="Invalid stock code.")
    from backend.sources import tickers
    try:
        code = tickers.normalise(code)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid stock code.")
    # the name is only a label until the SEC's own name is known: plain text, bounded
    name = re.sub(r"[\x00-\x1f<>{}]", "", (company_name or "")).strip()[:120]
    # there is one kind of report: every mode value runs it, and a company has one open job
    mode = "full"
    job, created = jobs.registry().create_or_existing(code, name, mode)
    if created:
        pipeline.start(job.job_id)
    return {"job_id": job.job_id, "received": {"stock_code": code, "company_name": name, "mode": mode}}


@app.get("/status/{job_id}")
def status(job_id: str) -> dict:
    return _status_dict(_job_or_404(job_id))


@app.get("/stream/{job_id}")
def stream_job(job_id: str) -> StreamingResponse:
    """The job's live events (server-sent events); ends with `done` or `error`."""
    if not contract.JOB_ID_RE.fullmatch(job_id or ""):
        raise HTTPException(status_code=404, detail="Job not found.")
    return StreamingResponse(events.astream(job_id, jobs.registry()), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.delete("/jobs/{job_id}")
def delete_job(job_id: str) -> dict:
    job = _job_or_404(job_id)
    root = settings.reports_dir()
    for name in (job.html_file, job.pdf_file):
        if not name or not contract.REPORT_FILE_RE.fullmatch(name):
            continue
        for path in (root / name, root / pipeline.ledger_file_name(name)):
            try:
                if path.is_file() or path.is_symlink():
                    path.unlink()
            except OSError as exc:
                log.warning("could not remove %s: %s", path, exc)
    jobs.registry().delete(job.job_id)
    return {"deleted": True}


@app.get("/download")
def download_file(file: str = "", inline: str = "") -> Response:
    try:
        path = download.resolve(file)
    except download.ReportMissing:
        raise HTTPException(status_code=404, detail="File not found.")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file.")
    if path.suffix == ".html":
        media_type = "text/html; charset=utf-8"
    else:
        media_type = "application/pdf"
    headers = {"Content-Security-Policy": download.REPORT_CSP, "X-Content-Type-Options": "nosniff",
               "Cache-Control": "no-store"}
    if str(inline).strip().lower() in ("1", "true", "yes", "on"):
        headers["Content-Disposition"] = "inline"
    else:
        headers["Content-Disposition"] = f'attachment; filename="{path.name}"'
    return Response(content=path.read_bytes(), media_type=media_type, headers=headers)


@app.get("/api/reports/mine")
def reports_mine(response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    rows = []
    for job in jobs.registry().finished():
        d = job.as_dict()
        d["ticker"] = job.stock_code
        rows.append({name: d.get(name) for name in contract.REPORT_ROW_FIELDS})
    return {"reports": rows}


def _chat_unavailable():
    yield "event: error\ndata: " + json.dumps({"message": "The report chat is unavailable."}) + "\n\n"
    yield "event: done\ndata: {}\n\n"


def _safe_stream(payload: dict):
    try:
        from backend import chat
        stream = chat.stream(payload)
        first = next(stream, None)
    except Exception:
        log.exception("report chat failed")
        yield from _chat_unavailable()
        return
    if first is None:
        yield from _chat_unavailable()
        return
    yield first
    try:
        yield from stream
    except Exception:
        log.exception("report chat failed mid-stream")
        yield from _chat_unavailable()


@app.post("/api/report-chat")
def report_chat(payload: dict | None = Body(None)) -> StreamingResponse:
    return StreamingResponse(_safe_stream(payload if isinstance(payload, dict) else {}),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


BRIEF_MAX_BODY = 64 * 1024


def _brief_reply(detail: str, status: int) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status, headers={"Cache-Control": "no-store"})


@app.post("/api/brief")
async def market_brief(request: Request) -> JSONResponse:
    """The markets app's "Quick brief" (backend.research.brief.write). The body is read here, at
    most 64 KB, and the brief is written in the thread pool (it waits on the model)."""
    too_large = _brief_reply("The request body is too large.", 413)
    try:
        if int(request.headers.get("content-length") or 0) > BRIEF_MAX_BODY:
            return too_large
    except ValueError:
        pass
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > BRIEF_MAX_BODY:
            return too_large
    try:
        payload = json.loads(bytes(body))
    except (ValueError, RecursionError):
        return _brief_reply("The request body must be JSON.", 400)
    try:
        result = await run_in_threadpool(brief.write, payload)
    except brief.BriefError as exc:
        return _brief_reply(exc.message, exc.status)
    except Exception:
        log.exception("the brief could not be written")
        return _brief_reply(brief.FAILED, 502)
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.backend_host(), port=settings.backend_port())
