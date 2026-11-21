import { randomBytes } from "node:crypto";
import { after } from "next/server";

const agentId = "tickerlens-report-agent";
const agentName = "Aditya's Agent";
const id = (bytes: number) => randomBytes(bytes).toString("hex");
const clock = () => (BigInt(Date.now()) * BigInt(1_000_000)).toString();
type Attributes = Record<string, string | number>;
const attributes = (values: Attributes) => Object.entries(values).map(([key, value]) => ({
  key, value: typeof value === "number" ? { intValue: String(value) } : { stringValue: value },
}));

export class ProviderError extends Error {
  constructor(readonly provider: string, readonly status: number) {
    super(`${provider} returned HTTP ${status}`);
  }
}

export async function traced<T>(name: string, run: (span: {
  traceId: string;
  step<T>(name: string, fields: Attributes, fn: (annotate: (fields: Attributes) => void) => Promise<T>): Promise<T>;
}) => Promise<T>): Promise<T> {
  const traceId = id(16);
  const rootId = id(8);
  const common = {
    "gen_ai.agent.id": agentId, "gen_ai.agent.name": agentName,
    "agent.id": agentId, "agent.name": agentName,
    "gen_ai.conversation.id": traceId,
  };
  function finishSpan(spanId: string, label: string, start: string, fields: Attributes, failed: boolean, parentSpanId?: string) {
    return {
      traceId, spanId, ...(parentSpanId ? { parentSpanId } : {}), name: label,
      kind: parentSpanId ? 3 : 2, startTimeUnixNano: start, endTimeUnixNano: clock(),
      attributes: attributes({ ...common, ...fields }), status: { code: failed ? 2 : 1 },
    };
  }
  const spans: ReturnType<typeof finishSpan>[] = [];
  const start = clock();
  let failed = false;
  try {
    return await run({
      traceId,
      async step(label, fields, fn) {
        const start = clock();
        const spanId = id(8);
        let failed = false;
        try {
          return await fn((extra) => Object.assign(fields, extra));
        } catch (error) {
          failed = true;
          fields["error.type"] = error instanceof ProviderError ? String(error.status) : "request_failed";
          throw error;
        } finally {
          spans.push(finishSpan(spanId, label, start, fields, failed, rootId));
        }
      },
    });
  } catch (error) {
    failed = true;
    throw error;
  } finally {
    const key = process.env.PRISMTRACE_API_KEY;
    if (key && spans.length) {
      const root = finishSpan(rootId, name, start, {}, failed);
      const host = process.env.PRISMTRACE_HOST || "https://api.prism.blockconvey.com";
      const body = JSON.stringify({ resourceSpans: [{
        resource: { attributes: attributes({ "service.name": "europa", ...common }) },
        scopeSpans: [{ scope: { name: "europa.server" }, spans: [root, ...spans] }],
      }] });
      after(async () => {
        try {
          const response = await fetch(`${host.replace(/\/$/, "")}/api/otlp/v1/traces`, {
            method: "POST", headers: { "Content-Type": "application/json", "X-PRISMtrace-Key": key },
            body, signal: AbortSignal.timeout(5000), cache: "no-store",
          });
          if (!response.ok) console.warn("PRISM rejected trace", response.status);
          else {
            const result = await response.json().catch(() => null);
            if (result?.partialSuccess?.rejectedSpans) console.warn("PRISM rejected spans", result.partialSuccess.rejectedSpans);
          }
        } catch {
          console.warn("PRISM trace delivery failed");
        }
      });
    }
  }
}

export type Trace = Parameters<Parameters<typeof traced>[1]>[0];
