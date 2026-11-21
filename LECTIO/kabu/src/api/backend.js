// Lightweight client for the backend endpoints this React UI relies on.

import { normalizeJobId } from "../lib/reportStorage.js";
import { normalizeReportFileName, reportDownloadPath, safeSameOriginPath } from "../lib/safeUrl.js";

/**
 * @typedef {{ id?: string, tool: string, input: Record<string, unknown> }} ToolCallEvent
 * @typedef {{ id?: string, tool: string, pct: number, stage?: string }} ToolProgressEvent
 * @typedef {Record<string, unknown> & { id?: string, tool: string, summary?: string,
 *   sources?: string[], source_details?: Record<string, unknown>, source_docs?: unknown[] }} ToolResultEvent
 * @typedef {{ message: string, reason?: string, retry: boolean }} StreamErrorInfo
 * @typedef {{ onText?: (text: string) => void, onError?: (message: string, info?: StreamErrorInfo) => void,
 *   onDone?: () => void, signal?: AbortSignal,
 *   onToolCall?: (event: ToolCallEvent) => void,
 *   onToolProgress?: (event: ToolProgressEvent) => void,
 *   onToolResult?: (event: ToolResultEvent) => void,
 *   onMeta?: (event: { deadline_s?: number, elapsed_s?: number, landed_by_deadline?: boolean }) => void,
 *   mode?: string, jobId?: string,
 *   file?: string, sources?: unknown[], company?: unknown }} ChatStreamOptions
 */

const cleanError = (text, fallback) => {
  if (!text) return fallback;
  if (text.trimStart().startsWith('<')) return fallback;
  // FastAPI JSON error responses: {"detail":"..."} or {"detail":[{...}]}
  try {
    const json = JSON.parse(text);
    if (typeof json.detail === 'string') return json.detail;
    if (Array.isArray(json.detail)) return json.detail.map((d) => d.msg || d.message || '').filter(Boolean).join('; ') || fallback;
  } catch { /* Non-JSON error bodies fall back to their bounded text below. */ }
  return text.length > 200 ? text.slice(0, 200) : text;
};

/** The structured twin of an onError message: the plain words, the server's
 *  reason code when it sent one, and whether asking again can help. Callers
 *  that only read the first onError argument keep the plain string. */
const streamErrorInfo = (message, reason, retry = true) => ({
  message: String(message || 'The response failed.'),
  ...(reason ? { reason: String(reason) } : {}),
  retry: retry !== false,
});

const toFormBody = (payload) => {
  const params = new URLSearchParams();
  Object.entries(payload || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null) {
      params.append(key, value);
    }
  });
  return params;
};

export async function startReport({ stock_code, company_name = '', mode = 'full' }) {
  const body = toFormBody({ stock_code, company_name, mode });
  const res = await fetch('/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(cleanError(text, `Start failed with status ${res.status}`));
  }
  return res.json().catch(() => ({}));
}

export async function getStatus(jobId) {
  const id = normalizeJobId(jobId);
  if (!id) {
    const error = Object.assign(new Error("Invalid report job ID"), { status: 400 });
    throw error;
  }
  const res = await fetch(`/status/${id}`);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    const error = Object.assign(new Error(cleanError(text, `Status failed with ${res.status}`)), { status: res.status });
    throw error;
  }
  const data = await res.json().catch(() => ({}));
  if (normalizeJobId(data?.job_id) !== id) {
    const error = Object.assign(new Error("Status response did not match the requested report job"), { status: 502 });
    throw error;
  }
  return data;
}

// Report links are same-origin relative URLs only (lib/safeUrl.js): anything
// else is dropped before a URL is persisted, displayed, or shared.
export const buildBareDownloadUrl = (filename) => reportDownloadPath(filename);
export const buildBareViewUrl = (filename) => reportDownloadPath(filename, { inline: true });
export const buildDownloadUrl = (filename) => safeSameOriginPath(buildBareDownloadUrl(filename));
export const buildViewUrl = (filename) => safeSameOriginPath(buildBareViewUrl(filename));

/**
 * Stream report-context chat (Haiku-powered, no tools).
 * Same SSE format as streamChat but only emits text/error/done.
 */
/**
 * @param {unknown} jobId
 * @param {unknown} messages
 * @param {ChatStreamOptions} [options]
 */
export async function streamReportChat(jobId, messages, { onText, onError, onDone, signal, file, sources, company } = {}) {
  const payload = { messages };
  const id = jobId ? normalizeJobId(jobId) : null;
  const reportFile = file ? normalizeReportFileName(file, "html") : null;
  if (jobId && !id) { onError?.("Invalid report job ID"); return; }
  if (file && !reportFile) { onError?.("Invalid report file"); return; }
  if (!id && !reportFile) { onError?.("Report identity is required"); return; }
  if (id) payload.job_id = id;
  if (reportFile) payload.file = reportFile;
  if (sources) payload.sources = sources;
  if (company) payload.company = company;

  let res;
  try {
    res = await fetch('/api/report-chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal,
    });
  } catch (e) {
    if (e.name === 'AbortError') return;
    onError?.(`Connection failed: ${e.message}`);
    return;
  }
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    onError?.(cleanError(text, `Chat failed with status ${res.status}`));
    return;
  }
  if (!res.body) { onError?.('No response body'); return; }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let eventType = null;
  let finished = false;

  const processLine = (line) => {
    if (signal?.aborted || finished) return;
    if (line.startsWith('event: ')) {
      eventType = line.slice(7).trim();
    } else if (line.startsWith('data: ') && eventType) {
      try {
        const data = JSON.parse(line.slice(6));
        if (eventType === 'text') onText?.(data.text);
        else if (eventType === 'error') { finished = true; onError?.(data.message); }
        else if (eventType === 'done') { if (!finished) { finished = true; onDone?.(); } }
      } catch { /* Ignore malformed SSE records and continue reading the stream. */ }
      eventType = null;
    } else if (line === '') {
      eventType = null;
    }
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        if (buffer.trim()) buffer.split('\n').forEach(processLine);
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();
      lines.forEach(processLine);
    }
  } catch (e) {
    if (e.name === 'AbortError') { try { reader.cancel(); } catch { /* The reader may already be closed after cancellation. */ } return; }
    try { reader.cancel(); } catch { /* Preserve the original stream error if cleanup also fails. */ }
    if (!finished) onError?.(`Connection lost: ${e.message}`);
    return;
  }
  if (!finished && !signal?.aborted) {
    finished = true;
    onError?.('Stream ended before the server sent a terminal event. The response may be incomplete.');
  }
}

export async function fetchQuote(stockCode) {
  try {
    const res = await fetch(`/api/quote/${encodeURIComponent(stockCode)}`);
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export async function fetchPriceHistory(stockCode, days = 90, interval = "1d") {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 20000);
  try {
    const res = await fetch(`/api/price-history/${encodeURIComponent(stockCode)}?days=${days}&interval=${interval}`, {
      signal: controller.signal,
    });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  } finally {
    clearTimeout(timeout);
  }
}

export async function deleteJob(jobId) {
  const id = normalizeJobId(jobId);
  if (!id) {
    const error = Object.assign(new Error("Invalid report job ID"), { status: 400 });
    throw error;
  }
  const res = await fetch(`/jobs/${id}`, { method: 'DELETE' });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(cleanError(text, `Delete failed with status ${res.status}`));
  }
  return res.json().catch(() => ({}));
}

// /api/chat sends an SSE keepalive after 15 s of silence, so no bytes at all
// for this long means the connection is gone.
export const STREAM_IDLE_MS = 75000;
const STREAM_IDLE_MESSAGE = 'No data from the server for 75 s: the connection seems to have dropped. Please send the question again.';

/**
 * Stream a chat query to the Claude-powered backend.
 * Uses POST with ReadableStream (since EventSource only supports GET).
 * `onMeta` receives the optional `event: meta` object ({deadline_s,
 * elapsed_s, landed_by_deadline}) — older backends never send it, so the
 * caller must treat it as absent-by-default.
 */
/**
 * @param {unknown} messages
 * @param {ChatStreamOptions} [options]
 */
export async function streamChat(messages, { onText, onToolCall, onToolResult, onToolProgress, onMeta, onError, onDone, signal, mode } = {}) {
  let res;
  try {
    const headers = { 'Content-Type': 'application/json' };
    res = await fetch('/api/chat', {
      method: 'POST',
      headers,
      body: JSON.stringify({ messages, mode: mode || "stream" }),
      signal,
    });
  } catch (e) {
    if (e.name === 'AbortError') return; // user cancelled
    const message = `Connection failed: ${e.message}`;
    onError?.(message, streamErrorInfo(message, 'connection'));
    return;
  }

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    const message = cleanError(text, `Chat failed with status ${res.status}`);
    // Rate limits, timeouts and server faults pass; a rejected request does not.
    const retry = res.status === 408 || res.status === 429 || res.status >= 500;
    onError?.(message, streamErrorInfo(message, `http_${res.status}`, retry));
    return;
  }

  if (!res.body) { onError?.('No response body', streamErrorInfo('No response body', 'no_body')); return; }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let finished = false;
  let errored = false;
  let eventType = null; // persist across chunks

  // `info` carries the server's {reason, retry} from `event: error`; local
  // transport failures are always worth one more try.
  const fireError = (msg, info) => {
    if (errored) return;
    errored = true;
    onError?.(msg, streamErrorInfo(msg, info?.reason, info?.retry));
  };
  // The server sends a keepalive at least every 15 s, so a silent stream is a
  // dropped connection: end it with an honest error instead of spinning forever.
  let idleTimer = 0;
  let idleTimedOut = false;
  const armIdle = () => {
    clearTimeout(idleTimer);
    idleTimer = setTimeout(() => {
      idleTimedOut = true;
      try { reader.cancel(); } catch { /* The reader may already be closed. */ }
    }, STREAM_IDLE_MS);
  };
  armIdle();

  try {
    while (true) {
      const { done, value } = await reader.read();
      armIdle();
      if (done) {
        // Process any remaining data in buffer (may contain multiple lines)
        if (buffer.trim()) {
          const remaining = buffer.split('\n');
          buffer = '';
          for (const line of remaining) {
            if (signal?.aborted || finished) break;
            if (line.startsWith('event: ')) {
              eventType = line.slice(7).trim();
            } else if (line.startsWith('data: ') && eventType) {
              try {
                const data = JSON.parse(line.slice(6));
                if (eventType === 'text') onText?.(data.text);
                else if (eventType === 'tool_call') onToolCall?.(data);
                else if (eventType === 'tool_result') onToolResult?.(data);
                else if (eventType === 'tool_progress') onToolProgress?.(data);
                else if (eventType === 'meta') onMeta?.(data);
                else if (eventType === 'error') { finished = true; fireError(data.message, data); }
                else if (eventType === 'done') { if (!finished) { finished = true; onDone?.(); } }
              } catch { /* Ignore malformed SSE records and continue reading the stream. */ }
              eventType = null;
            } else if (line === '') {
              eventType = null;
            }
          }
        }
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop(); // keep incomplete line in buffer

      for (const line of lines) {
        if (signal?.aborted || finished) break;
        if (line.startsWith('event: ')) {
          eventType = line.slice(7).trim();
        } else if (line.startsWith('data: ') && eventType) {
          try {
            const data = JSON.parse(line.slice(6));
            if (eventType === 'text') onText?.(data.text);
            else if (eventType === 'tool_call') onToolCall?.(data);
            else if (eventType === 'tool_result') onToolResult?.(data);
            else if (eventType === 'tool_progress') onToolProgress?.(data);
            else if (eventType === 'meta') onMeta?.(data);
            else if (eventType === 'error') { finished = true; fireError(data.message, data); }
            else if (eventType === 'done') { if (!finished) { finished = true; onDone?.(); } }
          } catch { /* Ignore a malformed final SSE record. */ }
          eventType = null;
        } else if (line === '') {
          eventType = null; // blank line resets per SSE spec
        }
      }
    }
  } catch (e) {
    clearTimeout(idleTimer);
    if (e.name === 'AbortError') { try { reader.cancel(); } catch { /* The reader may already be closed after cancellation. */ } return; } // user cancelled
    try { reader.cancel(); } catch { /* Preserve the original stream error if cleanup also fails. */ } // clean up reader on any error
    if (idleTimedOut && finished) return; // the answer was complete; only the idle tail was cut
    fireError(idleTimedOut ? STREAM_IDLE_MESSAGE : `Connection lost: ${e.message}`, { reason: idleTimedOut ? 'idle' : 'connection_lost' });
    return;
  }
  clearTimeout(idleTimer);
  if (!finished && !signal?.aborted) {
    finished = true;
    fireError(idleTimedOut ? STREAM_IDLE_MESSAGE
      : 'Stream ended before the server sent a terminal event. The response may be incomplete.',
    { reason: idleTimedOut ? 'idle' : 'truncated' });
  }
}
