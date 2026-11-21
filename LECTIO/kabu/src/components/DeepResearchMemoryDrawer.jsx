// Deep Research > Memory drawer. What memory the newest research run used, the
// "Save this as a note?" suggestions offered after it published, and quick
// add / edit / delete of notes, next to the research itself. The server answers
// 503 while memory is off for this account: the drawer then renders nothing and
// stops asking. All memory text renders as text. Mounted once by the DR page.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import './DeepResearchMemoryDrawer.css';

export const POLL_OPEN_MS = 10000;
export const POLL_CLOSED_MS = 30000;
export const RECENT_RUN_S = 6 * 3600;
const LOAD_RETRIES = 3;
const TITLE_MAX = 120;
const BODY_MAX = 4000;
const CODE_RE = /^[1-9][0-9]{2}[0-9A-Z]$/;

const WHY = {
  company: 'This company',
  standing: 'Always applies',
  match: 'Matched the question',
};
const KIND = { note: 'Note', preference: 'Preference', finding: 'Learned' };

// Pure: the badge text for why an item was used.
export function whyLabel(why) {
  return WHY[why] || WHY.match;
}

// Pure: "just now" / "4 min ago" / "3 h ago" / "2 d ago" for epoch seconds.
export function timeAgo(seconds, nowMs = Date.now()) {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds)) return '';
  const diff = Math.max(0, nowMs / 1000 - seconds);
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  return `${Math.floor(diff / 86400)} d ago`;
}

// Pure: "7203, 6758.T 285a" -> { codes: ['7203', '6758', '285A'], bad: [] }.
export function parseCodes(text) {
  const codes = [];
  const bad = [];
  for (const raw of String(text || '').split(/[\s,、，;]+/)) {
    if (!raw) continue;
    let code = raw.trim().toUpperCase().replace(/(\.T|_JPX)$/, '');
    if (code.length === 5 && code.endsWith('0') && CODE_RE.test(code.slice(0, 4))) code = code.slice(0, 4);
    if (CODE_RE.test(code)) { if (!codes.includes(code)) codes.push(code); } else bad.push(raw);
  }
  return { codes, bad };
}

// Pure: a run's last activity (finished/published, else started), seconds; NaN when unknown.
export function runActivityAt(run) {
  if (!run) return NaN;
  if (typeof run.updated_at === 'number' && run.updated_at >= (run.created_at || 0)) return run.updated_at;
  return typeof run.created_at === 'number' ? run.created_at : NaN;
}

// Pure: the logged runs, newest activity first (a run that started earlier but finished
// later is the research the user just read, so it leads); ties keep the server order.
function byActivity(runs) {
  return (Array.isArray(runs) ? runs : [])
    .map((run, i) => ({ run, i, at: runActivityAt(run) }))
    .filter((x) => Number.isFinite(x.at))
    .sort((a, b) => (b.at - a.at) || (a.i - b.i))
    .map((x) => x.run);
}

// Pure: the run with the newest activity within RECENT_RUN_S (the research on screen), or null.
export function latestRun(runs, nowMs = Date.now()) {
  const run = byActivity(runs)[0];
  if (!run) return null;
  return nowMs / 1000 - runActivityAt(run) <= RECENT_RUN_S ? run : null;
}

// Pure: every open suggestion of the recent runs, newest activity first, with its run key.
export function openSuggestions(runs, nowMs = Date.now()) {
  const out = [];
  for (const run of byActivity(runs)) {
    if (nowMs / 1000 - runActivityAt(run) > RECENT_RUN_S) continue;
    for (const s of run.suggestions || []) out.push({ ...s, key: run.key, question: run.question });
  }
  return out.slice(0, 3);
}

async function call(path, init) {
  let response;
  try {
    response = await fetch(path, init);
  } catch {
    return { status: 0, data: null };
  }
  let data = null;
  try { data = await response.json(); } catch { /* an empty or non-JSON body */ }
  return { status: response.status, data };
}

const json = (method, body) => ({
  method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
});

function errorText(status, data) {
  if (data && data.error === 'rate_limited') return 'Too many changes in a short time. Wait a minute.';
  if (data && data.error === 'memory_full') return 'Memory is full (500 items). Delete some first.';
  if (data && (data.error === 'too_long' || data.error === 'invalid')) return data.message || 'That could not be saved.';
  if (status === 401 || status === 403) return 'Your session has ended. Sign in again.';
  return 'Memory could not be reached. Try again.';
}

export default function DeepResearchMemoryDrawer() {
  const [phase, setPhase] = useState('loading');      // loading | ready | off
  const [open, setOpen] = useState(false);
  const [runs, setRuns] = useState([]);
  const [items, setItems] = useState([]);
  const [semantic, setSemantic] = useState(false);
  const [inUse, setInUse] = useState(true);
  const [seen, setSeen] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);
  const [draft, setDraft] = useState({ title: '', body: '', codes: '' });
  const [editing, setEditing] = useState(null);       // { id, title, body, codes }
  const alive = useRef(true);
  const panelRef = useRef(null);
  const tabRef = useRef(null);
  useEffect(() => () => { alive.current = false; }, []);

  const loadActivity = useCallback(async () => {
    const { status, data } = await call('/api/memory/activity');
    if (!alive.current) return false;
    if (status === 200 && data) {
      setRuns(Array.isArray(data.runs) ? data.runs : []);
      setSemantic(Boolean(data.semantic));
      setInUse(data.use_in_research !== false);
      setPhase('ready');
      return true;
    }
    // off for this account, signed out, or a server without the route: hide and stop asking
    if ([401, 403, 404, 405, 503].includes(status)) setPhase('off');
    return false;
  }, []);
  const loadItems = useCallback(async () => {
    const { status, data } = await call('/api/memory');
    if (!alive.current) return;
    if (status === 200 && data) setItems(Array.isArray(data.items) ? data.items : []);
    else if (status === 503) setPhase('off');
  }, []);

  useEffect(() => { loadActivity(); }, [loadActivity]);
  // a network error or a 5xx at mount: try a few more times, slowly
  const [retries, setRetries] = useState(0);
  useEffect(() => {
    if (phase !== 'loading' || retries >= LOAD_RETRIES) return undefined;
    const timer = setTimeout(() => { setRetries((n) => n + 1); loadActivity(); }, POLL_CLOSED_MS / 2);
    return () => clearTimeout(timer);
  }, [phase, retries, loadActivity]);
  useEffect(() => { if (open && phase === 'ready') loadItems(); }, [open, phase, loadItems]);
  // light polling while the page is visible; none once memory is off
  useEffect(() => {
    if (phase !== 'ready') return undefined;
    const tick = setInterval(() => {
      if (typeof document === 'undefined' || document.visibilityState === 'visible') loadActivity();
    }, open ? POLL_OPEN_MS : POLL_CLOSED_MS);
    return () => clearInterval(tick);
  }, [phase, open, loadActivity]);
  useEffect(() => {
    if (!open) return undefined;
    panelRef.current?.focus();
    const onKey = (event) => { if (event.key === 'Escape') { setOpen(false); tabRef.current?.focus(); } };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  const suggestions = openSuggestions(runs);
  const newest = suggestions.length ? `${suggestions[0].key}:${suggestions.length}` : '';
  useEffect(() => { if (open && newest) setSeen(newest); }, [open, newest]);

  const work = async (fn) => {
    setBusy(true);
    setMessage(null);
    try { await fn(); } finally { if (alive.current) setBusy(false); }
  };
  const fail = (status, data) => {
    if (status === 503) setPhase('off');
    else setMessage(errorText(status, data));
  };

  const accept = (s) => work(async () => {
    const { status, data } = await call(`/api/memory/suggestions/${s.key}/accept`, json('POST', { index: s.index }));
    if (!alive.current) return;
    if (status === 201) { setMessage('Saved as a note.'); await Promise.all([loadActivity(), loadItems()]); } else fail(status, data);
  });
  const dismiss = (s) => work(async () => {
    const { status, data } = await call(`/api/memory/suggestions/${s.key}/dismiss`, json('POST', { index: s.index }));
    if (!alive.current) return;
    if (status === 200 || status === 404) await loadActivity(); else fail(status, data);
  });
  const add = (event) => {
    event.preventDefault();
    const title = draft.title.trim();
    if (!title) return;
    const { codes, bad } = parseCodes(draft.codes);
    if (bad.length) { setMessage(`Not a ticker code: ${bad.join(', ')}`); return; }
    work(async () => {
      const { status, data } = await call('/api/memory', json('POST', { kind: 'note', title, body: draft.body, codes }));
      if (!alive.current) return;
      if (status === 201) { setDraft({ title: '', body: '', codes: '' }); await loadItems(); } else fail(status, data);
    });
  };
  const saveEdit = (event) => {
    event.preventDefault();
    if (!editing || !editing.title.trim()) return;
    const { codes, bad } = parseCodes(editing.codes);
    if (bad.length) { setMessage(`Not a ticker code: ${bad.join(', ')}`); return; }
    work(async () => {
      const { status, data } = await call(`/api/memory/${editing.id}`,
        json('PATCH', { title: editing.title.trim(), body: editing.body, codes }));
      if (!alive.current) return;
      if (status === 200) { setEditing(null); await loadItems(); } else fail(status, data);
    });
  };
  const remove = (id) => work(async () => {
    const { status, data } = await call(`/api/memory/${id}`, { method: 'DELETE' });
    if (!alive.current) return;
    if (status === 200 || status === 404) await Promise.all([loadItems(), loadActivity()]); else fail(status, data);
  });

  if (phase !== 'ready') return null;
  return (
    <MemoryDrawerView open={open} run={latestRun(runs)} suggestions={suggestions} items={items}
      semantic={semantic} inUse={inUse} busy={busy} message={message} draft={draft} editing={editing}
      fresh={Boolean(newest) && newest !== seen} panelRef={panelRef} tabRef={tabRef}
      onToggle={() => setOpen((v) => !v)} onClose={() => setOpen(false)} onAccept={accept} onDismiss={dismiss}
      onDraft={setDraft} onAdd={add} onEdit={setEditing} onSaveEdit={saveEdit} onRemove={remove} />
  );
}

function Codes({ codes }) {
  if (!codes || !codes.length) return null;
  return (
    <span className="drmem__codes">
      {codes.map((c) => <span key={c} className="drmem__code">{c}</span>)}
    </span>
  );
}

// Presentational: everything the drawer shows, from plain props (rendered in tests).
export function MemoryDrawerView({ open, run, suggestions, items, semantic, inUse = true, busy, message, draft, editing, fresh,
  panelRef, tabRef, onToggle, onClose, onAccept, onDismiss, onDraft, onAdd, onEdit, onSaveEdit, onRemove }) {
  const notes = (items || []).filter((i) => i.kind !== 'finding');
  const learned = (items || []).filter((i) => i.kind === 'finding');
  return (
    <div className={`drmem${open ? ' is-open' : ''}`}>
      <button ref={tabRef} type="button" className="drmem__tab" data-testid="dr-memory-tab"
        aria-expanded={open} aria-controls="dr-memory-panel" onClick={onToggle}>
        <span className="drmem__tab-label">Memory</span>
        {fresh ? <span className="drmem__dot" data-testid="dr-memory-fresh" aria-label="New suggestions" /> : null}
      </button>
      {open ? (
        <aside id="dr-memory-panel" ref={panelRef} tabIndex={-1} className="drmem__panel" role="dialog"
          aria-modal="false" aria-labelledby="dr-memory-title" data-testid="dr-memory-drawer">
          <header className="drmem__head">
            <div>
              <h2 id="dr-memory-title" className="drmem__title">Memory</h2>
              <p className="drmem__sub">
                Private to your account. Research uses it as context, never as a source.
                {semantic ? ' Recall understands Japanese and English.' : ''}
              </p>
            </div>
            <button type="button" className="drmem__close" onClick={onClose} aria-label="Close memory">×</button>
          </header>

          {message ? <p className="drmem__message" role="status">{message}</p> : null}

          <section className="drmem__section" aria-labelledby="drmem-used" data-testid="dr-memory-used">
            <h3 id="drmem-used" className="drmem__h">Latest research</h3>
            {!inUse ? (
              <p className="drmem__empty" data-testid="dr-memory-paused">
                Research does not use your memory right now. Turn it on under Memory settings.
              </p>
            ) : null}
            {run ? (
              <>
                <p className="drmem__question" title={run.question}>
                  {run.question || 'Research run'} <span className="drmem__meta">{timeAgo(runActivityAt(run))}</span>
                </p>
                {run.used && run.used.length ? (
                  <ul className="drmem__list">
                    {run.used.map((u) => (
                      <li key={u.id} className="drmem__used">
                        <span className="drmem__used-title">{u.title}</span>
                        <span className={`drmem__why is-${u.why || 'match'}`}>{whyLabel(u.why)}</span>
                      </li>
                    ))}
                  </ul>
                ) : <p className="drmem__empty">No memory was used for this run.</p>}
              </>
            ) : <p className="drmem__empty">What memory your next research run uses shows here.</p>}
          </section>

          {suggestions && suggestions.length ? (
            <section className="drmem__section" aria-labelledby="drmem-suggest">
              <h3 id="drmem-suggest" className="drmem__h">Save this as a note?</h3>
              <ul className="drmem__list">
                {suggestions.map((s) => (
                  <li key={`${s.key}:${s.index}`} className="drmem__suggestion" data-testid="dr-memory-suggestion">
                    <p className="drmem__suggestion-text">{s.title}</p>
                    <Codes codes={s.codes} />
                    <div className="drmem__actions">
                      <button type="button" className="drmem__btn is-primary" disabled={busy} onClick={() => onAccept(s)}>Save note</button>
                      <button type="button" className="drmem__btn" disabled={busy} onClick={() => onDismiss(s)}>Dismiss</button>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          <section className="drmem__section" aria-labelledby="drmem-notes">
            <h3 id="drmem-notes" className="drmem__h">Your notes</h3>
            <form className="drmem__form" onSubmit={onAdd} data-testid="dr-memory-add">
              <input className="drmem__input" aria-label="New note" placeholder="Add a note, e.g. Show figures in JPY bn"
                maxLength={TITLE_MAX} value={draft.title} disabled={busy}
                onChange={(e) => onDraft({ ...draft, title: e.target.value })} />
              <div className="drmem__row">
                <input className="drmem__input drmem__input--codes" aria-label="Ticker codes (optional)"
                  placeholder="Codes, e.g. 7203" value={draft.codes} disabled={busy}
                  onChange={(e) => onDraft({ ...draft, codes: e.target.value })} />
                <button type="submit" className="drmem__btn is-primary" disabled={busy || !draft.title.trim()}>Add</button>
              </div>
            </form>
            {notes.length ? (
              <ul className="drmem__list">
                {notes.map((item) => (
                  <li key={item.id} className="drmem__item" data-testid="dr-memory-item">
                    {editing && editing.id === item.id ? (
                      <form className="drmem__form" onSubmit={onSaveEdit}>
                        <input className="drmem__input" aria-label="Note title" maxLength={TITLE_MAX} value={editing.title}
                          onChange={(e) => onEdit({ ...editing, title: e.target.value })} />
                        <textarea className="drmem__input drmem__textarea" aria-label="Note details" maxLength={BODY_MAX}
                          value={editing.body} onChange={(e) => onEdit({ ...editing, body: e.target.value })} />
                        <input className="drmem__input drmem__input--codes" aria-label="Ticker codes" value={editing.codes}
                          placeholder="Codes, e.g. 7203" onChange={(e) => onEdit({ ...editing, codes: e.target.value })} />
                        <div className="drmem__actions">
                          <button type="submit" className="drmem__btn is-primary" disabled={busy}>Save</button>
                          <button type="button" className="drmem__btn" onClick={() => onEdit(null)}>Cancel</button>
                        </div>
                      </form>
                    ) : (
                      <>
                        <div className="drmem__item-main">
                          <span className="drmem__item-title">{item.title}</span>
                          <span className="drmem__meta">{KIND[item.kind] || 'Note'}</span>
                          <Codes codes={item.codes} />
                          {item.body ? <p className="drmem__item-body">{item.body}</p> : null}
                        </div>
                        <div className="drmem__actions">
                          <button type="button" className="drmem__btn" disabled={busy}
                            onClick={() => onEdit({ id: item.id, title: item.title, body: item.body || '', codes: (item.codes || []).join(' ') })}>Edit</button>
                          <button type="button" className="drmem__btn" disabled={busy} onClick={() => onRemove(item.id)}>Delete</button>
                        </div>
                      </>
                    )}
                  </li>
                ))}
              </ul>
            ) : <p className="drmem__empty">No notes yet. A note applies to every run; add codes to keep it to one company.</p>}
          </section>

          {learned.length ? (
            <section className="drmem__section" aria-labelledby="drmem-learned">
              <details className="drmem__learned">
                <summary id="drmem-learned" className="drmem__h">{`Learned from your research (${learned.length})`}</summary>
                <ul className="drmem__list">
                  {learned.map((item) => (
                    <li key={item.id} className={`drmem__item${item.superseded ? ' is-superseded' : ''}`}>
                      <div className="drmem__item-main">
                        <span className="drmem__item-title">{item.title}</span>
                        {item.superseded ? <span className="drmem__meta">Replaced by newer research</span> : null}
                        <Codes codes={item.codes} />
                      </div>
                      <div className="drmem__actions">
                        <button type="button" className="drmem__btn" disabled={busy} onClick={() => onRemove(item.id)}>Delete</button>
                      </div>
                    </li>
                  ))}
                </ul>
              </details>
            </section>
          ) : null}

          <footer className="drmem__foot">
            <a href="#/account" className="drmem__link">Memory settings and export</a>
          </footer>
        </aside>
      ) : null}
    </div>
  );
}
