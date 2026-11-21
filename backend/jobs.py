"""Durable report jobs on a local SQLite database (settings.jobs_db(), under OUTPUT_DIR).

Ported from the original product's registry (app/services/report_jobs.py):
- one row per job: status / stock_code / mode / created_at / finished_at as columns, the whole
  Job as a JSON payload; WAL mode, a busy timeout, every write inside BEGIN IMMEDIATE, so
  admission and claims are atomic across threads and processes;
- admission: a second start for the same stock_code and mode while one is queued or running
  returns the open job; `claim` moves a queued job to running only while fewer than
  settings.MAX_RUNNING_JOBS run; `queue_position` reports a queued job's place in line;
- restart: on first use of a registry, every job still `running` becomes an explicit error
  ("Interrupted by a restart": its work cannot be resumed safely); queued jobs never started,
  so they stay queued and `pending()` returns them for a caller to restart;
- events: `{ts, type, message, meta}`, the newest 200 kept, `event_offset` = absolute index of
  events[0] (for the live stream); a `stage` event on every step change;
- retention: at most the newest 60 finished jobs are kept.

Reads return detached copies; change a job only through `update` / `append_event` / `claim`.
`stage_history` stays the list of step names the interface and tests read; each step's
timestamps and duration are kept beside it in `stage_timings` (the ETA learns from those).
"""
from __future__ import annotations

import dataclasses
import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from backend import contract, settings

log = logging.getLogger(__name__)

EVENT_LIMIT = 200          # events kept per job (the original's cap)
RETENTION = 60             # finished jobs kept (the original's cap)
INTERRUPTED = "Interrupted by a restart"
SCHEMA_VERSION = 1
LEGACY_JSON = "jobs.json"  # the registry file this database replaces

_ACTIVE = ("queued", "running")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _iso_ms(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_ts(value) -> float | None:
    """An ISO timestamp written by this module (or None) -> epoch seconds."""
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


@dataclass
class Job:
    job_id: str
    stock_code: str
    company_name: str = ""
    mode: str = "full"
    status: str = "queued"
    step: str = "Starting"
    message: str = "Queued"
    error: str | None = None
    progress: int = 0
    eta_seconds: int | None = None
    created_at: str = field(default_factory=now_iso)
    started_at: str | None = None
    finished_at: str | None = None
    html_file: str | None = None
    pdf_file: str | None = None
    sources: list = field(default_factory=list)
    source_count: int = 0
    edinet_count: int = 0
    edinet_scanned: int = 0
    edinet_total: int = 0
    financial_rows: int = 0
    price_rows: int = 0
    financials_source: str | None = None
    warnings: list = field(default_factory=list)
    stage_history: list = field(default_factory=list)
    # {stage, started_at, ended_at, duration} per entry of stage_history (ended_at/duration
    # stay None while the stage runs); stage_started_at = when the current step began
    stage_timings: list = field(default_factory=list)
    stage_started_at: str | None = None
    events: list = field(default_factory=list)
    event_offset: int = 0

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


_FIELDS = {f.name for f in dataclasses.fields(Job)}


class JobStoreError(RuntimeError):
    """The job database could not be read or written."""


def _push_event(job: Job, event_type: str, message: str, meta: dict | None = None) -> None:
    job.events.append({"ts": now_iso(), "type": str(event_type), "message": str(message),
                       "meta": dict(meta or {})})
    dropped = len(job.events) - EVENT_LIMIT
    if dropped > 0:
        job.events = job.events[dropped:]
        job.event_offset = int(job.event_offset or 0) + dropped


def _close_stage(job: Job, now: float) -> None:
    """Close the running entry of stage_timings with its end time and duration."""
    if not job.stage_timings:
        return
    last = job.stage_timings[-1]
    if not isinstance(last, dict) or last.get("ended_at") is not None:
        return
    began = parse_ts(last.get("started_at"))
    last["ended_at"] = _iso_ms(now)
    last["duration"] = round(max(0.0, now - began), 3) if began is not None else None


def _enter_stage(job: Job, step: str, now: float) -> None:
    _close_stage(job, now)
    job.stage_history.append(step)
    job.stage_timings.append({"stage": step, "started_at": _iso_ms(now), "ended_at": None, "duration": None})
    job.stage_started_at = _iso_ms(now)


def _interrupt(job: Job) -> None:
    job.status = "error"
    job.error = INTERRUPTED
    job.message = INTERRUPTED
    job.finished_at = job.finished_at or now_iso()
    _close_stage(job, time.time())
    _push_event(job, "error", INTERRUPTED, {"step": job.step})


class Registry:
    """The job registry on one SQLite file. Construction does no I/O; the first use creates
    the schema, imports a legacy jobs.json once and applies the restart rule."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._local = threading.local()      # one connection per thread
        self._init_lock = threading.Lock()
        self._write_lock = threading.RLock()  # serialises this process's writers (SQLite does it across processes)
        self._ready = False

    # connection ------------------------------------------------------------------------------
    def _open(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            return conn
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.path), timeout=5.0, isolation_level=None, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA synchronous=FULL")
        except (OSError, sqlite3.Error) as exc:
            raise JobStoreError("The report job database is unavailable.") from exc
        self._local.conn = conn
        return conn

    def _conn(self) -> sqlite3.Connection:
        conn = self._open()
        if not self._ready:
            with self._init_lock:
                if not self._ready:
                    with self._write_lock:
                        self._initialize(conn)
                    self._ready = True
        return conn

    @contextmanager
    def _tx(self, conn: sqlite3.Connection | None = None):
        conn = conn or self._conn()  # before the write lock: first use initialises under it
        with self._write_lock:
            try:
                conn.execute("BEGIN IMMEDIATE")
            except sqlite3.Error as exc:
                raise JobStoreError("The report job database is busy.") from exc
            try:
                yield conn
                conn.execute("COMMIT")
            except sqlite3.Error as exc:
                self._rollback(conn)
                raise JobStoreError("A report job database write failed.") from exc
            except BaseException:
                self._rollback(conn)
                raise

    @staticmethod
    def _rollback(conn: sqlite3.Connection) -> None:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass

    def close(self) -> None:
        """Close this thread's connection (others close when their thread ends)."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            self._local.conn = None
            conn.close()

    # schema, legacy import, restart rule -----------------------------------------------------
    def _initialize(self, conn: sqlite3.Connection) -> None:
        try:
            if str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() != "wal":
                conn.execute("PRAGMA journal_mode=WAL")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                raise JobStoreError("Unsupported report job database version.")
        except sqlite3.Error as exc:
            raise JobStoreError("The report job database is unavailable.") from exc
        with self._tx(conn) as c:
            c.execute("""CREATE TABLE IF NOT EXISTS report_jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    stock_code TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    finished_at TEXT,
                    payload TEXT NOT NULL
                )""")
            c.execute("CREATE INDEX IF NOT EXISTS report_jobs_status ON report_jobs(status)")
            c.execute("CREATE INDEX IF NOT EXISTS report_jobs_symbol ON report_jobs(stock_code, mode, status)")
            c.execute("CREATE TABLE IF NOT EXISTS report_meta (key TEXT PRIMARY KEY, value TEXT)")
            c.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            self._import_legacy(c)
            for row in c.execute("SELECT * FROM report_jobs WHERE status='running'").fetchall():
                job = self._decode(row)
                if job is None:
                    continue
                _interrupt(job)
                self._write(c, job)
            self._prune(c)

    def _import_legacy(self, c: sqlite3.Connection) -> None:
        """Finished jobs of an old jobs.json, once; the file itself is left alone."""
        legacy = self.path.parent / LEGACY_JSON
        if c.execute("SELECT 1 FROM report_meta WHERE key='legacy_json_imported'").fetchone():
            return
        if not legacy.is_file():
            return
        try:
            raw = json.loads(legacy.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("could not read %s: %s", legacy, exc)
            raw = {}
        items = raw.get("jobs", []) if isinstance(raw, dict) else []
        imported = 0
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict) or not contract.JOB_ID_RE.fullmatch(str(item.get("job_id", ""))):
                continue
            if item.get("status") not in contract.TERMINAL or not isinstance(item.get("stock_code"), str):
                continue
            try:
                job = Job(**{k: v for k, v in item.items() if k in _FIELDS})
                payload = self._encode(job)
            except (TypeError, ValueError):
                continue
            cur = c.execute("""INSERT OR IGNORE INTO report_jobs
                    (job_id, status, stock_code, mode, created_at, finished_at, payload) VALUES (?,?,?,?,?,?,?)""",
                            (job.job_id, job.status, job.stock_code, job.mode, job.created_at, job.finished_at, payload))
            imported += cur.rowcount
        c.execute("INSERT OR REPLACE INTO report_meta(key, value) VALUES ('legacy_json_imported', ?)", (now_iso(),))
        log.info("imported %d finished jobs from %s", imported, legacy)

    # rows ------------------------------------------------------------------------------------
    @staticmethod
    def _encode(job: Job) -> str:
        if job.status not in contract.STATUSES:
            raise ValueError(f"invalid job status: {job.status!r}")
        return json.dumps(job.as_dict(), ensure_ascii=False, separators=(",", ":"), default=str)

    @staticmethod
    def _decode(row) -> Job | None:
        try:
            payload = json.loads(row["payload"])
            job = Job(**{k: v for k, v in payload.items() if k in _FIELDS})
        except (TypeError, ValueError, AttributeError) as exc:
            log.error("unreadable report job row %s: %s", row["job_id"], exc)
            return None
        job.status = row["status"]
        return job

    def _insert(self, c: sqlite3.Connection, job: Job) -> None:
        c.execute("""INSERT INTO report_jobs (job_id, status, stock_code, mode, created_at, finished_at, payload)
                     VALUES (?,?,?,?,?,?,?)""",
                  (job.job_id, job.status, job.stock_code, job.mode, job.created_at, job.finished_at,
                   self._encode(job)))

    def _write(self, c: sqlite3.Connection, job: Job) -> None:
        c.execute("""UPDATE report_jobs SET status=?, stock_code=?, mode=?, finished_at=?, payload=?
                     WHERE job_id=?""",
                  (job.status, job.stock_code, job.mode, job.finished_at, self._encode(job), job.job_id))

    @staticmethod
    def _prune(c: sqlite3.Connection) -> None:
        old = c.execute("""SELECT job_id FROM report_jobs WHERE status IN ('complete','warning','error')
                           ORDER BY COALESCE(finished_at, created_at) DESC, rowid DESC
                           LIMIT -1 OFFSET ?""", (RETENTION,)).fetchall()
        if old:
            c.executemany("DELETE FROM report_jobs WHERE job_id=?", [(r["job_id"],) for r in old])

    def _rows(self, sql: str, args: tuple = ()) -> list[Job]:
        try:
            rows = self._conn().execute(sql, args).fetchall()
        except sqlite3.Error as exc:
            raise JobStoreError("The report job database could not be read.") from exc
        return [job for job in (self._decode(r) for r in rows) if job is not None]

    # api -------------------------------------------------------------------------------------
    def create(self, stock_code: str, company_name: str = "", mode: str = "full") -> Job:
        """A new job, or the queued/running job already open for the same symbol and mode."""
        return self.create_or_existing(stock_code, company_name, mode)[0]

    def create_or_existing(self, stock_code: str, company_name: str = "", mode: str = "full") -> tuple[Job, bool]:
        with self._tx() as c:
            row = c.execute("""SELECT * FROM report_jobs WHERE stock_code=? AND mode=?
                               AND status IN ('queued','running') ORDER BY rowid LIMIT 1""",
                            (stock_code, mode)).fetchone()
            existing = self._decode(row) if row is not None else None
            if existing is not None:
                return existing, False
            job = Job(job_id=contract.new_job_id(), stock_code=stock_code,
                      company_name=company_name or "", mode=mode)
            self._insert(c, job)
            self._prune(c)
        return job, True

    def get(self, job_id: str) -> Job | None:
        found = self._rows("SELECT * FROM report_jobs WHERE job_id=?", (job_id,))
        return found[0] if found else None

    def update(self, job_id: str, **fields) -> Job | None:
        for name in fields:
            if name not in _FIELDS or name == "job_id":
                raise AttributeError(f"unknown job field: {name}")
        if "status" in fields and fields["status"] not in contract.STATUSES:
            raise ValueError(f"invalid job status: {fields['status']!r}")
        now = time.time()
        with self._tx() as c:
            row = c.execute("SELECT * FROM report_jobs WHERE job_id=?", (job_id,)).fetchone()
            job = self._decode(row) if row is not None else None
            if job is None:
                return None
            was_terminal = job.status in contract.TERMINAL
            for name, value in fields.items():
                if name == "progress":
                    value = max(int(job.progress or 0), int(value or 0))
                if name == "step":
                    _enter_stage(job, value, now)
                setattr(job, name, value)
            if "step" in fields:
                _push_event(job, "stage", f"{job.step} — {job.message}",
                            {"step": job.step, "progress": job.progress})
            finished_now = not was_terminal and job.status in contract.TERMINAL
            if finished_now:
                _close_stage(job, now)
            self._write(c, job)
            if finished_now:
                self._prune(c)
        if finished_now and job.status in ("complete", "warning"):
            self._record_eta(job)
        return job

    @staticmethod
    def _record_eta(job: Job) -> None:
        try:
            from backend import eta
            eta.record(job)
        except Exception:  # the ETA is advisory; never fail a job over it
            log.exception("could not record ETA history for %s", job.job_id)

    def append_event(self, job_id: str, type: str, message: str, meta: dict | None = None) -> Job | None:
        with self._tx() as c:
            row = c.execute("SELECT * FROM report_jobs WHERE job_id=?", (job_id,)).fetchone()
            job = self._decode(row) if row is not None else None
            if job is None:
                return None
            _push_event(job, type, message, meta)
            self._write(c, job)
        return job

    def claim(self, job_id: str) -> bool:
        """Queued -> running, only while fewer than settings.MAX_RUNNING_JOBS run. Atomic: the
        conditional UPDATE's row count decides, so two claimers never both win."""
        with self._tx() as c:
            row = c.execute("SELECT * FROM report_jobs WHERE job_id=?", (job_id,)).fetchone()
            job = self._decode(row) if row is not None else None
            if job is None or job.status != "queued":
                return False
            running = c.execute("SELECT count(*) FROM report_jobs WHERE status='running'").fetchone()[0]
            if running >= max(1, int(settings.MAX_RUNNING_JOBS)):
                return False
            job.status = "running"
            job.started_at = job.started_at or now_iso()
            job.message = "Starting"
            cur = c.execute("UPDATE report_jobs SET status='running', payload=? WHERE job_id=? AND status='queued'",
                            (self._encode(job), job_id))
            return cur.rowcount == 1

    def queue_position(self, job_id: str) -> dict | None:
        """{"position": 1 = next to start, "running": jobs running now}; None unless queued."""
        try:
            c = self._conn()
            row = c.execute("SELECT rowid AS rid, status FROM report_jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None or row["status"] != "queued":
                return None
            ahead = c.execute("SELECT count(*) FROM report_jobs WHERE status='queued' AND rowid<?",
                              (row["rid"],)).fetchone()[0]
            running = c.execute("SELECT count(*) FROM report_jobs WHERE status='running'").fetchone()[0]
        except sqlite3.Error as exc:
            raise JobStoreError("The report job database could not be read.") from exc
        return {"position": int(ahead) + 1, "running": int(running)}

    def pending(self) -> list[Job]:
        """Queued jobs (never started), oldest first: safe to start again after a restart."""
        return self._rows("SELECT * FROM report_jobs WHERE status='queued' ORDER BY rowid")

    def delete(self, job_id: str) -> bool:
        with self._tx() as c:
            return c.execute("DELETE FROM report_jobs WHERE job_id=?", (job_id,)).rowcount > 0

    def all(self) -> list[Job]:
        return self._rows("SELECT * FROM report_jobs ORDER BY rowid")

    def finished(self) -> list[Job]:
        """Reports that can be opened, newest first."""
        done = [j for j in self._rows("SELECT * FROM report_jobs WHERE status IN ('complete','warning') ORDER BY rowid")
                if j.html_file]
        done.sort(key=lambda j: (j.finished_at or j.created_at or ""), reverse=True)
        return done

    def running_count(self) -> int:
        """Jobs queued or running (as before)."""
        try:
            return int(self._conn().execute(
                "SELECT count(*) FROM report_jobs WHERE status IN ('queued','running')").fetchone()[0])
        except sqlite3.Error as exc:
            raise JobStoreError("The report job database could not be read.") from exc


_shared: Registry | None = None
_shared_lock = threading.Lock()


def registry() -> Registry:
    """The shared registry for the current OUTPUT_DIR (a new one when OUTPUT_DIR changes)."""
    global _shared
    path = settings.jobs_db()
    with _shared_lock:
        if _shared is None or _shared.path != path:
            _shared = Registry(path)
        return _shared
