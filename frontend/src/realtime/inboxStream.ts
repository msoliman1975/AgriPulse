// Fetch-stream-based SSE client for `/api/v1/inbox/stream`.
//
// Why not `EventSource`: it does not support custom headers, so we
// can't pass our bearer token without ugly query-string hacks. The
// browser's `fetch` does, and we can parse the SSE wire format off the
// `ReadableStream` it returns.

import { getAccessToken } from "@/auth/token";

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "/api";
const STREAM_URL = `${API_BASE}/v1/inbox/stream`;

export interface InboxStreamEvent {
  id: string;
  alert_id: string | null;
  severity: "info" | "warning" | "critical" | null;
  title: string;
  body: string;
  link_url: string | null;
  created_at: string;
}

export interface InboxStreamHandle {
  /** Stop the stream and release the underlying connection. */
  close(): void;
}

/**
 * Open the inbox SSE stream and invoke `onEvent` for every `inbox`
 * frame the server pushes. `onError` fires once if the stream fails to
 * start or aborts unexpectedly so callers can fall back to polling.
 *
 * The connection automatically closes when the returned handle's
 * `.close()` is called or when the AbortController is signalled.
 */
export function openInboxStream(opts: {
  onEvent: (event: InboxStreamEvent) => void;
  onError?: (err: unknown) => void;
}): InboxStreamHandle {
  const controller = new AbortController();
  void connect(controller, opts);
  return {
    close(): void {
      controller.abort();
    },
  };
}

async function connect(
  controller: AbortController,
  opts: { onEvent: (event: InboxStreamEvent) => void; onError?: (err: unknown) => void },
): Promise<void> {
  const token = getAccessToken();
  if (!token) {
    opts.onError?.(new Error("missing access token"));
    return;
  }
  let response: Response;
  try {
    response = await fetch(STREAM_URL, {
      method: "GET",
      signal: controller.signal,
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "text/event-stream",
      },
    });
  } catch (err) {
    if (!controller.signal.aborted) {
      opts.onError?.(err);
    }
    return;
  }

  if (!response.ok || response.body == null) {
    opts.onError?.(new Error(`SSE connect failed: ${response.status}`));
    return;
  }

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  // SSE frames are separated by a blank line ("\n\n"). We accumulate
  // chunks and split on that delimiter; partial frames stay in the
  // buffer until the next chunk arrives.
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) return;
      buffer += value;
      let sep = buffer.indexOf("\n\n");
      while (sep !== -1) {
        const frame = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        const parsed = parseFrame(frame);
        if (parsed && parsed.event === "inbox") {
          try {
            const data = JSON.parse(parsed.data) as InboxStreamEvent;
            opts.onEvent(data);
          } catch {
            // Malformed payload — ignore and keep reading.
          }
        }
        sep = buffer.indexOf("\n\n");
      }
    }
  } catch (err) {
    if (!controller.signal.aborted) {
      opts.onError?.(err);
    }
  } finally {
    try {
      reader.releaseLock();
    } catch {
      // already released
    }
  }
}

function parseFrame(frame: string): { event: string; data: string } | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const raw of frame.split("\n")) {
    if (raw.startsWith(":")) continue; // comment/keepalive
    if (raw.startsWith("event:")) {
      event = raw.slice("event:".length).trim();
    } else if (raw.startsWith("data:")) {
      dataLines.push(raw.slice("data:".length).trimStart());
    }
  }
  if (dataLines.length === 0) return null;
  return { event, data: dataLines.join("\n") };
}
