"""Backend settings. Keys are read through the root config (which owns .env); nothing secret here.
Paths are functions so tests can point OUTPUT_DIR at a temporary folder."""
import os
from pathlib import Path

import config  # the root loader; do not read .env any other way

REPO = Path(__file__).resolve().parent.parent


def output_dir() -> Path:
    """Reports, the HTTP cache and the jobs database. Git-ignored."""
    return Path(os.environ.get("OUTPUT_DIR") or REPO / "output").resolve()


def reports_dir() -> Path:
    return output_dir() / "reports"


def cache_dir() -> Path:
    return output_dir() / "cache"


def jobs_db() -> Path:
    return output_dir() / "report_jobs.sqlite3"


def replay_dir() -> Path:
    """Recorded public responses (committed) for tests and for a demo without network."""
    return Path(os.environ.get("REPLAY_DIR") or REPO / "tests" / "backend" / "fixtures" / "replay").resolve()


def source_mode() -> str:
    """live: the network. record: the network, and save what came back. replay: saved responses only."""
    mode = (os.environ.get("SOURCE_MODE") or "live").strip().lower()
    return mode if mode in ("live", "record", "replay") else "live"


def backend_host() -> str:
    # never the shell's HOST (this machine's shell exports an unrelated value there)
    return os.environ.get("BACKEND_HOST", "127.0.0.1")


def backend_port() -> int:
    return int(os.environ.get("BACKEND_PORT", "8130"))


MAX_RUNNING_JOBS = 3      # reports generated at the same time
MODEL_CONCURRENCY = 6     # model calls at the same time, across all jobs (backend.model's gate)
FETCH_WORKERS = 6         # source fetches at the same time within one job (Data Fetch)
# How long a report waits for each branch that runs alongside the others, in seconds, counted
# from the moment the branches start ("review" from the moment the drafting finished; "valuation"
# is the wait for the market proxy's bars, counted from the start of Data Fetch, since the
# arithmetic itself runs on the job's thread). A late branch is left out of the report with a
# plain note; the report still completes.
BRANCH_TIMEOUTS = {"valuation": 60, "peers": 50, "risk": 90, "drafting": 180, "review": 120,
                   "thesis": 90, "news": 60, "release": 90, "advisor": 60}


def secret(name: str) -> str:
    return config.secret(name)
