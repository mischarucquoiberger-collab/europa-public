import React, { useEffect, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Globe, FileText, Search, ArrowUpRight } from "lucide-react";
import { safeExternalUrl } from "@/lib/safeUrl";

/* ── Source type accents ──────────────────────────────── */
const TYPE_ACCENT = {
  edinet: { text: "#fcd34d", ring: "rgba(251,191,36,0.3)", bg: "rgba(245,158,11,0.12)" },
  web: { text: "#93c5fd", ring: "rgba(96,165,250,0.3)", bg: "rgba(59,130,246,0.14)" },
};

/* ── Search match highlighter ────────────────────────── */
function Highlight({ text, query }) {
  if (!text) return null;
  const q = query?.trim();
  if (!q) return <>{text}</>;
  try {
    const safe = q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const parts = String(text).split(new RegExp(`(${safe})`, "ig"));
    return (
      <>
        {parts.map((p, i) =>
          p.toLowerCase() === q.toLowerCase() ? (
            <span
              key={i}
              className="font-bold text-[#f4f5f7]"
              style={{ background: "rgba(255,255,255,0.12)", borderRadius: 3, padding: "1px 2px" }}
            >
              {p}
            </span>
          ) : (
            <React.Fragment key={i}>{p}</React.Fragment>
          )
        )}
      </>
    );
  } catch {
    return <>{text}</>;
  }
}

/* ── One source card ─────────────────────────────────── */
function SourceCard({ source, index, query }) {
  const isEdinet = source.type === "edinet";
  const accent = isEdinet ? TYPE_ACCENT.edinet : TYPE_ACCENT.web;
  const sourceUrl = safeExternalUrl(source.url);

  let hostname = "";
  try {
    hostname = new URL(sourceUrl).hostname.replace(/^www\./, "");
  } catch { /* An invalid source URL leaves the optional hostname empty. */ }

  const restShadow =
    "0 1px 3px rgba(0,0,0,0.2), 0 0 0 1px rgba(255,255,255,0.12)";
  const hoverShadow =
    "0 12px 28px -10px rgba(0,0,0,0.45), 0 4px 10px -4px rgba(0,0,0,0.25), 0 0 0 1px rgba(255,255,255,0.2)";

  return (
    <motion.a
      href={sourceUrl || undefined}
      target={sourceUrl ? "_blank" : undefined}
      rel="noreferrer"
      onClick={sourceUrl ? undefined : (e) => e.preventDefault()}
      aria-disabled={sourceUrl ? undefined : "true"}
      initial={{ opacity: 0, y: 5 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: 0.35,
        ease: [0.16, 1, 0.3, 1],
        delay: Math.min(index * 0.015, 0.25),
      }}
      className="group relative block overflow-hidden no-underline"
      style={{
        borderRadius: 16,
        background: "rgba(255,255,255,0.05)",
        boxShadow: restShadow,
        transition:
          "box-shadow 380ms cubic-bezier(0.16,1,0.3,1), transform 380ms cubic-bezier(0.16,1,0.3,1)",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.boxShadow = hoverShadow;
        e.currentTarget.style.transform = "translateY(-1.5px)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.boxShadow = restShadow;
        e.currentTarget.style.transform = "translateY(0)";
      }}
    >
      <div className="relative flex items-start gap-[14px] px-[18px] py-[15px]">
        {/* Type badge */}
        <span
          className="shrink-0 inline-flex items-center justify-center h-[22px] px-[8px] mt-[1px] rounded-[7px] text-[9.5px] font-bold tracking-[0.1em] uppercase"
          style={{
            background: accent.bg,
            color: accent.text,
            boxShadow: `inset 0 0 0 1px ${accent.ring}`,
          }}
        >
          {isEdinet ? "SEC" : "WEB"}
        </span>

        {/* Content */}
        <div className="min-w-0 flex-1">
          <p className="text-[13.5px] font-semibold text-white/90 leading-[1.45] tracking-[-0.01em] line-clamp-2 group-hover:text-[#f4f5f7] transition-colors duration-300">
            <Highlight text={source.title || hostname || "Untitled"} query={query} />
          </p>
          {hostname && (
            <p className="text-[11px] text-white/50 font-mono truncate mt-[5px] tracking-[-0.01em]">
              {hostname}
            </p>
          )}
          {source.snippet && (
            <p className="text-[12px] text-white/60 mt-[7px] line-clamp-2 leading-[1.6] tracking-[-0.005em]">
              <Highlight text={source.snippet} query={query} />
            </p>
          )}
          {source.date && (
            <p className="text-[10.5px] text-white/40 mt-[7px] font-medium tabular-nums tracking-wide">
              {source.date}
            </p>
          )}
        </div>

        {/* External arrow */}
        {sourceUrl && (
          <div className="shrink-0 w-[28px] h-[28px] rounded-full flex items-center justify-center text-white/40 transition-all duration-300 mt-[1px] group-hover:text-white/70 group-hover:bg-white/[0.05]">
            <ArrowUpRight
              className="w-[14px] h-[14px] transition-transform duration-300 group-hover:translate-x-[1.5px] group-hover:-translate-y-[1.5px]"
              style={{ transitionTimingFunction: "cubic-bezier(0.16, 1, 0.3, 1)" }}
              strokeWidth={2}
            />
          </div>
        )}
      </div>
    </motion.a>
  );
}

/* ── Section header ──────────────────────────────────── */
function Section({ title, icon: Icon, count, children }) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-[14px] px-1">
        <Icon className="w-[13px] h-[13px] text-white/45" strokeWidth={2} style={{ color: "rgba(255,255,255,0.32)" }} />
        <h3
          className="text-[10px] font-semibold uppercase tracking-[0.16em]"
          style={{ color: "rgba(255,255,255,0.38)" }}
        >
          {title}
        </h3>
        <span className="ml-auto text-[10.5px] font-medium tabular-nums" style={{ color: "rgba(255,255,255,0.25)" }}>
          {count}
        </span>
      </div>
      <div className="space-y-[10px]">{children}</div>
    </div>
  );
}

/* ── Empty state ─────────────────────────────────────── */
function EmptyState({ message, hint = null }) {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <div
        className="w-11 h-11 rounded-[14px] flex items-center justify-center mb-4"
        style={{
          background: "linear-gradient(180deg, rgba(255,255,255,0.07) 0%, rgba(255,255,255,0.04) 100%)",
          boxShadow:
            "0 1px 3px rgba(0,0,0,0.2), 0 0 0 1px rgba(255,255,255,0.12)",
        }}
      >
        <Search className="w-[16px] h-[16px] text-white/40" strokeWidth={2} />
      </div>
      <p className="text-[13px] text-white/60 font-medium tracking-[-0.005em]">
        {message}
      </p>
      {hint && (
        <p className="text-[11px] text-white/40 mt-[6px] tracking-[-0.005em]">
          {hint}
        </p>
      )}
    </div>
  );
}

/* ── Filter tab ──────────────────────────────────────── */
function FilterTab({ label, count, active, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="relative flex items-center gap-[5px] px-3 h-[30px] rounded-[9px] text-[11px] font-semibold transition-all duration-300 focus:outline-none"
      style={{
        color: active ? "#f4f5f7" : "rgba(255,255,255,0.42)",
        background: active ? "rgba(255,255,255,0.1)" : "transparent",
        boxShadow: active
          ? "0 1px 3px rgba(0,0,0,0.2), 0 0 0 1px rgba(255,255,255,0.12)"
          : "none",
        letterSpacing: "-0.005em",
      }}
    >
      <span>{label}</span>
      <span
        className="text-[9.5px] font-medium tabular-nums"
        style={{ color: active ? "rgba(255,255,255,0.38)" : "rgba(255,255,255,0.28)" }}
      >
        {count}
      </span>
    </button>
  );
}

/* ── Keycap ──────────────────────────────────────────── */
function Kbd({ children }) {
  return (
    <span
      className="inline-flex items-center justify-center h-[18px] min-w-[18px] px-[5px] rounded-[5px] text-[10px] font-semibold tabular-nums"
      style={{
        fontFamily: "'Space Grotesk', sans-serif",
        color: "rgba(255,255,255,0.35)",
        background: "linear-gradient(180deg, rgba(255,255,255,0.08) 0%, rgba(255,255,255,0.05) 100%)",
        boxShadow:
          "0 1px 0 rgba(0,0,0,0.3), 0 0 0 1px rgba(255,255,255,0.12), inset 0 1px 0 rgba(255,255,255,0.06)",
      }}
    >
      {children}
    </span>
  );
}

/* ── Main modal ──────────────────────────────────────── */
export default function SourcesModal({
  isOpen,
  onClose,
  sources = [],
  companyName,
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const searchRef = useRef(null);
  const panelRef = useRef(null);
  const closeBtnRef = useRef(null);
  const prevFocusRef = useRef(null);

  useEffect(() => {
    if (!isOpen) return;
    setQuery("");
    setFilter("all");
    // Capture the element that had focus before opening, seed focus to Close.
    prevFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeBtnRef.current?.focus();
    const t = setTimeout(() => searchRef.current?.focus(), 280);
    return () => {
      clearTimeout(t);
      // Restore focus to wherever it was before the modal opened.
      prevFocusRef.current?.focus?.();
      prevFocusRef.current = null;
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const handler = (e) => {
      if (e.key === "Escape") {
        onClose?.();
        return;
      }
      if (e.key !== "Tab") return;
      const panel = panelRef.current;
      if (!panel) return;
      const focusables = panel.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const active = document.activeElement;
      // Keep Tab focus cycling within the dialog panel.
      if (e.shiftKey) {
        if (active === first || !panel.contains(active)) {
          e.preventDefault();
          last.focus();
        }
      } else {
        if (active === last || !panel.contains(active)) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [isOpen, onClose]);

  const webCount = useMemo(
    () => sources.filter((s) => s.type !== "edinet").length,
    [sources]
  );
  const edinetCount = useMemo(
    () => sources.filter((s) => s.type === "edinet").length,
    [sources]
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return sources.filter((s) => {
      if (filter === "web" && s.type === "edinet") return false;
      if (filter === "edinet" && s.type !== "edinet") return false;
      if (!q) return true;
      const hay = `${s.title || ""} ${s.snippet || ""} ${s.url || ""}`.toLowerCase();
      return hay.includes(q);
    });
  }, [sources, query, filter]);

  const grouped = useMemo(
    () => ({
      web: filtered.filter((s) => s.type !== "edinet"),
      edinet: filtered.filter((s) => s.type === "edinet"),
    }),
    [filtered]
  );

  const hasBothKinds = webCount > 0 && edinetCount > 0;

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* ── Backdrop ─────────────────────────────── */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.28 }}
            className="fixed inset-0 z-50"
            style={{
              background: "rgba(15,23,42,0.18)",
              backdropFilter: "blur(12px) saturate(140%)",
              WebkitBackdropFilter: "blur(12px) saturate(140%)",
            }}
            onClick={onClose}
          />

          {/* ── Dialog ───────────────────────────────── */}
          <motion.div
            initial={{ opacity: 0, scale: 0.965, y: 18, filter: "blur(6px)" }}
            animate={{ opacity: 1, scale: 1, y: 0, filter: "blur(0px)" }}
            exit={{ opacity: 0, scale: 0.97, y: 12, filter: "blur(2px)" }}
            transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
            className="fixed inset-0 z-50 flex items-center justify-center p-5 pointer-events-none"
            role="dialog"
            aria-modal="true"
            aria-label="Report sources"
          >
            <div
              ref={panelRef}
              className="pointer-events-auto w-full max-w-[700px] h-[85vh] max-h-[85vh] flex flex-col overflow-hidden relative"
              style={{
                borderRadius: 22,
                background: "#0e1420",
                boxShadow:
                  "0 40px 80px -20px rgba(0,0,0,0.5), 0 16px 40px -12px rgba(0,0,0,0.3), 0 0 0 1px rgba(255,255,255,0.12)",
                fontFamily: "'Space Grotesk', sans-serif",
              }}
            >
              {/* ── Header ───────────────────────────── */}
              <div className="shrink-0 px-8 pt-7 pb-5 flex items-start justify-between">
                <div className="min-w-0">
                  <h2 className="text-[20px] font-semibold text-[#f4f5f7] tracking-[-0.025em] leading-[1.1]">
                    Sources
                  </h2>
                  <p className="text-[12.5px] text-white/50 mt-[6px] truncate tracking-[-0.005em] font-medium">
                    {sources.length} reference{sources.length !== 1 ? "s" : ""}
                    {companyName ? (
                      <>
                        <span className="mx-[6px]" style={{ color: "rgba(255,255,255,0.2)" }}>·</span>
                        {companyName}
                      </>
                    ) : ""}
                  </p>
                </div>
                <button
                  ref={closeBtnRef}
                  onClick={onClose}
                  aria-label="Close"
                  className="shrink-0 w-[32px] h-[32px] rounded-full flex items-center justify-center text-white/50 hover:text-white/70 hover:bg-white/[0.07] transition-all duration-200 focus:outline-none"
                >
                  <X className="w-4 h-4" strokeWidth={2.25} />
                </button>
              </div>

              {/* ── Search + filter tabs ─────────────── */}
              {sources.length > 0 && (
                <div className="shrink-0 px-8 pb-5 flex items-center gap-3">
                  <div className="relative flex-1 min-w-0">
                    <Search
                      className="absolute left-[13px] top-1/2 -translate-y-1/2 w-[14px] h-[14px] text-white/40 pointer-events-none"
                      strokeWidth={2.25}
                    />
                    <input
                      ref={searchRef}
                      type="text"
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      placeholder="Search sources…"
                      className="w-full h-[40px] pl-[38px] pr-4 rounded-[12px] text-[13px] text-white/90 placeholder:text-white/35 bg-white/[0.05] border border-white/[0.1] caret-white focus:border-white/[0.2] focus:bg-white/[0.07] focus:outline-none focus:ring-2 focus:ring-white/[0.1] transition-all duration-200 tracking-[-0.005em]"
                      style={{ fontFamily: "'Space Grotesk', sans-serif" }}
                    />
                  </div>
                  {hasBothKinds && (
                    <div className="flex items-center gap-[2px] p-[3px] rounded-[12px] bg-white/[0.05] border border-white/[0.1]">
                      <FilterTab
                        label="All"
                        count={sources.length}
                        active={filter === "all"}
                        onClick={() => setFilter("all")}
                      />
                      <FilterTab
                        label="Web"
                        count={webCount}
                        active={filter === "web"}
                        onClick={() => setFilter("web")}
                      />
                      <FilterTab
                        label="SEC"
                        count={edinetCount}
                        active={filter === "edinet"}
                        onClick={() => setFilter("edinet")}
                      />
                    </div>
                  )}
                </div>
              )}

              {/* Divider */}
              <div aria-hidden className="shrink-0 h-px bg-white/[0.12]" />

              {/* ── Body ─────────────────────────────── */}
              <div className="relative flex-1 min-h-0">
                <div className="absolute inset-0 overflow-y-auto sources-scroll px-8 py-6 overscroll-contain">
                  {sources.length === 0 ? (
                    <EmptyState message="No sources available for this report." />
                  ) : filtered.length === 0 ? (
                    <EmptyState
                      message={
                        query ? `No sources match "${query}"` : "No sources in this view"
                      }
                      hint={query ? "Try a different search term" : undefined}
                    />
                  ) : filter === "all" ? (
                    <div className="space-y-8">
                      {grouped.web.length > 0 && (
                        <Section
                          title="Web Sources"
                          icon={Globe}
                          count={grouped.web.length}
                        >
                          {grouped.web.map((source, i) => (
                            <SourceCard
                              key={source.id || `${source.url}-${i}`}
                              source={source}
                              index={i}
                              query={query}
                            />
                          ))}
                        </Section>
                      )}
                      {grouped.edinet.length > 0 && (
                        <Section
                          title="SEC Filings"
                          icon={FileText}
                          count={grouped.edinet.length}
                        >
                          {grouped.edinet.map((source, i) => (
                            <SourceCard
                              key={source.id || `${source.url}-${i}`}
                              source={source}
                              index={i}
                              query={query}
                            />
                          ))}
                        </Section>
                      )}
                    </div>
                  ) : (
                    <div className="space-y-[10px]">
                      {filtered.map((source, i) => (
                        <SourceCard
                          key={source.id || `${source.url}-${i}`}
                          source={source}
                          index={i}
                          query={query}
                        />
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {/* ── Footer ───────────────────────────── */}
              <div className="shrink-0 px-8 h-[44px] flex items-center justify-between border-t border-white/[0.1]">
                <span className="text-[11px] font-medium tabular-nums" style={{ color: "rgba(255,255,255,0.28)" }}>
                  {filtered.length} of {sources.length}
                </span>
                <span className="flex items-center gap-[7px] text-[11px]" style={{ color: "rgba(255,255,255,0.3)" }}>
                  <Kbd>Esc</Kbd>
                  <span>to close</span>
                </span>
              </div>
            </div>
          </motion.div>

          {/* Scoped scrollbar styles */}
          <style>{`
            .sources-scroll::-webkit-scrollbar { width: 11px; }
            .sources-scroll::-webkit-scrollbar-track { background: transparent; }
            .sources-scroll::-webkit-scrollbar-thumb {
              background: rgba(255,255,255,0.1);
              border-radius: 10px;
              border: 3px solid transparent;
              background-clip: padding-box;
            }
            .sources-scroll::-webkit-scrollbar-thumb:hover {
              background: rgba(255,255,255,0.18);
              background-clip: padding-box;
              border: 3px solid transparent;
            }
          `}</style>
        </>
      )}
    </AnimatePresence>
  );
}
