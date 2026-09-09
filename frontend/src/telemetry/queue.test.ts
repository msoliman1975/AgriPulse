import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as token from "@/auth/token";

import {
  configureQueue,
  droppedCount,
  enqueue,
  flush,
  MAX_QUEUE,
  queueLength,
  resetQueue,
} from "./queue";
import type { TelemetryEvent } from "./types";

function event(n: number): TelemetryEvent {
  return {
    id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`,
    time: new Date(0).toISOString(),
    event_name: "page_view",
    route: "/farms",
  };
}

describe("telemetry queue", () => {
  beforeEach(() => {
    resetQueue();
    configureQueue({ sessionId: "11111111-1111-4111-8111-111111111111" });
    vi.spyOn(token, "getAccessToken").mockReturnValue("test-token");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 202 })));
  });

  afterEach(() => {
    resetQueue();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("drops the OLDEST event on overflow and counts it", () => {
    // No token, so every flush returns without draining. This is the real
    // shape of the overflow case: a queue only grows when it cannot be sent.
    vi.mocked(token.getAccessToken).mockReturnValue(null);
    for (let i = 0; i < MAX_QUEUE + 9; i += 1) enqueue(event(i));
    expect(queueLength()).toBe(MAX_QUEUE);
    expect(droppedCount()).toBe(9);
  });

  it("keeps events queued while there is no token instead of discarding them", async () => {
    // A hard refresh flushes before the OIDC user has loaded. Draining the
    // queue there would silently lose the first events of every session.
    vi.mocked(token.getAccessToken).mockReturnValue(null);
    enqueue(event(1));
    await flush();
    expect(fetch).not.toHaveBeenCalled();
    expect(queueLength()).toBe(1);

    vi.mocked(token.getAccessToken).mockReturnValue("test-token");
    await flush();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(queueLength()).toBe(0);
  });

  it("auto-flushes once ten events are queued", async () => {
    for (let i = 0; i < 10; i += 1) enqueue(event(i));
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    expect(queueLength()).toBe(0);
  });

  it("sends the batch with keepalive and a bearer token", async () => {
    enqueue(event(1));
    await flush();
    const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/v1/telemetry/events");
    expect(init.keepalive).toBe(true);
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer test-token");
  });

  it("reports the client-side drop count to the server", async () => {
    vi.mocked(token.getAccessToken).mockReturnValue(null);
    for (let i = 0; i < MAX_QUEUE + 5; i += 1) enqueue(event(i));
    vi.mocked(token.getAccessToken).mockReturnValue("test-token");
    vi.mocked(fetch).mockClear();
    await flush();
    const init = vi.mocked(fetch).mock.calls[0]?.[1] as RequestInit;
    const body = JSON.parse(init.body as string) as { dropped: number };
    expect(body.dropped).toBeGreaterThan(0);
  });

  it("never re-queues a failed batch", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new Error("network down"));
    enqueue(event(1));
    await expect(flush()).resolves.toBeUndefined();
    expect(queueLength()).toBe(0);
  });

  it("caps one request at the server's 50-event limit", async () => {
    // Queued with no token so nothing drains, then flushed once. 60 > 50, so
    // a batch that ignored the cap would be rejected wholesale by the server.
    vi.mocked(token.getAccessToken).mockReturnValue(null);
    for (let i = 0; i < 60; i += 1) enqueue(event(i));
    vi.mocked(token.getAccessToken).mockReturnValue("test-token");
    vi.mocked(fetch).mockClear();
    await flush();
    for (const call of vi.mocked(fetch).mock.calls) {
      const body = JSON.parse((call[1] as RequestInit).body as string) as {
        events: unknown[];
      };
      expect(body.events.length).toBeLessThanOrEqual(50);
    }
  });
});
