import json
import threading

import pytest

from backend import contract, jobs, settings


def test_create_get_update_round_trip():
    reg = jobs.registry()
    job = reg.create("AAPL", "Apple Inc.", "full")
    assert contract.JOB_ID_RE.fullmatch(job.job_id)
    assert (job.status, job.step, job.progress, job.message) == ("queued", "Starting", 0, "Queued")
    assert job.sources == [] and job.html_file is None and job.created_at.endswith("Z")
    reg.update(job.job_id, status="running", step="Company Info", progress=8, message="Looking up")
    got = reg.get(job.job_id)
    assert got.status == "running" and got.step == "Company Info" and got.progress == 8
    assert got.stage_history == ["Company Info"]
    got.status = "mutated"
    assert reg.get(job.job_id).status == "running"  # get returns a copy
    assert all(hasattr(got, name) for name in contract.STATUS_FIELDS)


def test_progress_never_decreases():
    reg = jobs.registry()
    job = reg.create("MSFT", "", "full")
    reg.update(job.job_id, progress=50)
    reg.update(job.job_id, progress=20)
    assert reg.get(job.job_id).progress == 50


def test_duplicate_start_returns_the_same_job():
    reg = jobs.registry()
    a = reg.create("BRK.B", "", "full")
    b = reg.create("BRK.B", "", "full")
    c = reg.create("BRK.B", "", "fast")
    assert a.job_id == b.job_id != c.job_id
    reg.update(a.job_id, status="complete")
    assert reg.create("BRK.B", "", "full").job_id != a.job_id


def test_reload_turns_running_job_into_error():
    reg = jobs.registry()
    job = reg.create("AAPL", "", "full")
    reg.update(job.job_id, status="running", step="Data Fetch", progress=15)
    done = reg.create("MSFT", "", "full")
    reg.update(done.job_id, status="complete", html_file="report_MSFT_12345678.html", finished_at="2026-11-22T00:00:00Z")
    path = settings.jobs_db()
    assert path.is_file()
    fresh = jobs.Registry(path)  # a restart: a second registry on the same database
    again = fresh.get(job.job_id)
    assert again.status == "error" and again.error == "Interrupted by a restart"
    assert fresh.get(done.job_id).status == "complete"
    assert [j.job_id for j in fresh.finished()] == [done.job_id]
    assert fresh.running_count() == 0


def test_delete_and_finished_order():
    reg = jobs.registry()
    a = reg.create("AAPL", "", "full")
    b = reg.create("MSFT", "", "full")
    reg.update(a.job_id, status="complete", html_file="report_AAPL_aaaaaaaa.html", finished_at="2026-11-21T00:00:00Z")
    reg.update(b.job_id, status="warning", html_file="report_MSFT_bbbbbbbb.html", finished_at="2026-11-22T00:00:00Z")
    assert [j.job_id for j in reg.finished()] == [b.job_id, a.job_id]
    assert reg.delete(a.job_id) is True
    assert reg.get(a.job_id) is None and reg.delete(a.job_id) is False


def test_registry_follows_output_dir(tmp_path, monkeypatch):
    first = jobs.registry()
    first.create("AAPL", "", "full")
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "other"))
    second = jobs.registry()
    assert second is not first and second.running_count() == 0


# SQLite registry (ported from the original's report_jobs.py) ----------------------------------
def test_two_threads_starting_the_same_symbol_share_one_job():
    reg = jobs.registry()
    barrier = threading.Barrier(2)
    results = []

    def start():
        barrier.wait(timeout=5)
        results.append(reg.create_or_existing("AAPL", "", "full"))

    threads = [threading.Thread(target=start) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert not any(t.is_alive() for t in threads) and len(results) == 2
    assert results[0][0].job_id == results[1][0].job_id
    assert sorted(created for _, created in results) == [False, True]
    assert len(reg.all()) == 1


def test_claim_succeeds_once():
    reg = jobs.registry()
    job = reg.create("AAPL", "", "full")
    assert reg.claim(job.job_id) is True
    assert reg.claim(job.job_id) is False
    got = reg.get(job.job_id)
    assert got.status == "running" and got.started_at
    assert reg.claim("0" * 32) is False


def test_fourth_job_waits_while_three_run():
    reg = jobs.registry()
    assert settings.MAX_RUNNING_JOBS == 3
    made = [reg.create(code, "", "full") for code in ("AAPL", "MSFT", "NVDA", "META", "AMZN")]
    assert [reg.claim(j.job_id) for j in made[:3]] == [True, True, True]
    assert reg.claim(made[3].job_id) is False
    assert reg.get(made[3].job_id).status == "queued"
    assert reg.queue_position(made[3].job_id) == {"position": 1, "running": 3}
    assert reg.queue_position(made[4].job_id) == {"position": 2, "running": 3}
    assert reg.queue_position(made[0].job_id) is None
    reg.update(made[0].job_id, status="complete", finished_at=jobs.now_iso())
    assert reg.claim(made[3].job_id) is True


def test_restart_interrupts_running_and_keeps_queued_pending():
    reg = jobs.registry()
    running = reg.create("AAPL", "", "full")
    reg.update(running.job_id, status="running", step="Data Fetch", progress=15, message="Fetching")
    queued = reg.create("MSFT", "", "full")
    fresh = jobs.Registry(settings.jobs_db())
    got = fresh.get(running.job_id)
    assert (got.status, got.error, got.message) == ("error", "Interrupted by a restart", "Interrupted by a restart")
    assert got.finished_at and got.step == "Data Fetch" and got.progress == 15
    assert got.events[-1]["type"] == "error" and got.events[-1]["message"] == "Interrupted by a restart"
    assert [j.job_id for j in fresh.pending()] == [queued.job_id]
    assert fresh.get(queued.job_id).status == "queued"
    # a new start for the interrupted symbol is admitted again
    assert fresh.create_or_existing("AAPL", "", "full")[1] is True


def test_events_are_capped_and_step_changes_add_stage_events():
    reg = jobs.registry()
    job = reg.create("AAPL", "", "full")
    reg.update(job.job_id, step="Company Info", message="Looking up", status="running")
    got = reg.get(job.job_id)
    assert got.events[-1]["type"] == "stage" and got.events[-1]["message"] == "Company Info — Looking up"
    assert set(got.events[-1]) == {"ts", "type", "message", "meta"}
    reg.update(job.job_id, progress=10)  # no step: no event
    assert len(reg.get(job.job_id).events) == 1
    for i in range(250):
        reg.append_event(job.job_id, "log", f"e{i}", {"i": i})
    got = reg.get(job.job_id)
    assert len(got.events) == jobs.EVENT_LIMIT == 200
    assert got.event_offset == 51 and got.events[0]["message"] == "e50" and got.events[-1]["meta"] == {"i": 249}
    assert reg.append_event("0" * 32, "log", "x") is None


def test_stage_timings_record_duration_of_previous_stage():
    reg = jobs.registry()
    job = reg.create("AAPL", "", "full")
    reg.update(job.job_id, step="Starting", status="running")
    reg.update(job.job_id, step="Company Info")
    got = reg.get(job.job_id)
    assert got.stage_history == ["Starting", "Company Info"]
    first, second = got.stage_timings
    assert first["stage"] == "Starting" and first["ended_at"] and first["duration"] >= 0
    assert second["stage"] == "Company Info" and second["ended_at"] is None
    assert got.stage_started_at == second["started_at"]
    reg.update(job.job_id, status="error", error="x", finished_at=jobs.now_iso())
    assert reg.get(job.job_id).stage_timings[-1]["duration"] is not None


def test_retention_keeps_the_newest_sixty_finished():
    reg = jobs.registry()
    made = []
    for i in range(65):
        job = reg.create("AAPL", "", "full")
        reg.update(job.job_id, status="complete", html_file=f"report_AAPL_{i:08x}.html",
                   finished_at=f"2026-11-22T00:{i // 60:02d}:{i % 60:02d}Z")
        made.append(job.job_id)
    left = {j.job_id for j in reg.all()}
    assert len(left) == jobs.RETENTION == 60
    assert left == set(made[5:])
    active = reg.create("MSFT", "", "full")  # an active job is never pruned
    assert reg.get(active.job_id) is not None and len(reg.all()) == 61


def test_progress_never_decreases_across_stages():
    reg = jobs.registry()
    job = reg.create("AAPL", "", "full")
    seen = []
    for step, progress in (("Starting", 2), ("Company Info", 8), ("Data Fetch", 15)):
        reg.update(job.job_id, step=step, progress=progress)
        reg.update(job.job_id, progress=1)
        seen.append(reg.get(job.job_id).progress)
    assert seen == [2, 8, 15]


def test_unknown_field_and_bad_status_are_refused():
    reg = jobs.registry()
    job = reg.create("AAPL", "", "full")
    with pytest.raises(AttributeError):
        reg.update(job.job_id, nope=1)
    with pytest.raises(ValueError):
        reg.update(job.job_id, status="mutated")
    assert reg.get(job.job_id).status == "queued"


def test_legacy_jobs_json_is_imported_once_and_left_alone():
    legacy = settings.output_dir() / "jobs.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    done_id, running_id = "a" * 32, "b" * 32
    legacy.write_text(json.dumps({"jobs": [
        {"job_id": done_id, "stock_code": "AAPL", "status": "complete", "step": "Complete", "progress": 100,
         "html_file": "report_AAPL_aaaaaaaa.html", "finished_at": "2026-11-20T00:00:00Z",
         "stage_history": ["Starting", "Complete"], "unknown_old_field": 1},
        {"job_id": running_id, "stock_code": "MSFT", "status": "running"},
        {"job_id": "not-a-job", "stock_code": "X", "status": "complete"},
    ]}), encoding="utf-8")
    before = legacy.read_text(encoding="utf-8")
    reg = jobs.registry()
    assert [j.job_id for j in reg.finished()] == [done_id]
    assert reg.get(running_id) is None
    reg.delete(done_id)
    again = jobs.Registry(settings.jobs_db())
    assert again.get(done_id) is None  # imported once: a deleted job does not come back
    assert legacy.read_text(encoding="utf-8") == before
