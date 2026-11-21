import time

from backend import contract, eta, jobs, pipeline, settings


def _running(step="Data Fetch", stage_age=0.0, run_age=0.0, **kw):
    now = time.time()
    return jobs.Job(job_id=contract.new_job_id(), stock_code="AAPL", status="running", step=step,
                    progress=pipeline.PROGRESS[step],
                    started_at=jobs._iso_ms(now - run_age), stage_started_at=jobs._iso_ms(now - stage_age), **kw)


def _finished(drafting_seconds: float) -> jobs.Job:
    job = jobs.Job(job_id=contract.new_job_id(), stock_code="AAPL", status="complete", step="Complete",
                   progress=100, started_at="2026-11-22T00:00:00Z", finished_at="2026-11-22T00:00:40Z")
    job.stage_timings = [
        {"stage": "Data Fetch", "started_at": "x", "ended_at": "y", "duration": 6.0},
        {"stage": "Drafting", "started_at": "x", "ended_at": "y", "duration": drafting_seconds},
        {"stage": "Complete", "started_at": "x", "ended_at": "y", "duration": 0.0},
    ]
    return job


def test_stage_tables_follow_the_contract_and_the_pipeline():
    assert tuple(eta.STAGE_ORDER) == contract.STAGES
    assert eta.STAGE_BASE == pipeline.PROGRESS


def test_defaults_give_a_positive_estimate_and_zero_at_complete():
    job = _running("Data Fetch")
    left = eta.predict_eta(job)
    future = sum(eta.STAGE_DEFAULTS[s] for s in contract.STAGES[contract.STAGES.index("Data Fetch"):])
    assert left > 0 and abs(left - future) <= 2
    later = eta.predict_eta(_running("Drafting"))
    assert 0 < later < left
    assert eta.predict_eta(_running("Complete")) == 0
    done = jobs.Job(job_id=contract.new_job_id(), stock_code="AAPL", status="complete", step="Complete")
    assert eta.predict_eta(done) == 0
    queued = jobs.Job(job_id=contract.new_job_id(), stock_code="AAPL")
    assert eta.predict_eta(queued) is None


def test_overrun_stage_still_reports_time_left():
    job = _running("Drafting", stage_age=200, run_age=230)
    assert eta.predict_eta(job) >= 3


def test_learning_moves_the_expectation_toward_what_was_observed():
    default = eta._get_stage_expected("Drafting", "full")
    assert default == eta.STAGE_DEFAULTS["Drafting"]
    assert eta.record(_finished(5.0)) is True
    first = eta._get_stage_expected("Drafting", "full")
    assert eta.record(_finished(5.0)) is True
    second = eta._get_stage_expected("Drafting", "full")
    assert default > first > second > 5.0
    assert (settings.output_dir() / eta.HISTORY_FILE).is_file()
    assert eta._get_stage_expected("Drafting", "fast") == default  # kept per mode
    failed = _finished(1.0)
    failed.status = "error"
    assert eta.record(failed) is False  # only complete/warning runs teach the ETA


def test_record_is_once_per_job():
    job = _finished(5.0)
    assert eta.record(job) is True
    learned = eta._get_stage_expected("Drafting", "full")
    assert eta.record(job) is False
    assert eta._get_stage_expected("Drafting", "full") == learned


def test_a_corrupt_history_file_is_ignored():
    path = settings.output_dir() / eta.HISTORY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert eta._get_stage_expected("Drafting", "full") == eta.STAGE_DEFAULTS["Drafting"]
    assert eta.predict_eta(_running("Data Fetch")) > 0
    path.write_text('{"stages": {"Drafting::full": {"ema": "fast"}, "Peers::full": {"ema": -1}}}', encoding="utf-8")
    assert eta._get_stage_expected("Drafting", "full") == eta.STAGE_DEFAULTS["Drafting"]
    assert eta._get_stage_expected("Peers", "full") == eta.STAGE_DEFAULTS["Peers"]
    assert eta.record(_finished(5.0)) is True  # replaces the bad file
    assert eta._get_stage_expected("Drafting", "full") < eta.STAGE_DEFAULTS["Drafting"]


def test_interpolate_progress_is_monotonic_and_bounded():
    for step in contract.STAGES[:-1]:
        job = _running(step)
        t0 = jobs.parse_ts(job.stage_started_at)
        values = [eta.interpolate_progress(job, now=t0 + k * 0.25) for k in range(0, 400)]
        nxt = pipeline.PROGRESS[contract.STAGES[contract.STAGES.index(step) + 1]]
        assert values == sorted(values), step
        assert values[0] >= pipeline.PROGRESS[step] and values[-1] < nxt, step
        assert values[-1] > values[0], step
    assert eta.interpolate_progress(_running("Complete")) == 100
    queued = jobs.Job(job_id=contract.new_job_id(), stock_code="AAPL")
    assert eta.interpolate_progress(queued) == 0
    ahead = _running("Drafting")
    ahead.progress = 99  # the job's own progress always wins
    assert eta.interpolate_progress(ahead) == 99


def test_completed_stages_and_registry_records_on_finish():
    reg = jobs.registry()
    job = reg.create("AAPL", "", "full")
    for step in ("Starting", "Company Info", "Data Fetch"):
        reg.update(job.job_id, step=step, status="running", started_at=jobs.now_iso())
    done = eta.completed_stages(reg.get(job.job_id))
    assert list(done) == ["Starting", "Company Info"] and all(v >= 0 for v in done.values())
    reg.update(job.job_id, step="Complete", status="complete", finished_at=jobs.now_iso())
    assert (settings.output_dir() / eta.HISTORY_FILE).is_file()
