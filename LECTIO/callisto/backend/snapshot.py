"""Key figures for the stock an answer is about, as ready-to-show tiles. Every value is a fact from the market
pack (Massive, built by code in backend/specialists.py), shown in the pack's own display form: no model writes
or changes them. Never raises: a missing pack means no tiles."""
from __future__ import annotations

from backend import specialists

_TILES = [("px_close_last", "Price", "close"), ("ret_1d_pct", "Day change", "against the close before"),
          ("ret_1y_pct", "Past year", "price return"), ("market_cap", "Market cap", None),
          ("gap_52w_high_pct", "Below 52-week high", None), ("div_yield_pct", "Dividend yield", "at the latest rate")]


def stats(ticker: str) -> list:
    try:
        pack = specialists.market({"ticker": ticker, "question": ""})
        if not isinstance(pack, dict) or pack.get("status") != "ok":
            return []
        facts, as_of = pack.get("facts") or {}, pack.get("as_of")
        out = []
        for fid, label, note in _TILES:
            f = facts.get(fid)
            if not f or not f.get("display"):
                continue
            n = f"{note}, {as_of}" if fid == "px_close_last" and as_of else note
            out.append({"label": label, "value": str(f["display"]), "note": n or "", "fact_id": fid})
        lo, hi = facts.get("px_52w_low"), facts.get("px_52w_high")
        if lo and hi and lo.get("display") and hi.get("display"):
            out.insert(4, {"label": "52-week range", "value": f"{lo['display']} to {hi['display']}", "note": "",
                           "fact_id": "px_52w_low,px_52w_high"})
        return out[:6]
    except Exception:
        return []
