"""The report-file guard for GET /download, and the Content-Security-Policy a report is served with."""
from pathlib import Path

from backend import contract, settings

# No scripts, no outside requests of any kind, and only this app may frame a report.
REPORT_CSP = ("default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; "
              "base-uri 'none'; form-action 'none'; frame-ancestors 'self'")


class ReportMissing(ValueError):
    """The name is valid but no such report exists (GET /download answers 404)."""


def resolve(file: str) -> Path:
    """The report file for a bare name; ValueError for anything else (bad name, outside the
    reports folder, missing, or a symlink)."""
    name = (file or "").strip()
    if not contract.REPORT_FILE_RE.fullmatch(name):
        raise ValueError("invalid report file name")
    try:
        root = settings.reports_dir().resolve()
        candidate = root / name
        if candidate.is_symlink():
            raise ValueError("report file is a symlink")
        resolved = candidate.resolve()
        if resolved.parent != root:
            raise ValueError("report file is outside the reports folder")
        missing = not resolved.is_file()
    except OSError as exc:          # a name the file system refuses is a bad name, not a server fault
        raise ValueError("invalid report file name") from exc
    if missing:
        raise ReportMissing(name)
    return resolved
