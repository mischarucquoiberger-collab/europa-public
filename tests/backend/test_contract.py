"""The contract is what the interface's own code expects; these tests read that code."""
import re
import socket
from pathlib import Path

import pytest

from backend import contract, settings

SRC = Path(__file__).resolve().parents[2] / "LECTIO" / "kabu" / "src"


def test_stages_are_the_interfaces_step_keys():
    assert contract.STAGES == ("Starting", "Company Info", "Data Fetch", "Extraction", "Analysis",
                               "Valuation", "Peers", "Drafting", "Rendering", "Complete")
    assert "Compare Peers" not in contract.STAGES          # that is only the label of "Peers"
    page = (SRC / "pages" / "GenerateReport.jsx").read_text()
    keys = re.findall(r'\{\s*key:\s*"([^"]+)"', page)
    for stage in contract.STAGES:
        assert stage in keys, stage


def test_every_status_field_the_interface_reads_is_pinned():
    page = (SRC / "pages" / "GenerateReport.jsx").read_text()
    read = set(re.findall(r"status\??\.([a-z_]+)", page))
    known = set(contract.STATUS_FIELDS) | set(contract.STATUS_FIELDS_WHILE_OPEN)
    assert read <= known, read - known
    assert contract.STATUSES == ("queued", "running", "complete", "warning", "error")


def test_job_id_and_report_file_patterns_match_the_interface():
    assert "/^[0-9a-f]{32}$/" in (SRC / "lib" / "reportStorage.js").read_text()
    assert contract.JOB_ID_RE.fullmatch(contract.new_job_id())
    # the interface writes the group as non-capturing; the accepted names are the same
    assert r"/^report_[0-9A-Za-z.]+_[0-9a-f]{8}\.(?:html|pdf)$/" in (SRC / "lib" / "safeUrl.js").read_text()
    assert contract.report_file_name("BRK.B", "1a2b3c4d") == "report_BRK.B_1a2b3c4d.html"
    assert contract.report_file_name("brk-b", "1A2B3C4D", "pdf") == "report_BRK.B_1a2b3c4d.pdf"
    for bad in (("AAPL", "xyz"), ("AA PL", "1a2b3c4d"), ("../x", "1a2b3c4d"), ("AAPL", "1a2b3c4")):
        with pytest.raises(ValueError):
            contract.report_file_name(*bad)


def test_ticker_pattern_accepts_class_shares_in_both_forms():
    for good in ("AAPL", "v", "BRK.B", "brk-b", "GOOGL"):
        assert contract.TICKER_RE.fullmatch(good), good
    for bad in ("", "TOOLONG", "7203", "AA PL", "BRK.BB", "A.B.C"):
        assert not contract.TICKER_RE.fullmatch(bad), bad


def test_source_and_report_row_shapes():
    assert contract.SOURCE_FIELDS == ("id", "type", "url", "title", "date", "snippet")
    assert contract.SOURCE_TYPES == ("edinet", "web")
    assert "ticker" in contract.REPORT_ROW_FIELDS and "stock_code" not in contract.REPORT_ROW_FIELDS
    assert contract.CHAT_EVENTS[-1] == "done"


def test_settings_defaults_and_test_isolation(tmp_path):
    assert settings.backend_host() == "127.0.0.1"
    assert settings.backend_port() == 8130
    assert settings.source_mode() == "replay"                       # set by tests/conftest.py
    assert str(settings.output_dir()).startswith(str(tmp_path))     # never the real output folder
    assert settings.secret("NICRRON_API_KEY").startswith("nk-FAKE")  # never the real key
    with pytest.raises(OSError, match="tests are offline"):
        socket.create_connection(("93.184.216.34", 80), timeout=1)
