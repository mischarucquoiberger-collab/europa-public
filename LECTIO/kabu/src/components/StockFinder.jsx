import { createPortal } from "react-dom";
import { useEffect, useRef, useState } from "react";
import { Search } from "lucide-react";
import companies from "@/data/companies.json";

/* The stock finder: the magnifier in the top navigation. It opens a stock's page of the markets
   desk in a new tab (#/Home?page=/stocks/…), which index.html opens without the splash. */

const SLOT = ".underlay-nav__container";
const RESULTS_ID = "stock-finder-results";
const MAX_RESULTS = 6;
/** A text that looks like a ticker of its own (AAPL, BRK.B, BF-B, I:SPX); anything else opens nothing. */
export const TICKER_SHAPE = /^(?:I:)?[A-Z]{1,5}(?:[.-][A-Z]{1,2})?$/;

/** The desk page of a ticker, as a deep link into Home. */
export const stockHref = (ticker) => "#/Home?page=" + encodeURIComponent("/stocks/" + ticker);

/** The companies a query matches, best first: the exact ticker, tickers that start with it, names
 *  with a word that starts with it, then names that contain it. A ticker-shaped text with no
 *  company of its own is offered as itself. */
export function findStocks(query) {
  const text = String(query || "").trim().toUpperCase();
  if (!text) return [];
  const rank = (c) => {
    const name = c.name.toUpperCase();
    if (c.ticker === text) return 0;
    if (c.ticker.startsWith(text)) return 1;
    if (name.startsWith(text) || name.includes(" " + text)) return 2;
    if (name.includes(text)) return 3;
    return -1;
  };
  const found = companies
    .map((c, i) => ({ c, r: rank(c), i }))
    .filter((x) => x.r >= 0)
    .sort((a, b) => a.r - b.r || a.i - b.i)
    .slice(0, MAX_RESULTS)
    .map((x) => ({ ticker: x.c.ticker, name: x.c.name }));
  if (found.length) return found;
  return TICKER_SHAPE.test(text) ? [{ ticker: text, name: `Open the ${text} chart` }] : [];
}

/** The header's container. The nav may render after this component, or render its header again:
 *  watch the document until the container is there, and again whenever it is replaced. */
function useNavSlot() {
  const [slot, setSlot] = useState(null);
  useEffect(() => {
    let current = null;
    const find = () => {
      if (current?.isConnected) return;
      current = document.querySelector(SLOT);
      setSlot(current);
    };
    find();
    const watch = new MutationObserver(find);
    watch.observe(document.body, { childList: true, subtree: true });
    return () => watch.disconnect();
  }, []);
  return slot;
}

export default function StockFinder() {
  const slot = useNavSlot();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const trigger = useRef(null);
  const options = findStocks(query);
  const text = query.trim();

  function close({ refocus = false } = {}) {
    setOpen(false);
    setQuery("");
    setActive(-1);
    if (refocus) trigger.current?.focus();
  }
  function openStock(ticker) {
    window.open(stockHref(ticker), "_blank", "noopener");
    close({ refocus: true });
  }

  if (!slot) return null;
  return createPortal(
    <div className="stock-search-tool" data-expanded={open}
      onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) close(); }}
      onKeyDown={(e) => { if (e.key === "Escape") { e.preventDefault(); close({ refocus: true }); } }}>
      <button type="button" ref={trigger} className="stock-search-trigger" aria-label="Search stocks"
        aria-expanded={open} onClick={() => (open ? close({ refocus: true }) : setOpen(true))}>
        <Search size={19} aria-hidden="true" />
      </button>
      {open && (
        <form className="europa-finder" role="search"
          onMouseDown={(e) => { if (!(/** @type {Element} */ (e.target)).closest("input, a")) e.preventDefault(); }}
          onSubmit={(e) => {
            e.preventDefault();
            const pick = options[active] || options[0];
            if (pick) openStock(pick.ticker);
          }}>
          <input autoFocus type="search" role="combobox" aria-label="Search stocks by company or ticker"
            placeholder="Search stocks" value={query} autoComplete="off" spellCheck={false}
            aria-autocomplete="list" aria-expanded={options.length > 0} aria-controls={RESULTS_ID}
            aria-activedescendant={active >= 0 && options[active] ? `${RESULTS_ID}-${active}` : undefined}
            onChange={(e) => { setQuery(e.target.value); setActive(-1); }}
            onKeyDown={(e) => {
              if (!options.length || (e.key !== "ArrowDown" && e.key !== "ArrowUp")) return;
              e.preventDefault();
              const step = e.key === "ArrowDown" ? 1 : -1;
              setActive((i) => (i < 0 && step < 0 ? options.length - 1 : (i + step + options.length) % options.length));
            }} />
          {text && (
            <div className="finder-results" id={RESULTS_ID} role="listbox" aria-label="Matching stocks">
              {options.length ? options.map((c, i) => (
                <a key={c.ticker} id={`${RESULTS_ID}-${i}`} role="option" aria-selected={i === active} tabIndex={-1}
                  href={stockHref(c.ticker)} target="_blank" rel="noopener noreferrer"
                  onMouseEnter={() => setActive(i)}
                  onClick={(e) => {
                    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
                    e.preventDefault();
                    openStock(c.ticker);
                  }}>
                  <strong>{c.ticker}</strong> <span>{c.name}</span>
                </a>
              )) : <p className="finder-empty">No company or ticker matches.</p>}
            </div>
          )}
        </form>
      )}
    </div>,
    slot,
  );
}
