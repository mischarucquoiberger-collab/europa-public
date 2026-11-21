"""Report ETA, ported from the original product's app/services/eta.py (per-stage durations).

ETA = time left in the current stage + the expected duration of every later stage, blended
with an elapsed-time projection once a run is under way, then smoothed for display.
Each stage's expected duration starts at STAGE_DEFAULTS and learns from finished jobs'
stage_timings: an exponential moving average per stage and mode, kept in
OUTPUT_DIR/eta_history.json (a missing or unreadable file means the defaults).
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path

from backend import contract, settings
from backend.jobs import parse_ts

log = logging.getLogger(__name__)

STAGE_ORDER = list(contract.STAGES)

# progress at the start of each stage (= pipeline.PROGRESS; a test keeps the two equal)
STAGE_BASE = {"Starting": 2, "Company Info": 8, "Data Fetch": 15, "Extraction": 35, "Analysis": 50,
              "Valuation": 62, "Peers": 70, "Drafting": 80, "Rendering": 92, "Complete": 100}

# seconds per stage for this pipeline before any history exists
STAGE_DEFAULTS = {"Starting": 1, "Company Info": 2, "Data Fetch": 6, "Extraction": 2, "Analysis": 1,
                  "Valuation": 2, "Peers": 3, "Drafting": 25, "Rendering": 2, "Complete": 0}
assert tuple(STAGE_BASE) == tuple(STAGE_DEFAULTS) == contract.STAGES

EMA_ALPHA = 0.3          # weight of the newest observation
MAX_ETA = 600.0
MIN_ETA = 2.0
HISTORY_FILE = "eta_history.json"
_MAX_STATE = 512         # per-job display dampers kept in memory
_MAX_RECORDED = 2048     # job ids already learned from (record is once per job)

LOCK = threading.RLock()
_JOB_ETA_STATE: "OrderedDict[str, dict]" = OrderedDict()
_RECORDED: "OrderedDict[str, None]" = OrderedDict()
_CACHE: dict = {"key": None, "data": None}


# history -------------------------------------------------------------------------------------
def _history_path() -> Path:
    return settings.output_dir() / HISTORY_FILE


def _empty() -> dict:
    return {"version": 1, "stages": {}, "totals": {}}


def _clean_entries(raw) -> dict:
    out = {}
    if not isinstance(raw, dict):
        return out
    for key, entry in raw.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            continue
        ema, n = entry.get("ema"), entry.get("n")
        if isinstance(ema, bool) or not isinstance(ema, (int, float)) or not math.isfinite(ema) or ema < 0:
            continue
        out[key] = {"ema": float(ema), "n": int(n) if isinstance(n, int) and not isinstance(n, bool) and n > 0 else 1}
    return out


def _load_history() -> dict:
    """The learned history for the current OUTPUT_DIR (re-read when the file changes)."""
    path = _history_path()
    try:
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size)
    except OSError:
        key = (str(path), None, None)
    with LOCK:
        if _CACHE["key"] == key and _CACHE["data"] is not None:
            return _CACHE["data"]
        data = _empty()
        if key[1] is not None:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    data["stages"] = _clean_entries(raw.get("stages"))
                    data["totals"] = _clean_entries(raw.get("totals"))
            except (OSError, ValueError) as exc:
                log.warning("ignoring unreadable ETA history %s: %s", path, exc)
        _CACHE.update(key=key, data=data)
        return data


def _save_history(data: dict) -> None:
    path = _history_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        log.warning("could not save ETA history %s: %s", path, exc)
    _CACHE.update(key=None, data=None)  # re-read (and re-stat) on next use


def _ema(entries: dict, key: str, observed: float, start: float) -> None:
    entry = entries.get(key)
    if entry is None:
        entries[key] = {"ema": round(start + EMA_ALPHA * (observed - start), 3), "n": 1}
    else:
        entry["ema"] = round(entry["ema"] + EMA_ALPHA * (observed - entry["ema"]), 3)
        entry["n"] = int(entry.get("n", 1)) + 1


def _mode(job) -> str:
    mode = getattr(job, "mode", "full") or "full"
    return mode if mode in contract.MODES else "full"


def _get_stage_expected(stage: str, mode: str = "full") -> float:
    """Expected seconds for a stage: the learned average, else the default."""
    entry = _load_history()["stages"].get(f"{stage}::{mode}")
    if entry is not None:
        return float(entry["ema"])
    return float(STAGE_DEFAULTS.get(stage, 2))


def _get_expected_total(mode: str = "full") -> float:
    entry = _load_history()["totals"].get(mode)
    if entry is not None and entry["ema"] > 0:
        return float(entry["ema"])
    return float(sum(_get_stage_expected(s, mode) for s in STAGE_ORDER if s != "Complete"))


# estimator (the original's StageETA, stateless: stage start times come from the job) ---------
def _raw_eta(job, now: float) -> float:
    step = job.step
    mode = _mode(job)
    idx = STAGE_ORDER.index(step)
    stage_start = parse_ts(getattr(job, "stage_started_at", None)) or parse_ts(job.started_at) or now
    stage_elapsed = max(0.0, now - stage_start)
    stage_expected = _get_stage_expected(step, mode)
    if stage_elapsed < stage_expected:
        current_remaining = stage_expected - stage_elapsed
    else:
        # overshooting: the longer it runs over, the less sure the end; a slowly shrinking buffer
        overshoot = stage_elapsed - stage_expected
        decay = 1.0 / (1.0 + math.log1p(overshoot / max(stage_expected, 1.0)))
        current_remaining = max(3.0, stage_expected * decay)
    future = sum(_get_stage_expected(s, mode) for s in STAGE_ORDER[idx + 1:] if s != "Complete")
    raw = current_remaining + future
    started = parse_ts(job.started_at)
    if started is not None:
        total_elapsed = now - started
        total_expected = _get_expected_total(mode)
        if total_elapsed > 5 and total_expected > 0 and total_elapsed / total_expected > 0.1:
            projection = total_expected - total_elapsed
            if projection > 0:
                raw = 0.7 * raw + 0.3 * projection
    return max(MIN_ETA, min(raw, MAX_ETA))


class DisplayDamper:
    """The original's display smoothing: ticks down about 1 s per second, drops fast when ahead
    of schedule, corrects upward proportionally, trusts a new stage's estimate more."""

    def __init__(self):
        self.displayed_eta: float | None = None
        self.last_ts: float | None = None

    def smooth(self, raw_eta: float, now: float, stage_changed: bool) -> int:
        if self.displayed_eta is None or self.last_ts is None:
            self.displayed_eta, self.last_ts = raw_eta, now
            return round(raw_eta)
        elapsed = max(0.0, now - self.last_ts)
        self.last_ts = now
        expected = max(self.displayed_eta - elapsed, 0.0)
        if stage_changed:
            result = 0.3 * expected + 0.7 * raw_eta
        elif raw_eta <= expected:
            result = 0.4 * expected + 0.6 * raw_eta
        else:
            delta = raw_eta - expected
            result = expected + min(delta * 0.3, max(expected * 0.3, 5.0))
        if raw_eta > 3.0:
            result = max(result, 3.0)
        result = max(1.0, min(result, MAX_ETA))
        self.displayed_eta = result
        return round(result)


# public api ----------------------------------------------------------------------------------
def predict_eta(job, now: float | None = None) -> int | None:
    """Seconds left for a running job (smoothed per job); 0 once it is finished; None when
    there is nothing to estimate (queued, or a step outside contract.STAGES)."""
    status = str(getattr(job, "status", "") or "").lower()
    step = getattr(job, "step", None)
    job_id = getattr(job, "job_id", None)
    if status in contract.TERMINAL or step == "Complete":
        if job_id:
            cleanup_job(job_id)
        return 0
    if status != "running" or step not in STAGE_ORDER:
        return None
    now = time.time() if now is None else now
    try:
        raw = _raw_eta(job, now)
    except Exception:  # an odd timestamp must never break /status
        log.exception("ETA estimate failed for %s", job_id)
        return None
    if not job_id:
        return round(raw)
    with LOCK:
        state = _JOB_ETA_STATE.get(job_id)
        if state is None:
            state = {"damper": DisplayDamper(), "step": step}
            _JOB_ETA_STATE[job_id] = state
            while len(_JOB_ETA_STATE) > _MAX_STATE:
                _JOB_ETA_STATE.popitem(last=False)
        stage_changed = step != state["step"]
        state["step"] = step
        return int(state["damper"].smooth(raw, now, stage_changed))


def interpolate_progress(job, now: float | None = None) -> int:
    """Progress moving smoothly inside the current stage: from the stage's base value toward
    (never reaching) the next stage's, eased, never below the job's own progress."""
    base = int(getattr(job, "progress", 0) or 0)
    step = getattr(job, "step", None)
    if str(getattr(job, "status", "")) != "running" or step not in STAGE_ORDER or step == "Complete":
        return base
    try:
        idx = STAGE_ORDER.index(step)
        start_pct = STAGE_BASE[step]
        end_pct = STAGE_BASE[STAGE_ORDER[idx + 1]] - 1
        stage_start = parse_ts(getattr(job, "stage_started_at", None))
        if stage_start is None:
            return max(base, start_pct)
        now = time.time() if now is None else now
        expected = max(_get_stage_expected(step, _mode(job)), 1.0)
        elapsed = max(0.0, now - stage_start)
        if elapsed >= expected:
            overshoot = elapsed / expected
            frac = min(0.90 + 0.05 * (1 - 1.0 / max(overshoot, 1.0)), 0.95)
        else:
            frac = max(0.02, min(elapsed / expected, 0.90))
        eased = 1 - (1 - frac) ** 2.5
        interpolated = int(start_pct + eased * (end_pct - start_pct))
        return max(base, min(interpolated, end_pct))
    except Exception:
        return base


def _stage_seconds(job) -> dict:
    out: dict = {}
    for entry in getattr(job, "stage_timings", None) or []:
        if not isinstance(entry, dict) or not isinstance(entry.get("stage"), str) or entry["stage"] == "Complete":
            continue
        duration = entry.get("duration")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool) and math.isfinite(duration):
            out[entry["stage"]] = out.get(entry["stage"], 0.0) + max(0.0, float(duration))
    return out


def completed_stages(job) -> dict:
    """{stage: seconds} for every stage the job has finished, in order."""
    return {stage: round(seconds, 1) for stage, seconds in _stage_seconds(job).items()}


def cleanup_job(job_id: str) -> None:
    """Drop a job's display state."""
    with LOCK:
        _JOB_ETA_STATE.pop(job_id, None)


def record(job) -> bool:
    """Learn from a finished job (complete or warning), once per job. True when recorded."""
    job_id = getattr(job, "job_id", None)
    if job_id:
        cleanup_job(job_id)
    if getattr(job, "status", None) not in ("complete", "warning"):
        return False
    mode = _mode(job)
    with LOCK:
        if job_id:
            if job_id in _RECORDED:
                return False
            _RECORDED[job_id] = None
            while len(_RECORDED) > _MAX_RECORDED:
                _RECORDED.popitem(last=False)
        data = _load_history()
        data = {"version": 1, "stages": {k: dict(v) for k, v in data["stages"].items()},
                "totals": {k: dict(v) for k, v in data["totals"].items()}}
        learned = False
        for stage, seconds in _stage_seconds(job).items():
            if stage not in STAGE_DEFAULTS:
                continue
            _ema(data["stages"], f"{stage}::{mode}", seconds, _get_stage_expected(stage, mode))
            learned = True
        started, finished = parse_ts(getattr(job, "started_at", None)), parse_ts(getattr(job, "finished_at", None))
        if started is not None and finished is not None and finished - started > 0:
            _ema(data["totals"], mode, finished - started, _get_expected_total(mode))
            learned = True
        if learned:
            _save_history(data)
        return learned


record_job = record  # the original's name
