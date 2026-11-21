"""The contract the interface already speaks. Pinned from the interface's own code
(LECTIO/kabu/src: api/backend.js, lib/safeUrl.js, lib/reportStorage.js, pages/GenerateReport.jsx,
components/report/SourcesModal.jsx). Change a value here only together with the interface."""
import re
import uuid

# job.step: the interface's stepper looks these strings up; any other string freezes it.
# ("Peers" is shown to the user as "Compare Peers".)
STAGES = ("Starting", "Company Info", "Data Fetch", "Extraction", "Analysis", "Valuation",
          "Peers", "Drafting", "Rendering", "Complete")

# job.status
STATUSES = ("queued", "running", "complete", "warning", "error")
TERMINAL = ("complete", "warning", "error")

# GET /status/{job_id}: every field the interface reads.
STATUS_FIELDS = (
    "job_id", "stock_code", "company_name", "status", "step", "message", "error", "progress",
    "eta_seconds", "created_at", "started_at", "finished_at", "html_file", "pdf_file",
    "sources", "source_count", "edinet_count", "edinet_scanned", "edinet_total",
    "financial_rows", "price_rows", "financials_source",
)

# Sent only while a job is queued or running (see main._status_dict): the progress inside a step
# and the place in the queue. The interface reads them when they are there.
STATUS_FIELDS_WHILE_OPEN = ("interpolated_progress", "completed", "queue_position")

# sources[] items, as the Sources panel reads them. type "edinet" = a filing (SEC here); else "web".
SOURCE_FIELDS = ("id", "type", "url", "title", "date", "snippet")
SOURCE_TYPES = ("edinet", "web")

# GET /api/reports/mine -> {"reports": [row, ...]}
REPORT_ROW_FIELDS = ("job_id", "ticker", "company_name", "html_file", "pdf_file",
                     "finished_at", "created_at", "status", "source_count")

# POST /api/report-chat answers as an event stream; "done" is always last.
CHAT_EVENTS = ("text", "error", "done")

JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
REPORT_FILE_RE = re.compile(r"^report_[0-9A-Za-z.]{1,12}_[0-9a-f]{8}\.(html|pdf)$")
TICKER_RE = re.compile(r"^[A-Za-z]{1,5}([.-][A-Za-z])?$")

MODES = ("full", "fast")


def new_job_id() -> str:
    return uuid.uuid4().hex


def report_file_name(ticker: str, token: str, ext: str = "html") -> str:
    """`report_{TICKER in dot form}_{8 hex}.{ext}`; raises ValueError for anything the interface would drop."""
    name = f"report_{ticker.upper().replace('-', '.')}_{token.lower()}.{ext}"
    if not REPORT_FILE_RE.fullmatch(name):
        raise ValueError(f"not a valid report file name: {name!r}")
    return name
