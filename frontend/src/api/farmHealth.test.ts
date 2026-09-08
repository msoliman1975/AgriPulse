// The URLs these five reads actually request.
//
// This file exists because all five shipped to production without the `/v1`
// segment and every one of them returned 404. Nothing caught it: the page
// tests mock this whole module, so they assert what the screen does with a
// response and never what it asked for. `apiClient`'s baseURL is `/api`, and
// the version belongs to the path — see any other client in this directory.

import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "./client";
import {
  getBlockVerdicts,
  getFarmVerdictHistory,
  getFarmVerdicts,
  getVerdictReasoning,
  getVerdictStatuses,
} from "./farmHealth";

const get = vi.spyOn(apiClient, "get");

/** The path the client asked for, and the params it sent with it. */
function lastCall(): { url: string; params: Record<string, unknown> | undefined } {
  const call = get.mock.calls[get.mock.calls.length - 1];
  const config = call[1];
  return { url: call[0], params: config?.params };
}

describe("farmHealth api paths", () => {
  beforeEach(() => {
    get.mockReset();
    get.mockResolvedValue({ data: {} });
  });

  it("asks for the status catalog under /v1", async () => {
    await getVerdictStatuses();
    expect(lastCall().url).toBe("/v1/verdict-statuses");
  });

  it("asks for a farm's verdicts under /v1", async () => {
    await getFarmVerdicts("farm-1");
    expect(lastCall().url).toBe("/v1/farms/farm-1/verdicts");
  });

  it("passes the replay instant through when one is given", async () => {
    await getFarmVerdicts("farm-1", "2026-09-01T00:00:00Z");
    expect(lastCall().params).toEqual({ at: "2026-09-01T00:00:00Z" });
  });

  it("asks for a block's verdicts under /v1, with the farm it is authorized against", async () => {
    await getBlockVerdicts("block-1", "farm-1");
    const call = lastCall();
    expect(call.url).toBe("/v1/blocks/block-1/verdicts");
    // Without farm_id this is a silent 403 for every farm-scoped user.
    expect(call.params).toEqual({ farm_id: "farm-1" });
  });

  it("asks for the reasoning under /v1", async () => {
    await getVerdictReasoning("block-1", "verdict-1", "farm-1");
    const call = lastCall();
    expect(call.url).toBe("/v1/blocks/block-1/verdicts/verdict-1/reasoning");
    expect(call.params).toEqual({ farm_id: "farm-1" });
  });

  it("asks for the history under /v1, with the window", async () => {
    await getFarmVerdictHistory("farm-1", "2026-08-01", "2026-09-01");
    const call = lastCall();
    expect(call.url).toBe("/v1/farms/farm-1/verdict-history");
    expect(call.params).toEqual({ from: "2026-08-01", to: "2026-09-01" });
  });

  it("names a tree only when one is chosen", async () => {
    // Sending `tree_code: undefined` would put an empty parameter on the
    // query string, which the server reads as a tree with no code.
    await getFarmVerdictHistory("farm-1", "2026-08-01", "2026-09-01", null);
    expect(lastCall().params).toEqual({ from: "2026-08-01", to: "2026-09-01" });

    await getFarmVerdictHistory("farm-1", "2026-08-01", "2026-09-01", "t_cwsi");
    expect(lastCall().params).toEqual({
      from: "2026-08-01",
      to: "2026-09-01",
      tree_code: "t_cwsi",
    });
  });

  it("every path this module requests carries the version segment", async () => {
    // The rule, not the six examples: `apiClient` is mounted at `/api` and
    // the version lives in the path.
    await getVerdictStatuses();
    await getFarmVerdicts("f");
    await getBlockVerdicts("b", "f");
    await getVerdictReasoning("b", "v", "f");
    await getFarmVerdictHistory("f", "a", "z");

    const urls = get.mock.calls.map((call) => call[0]);
    expect(urls).toHaveLength(5);
    for (const url of urls) expect(url.startsWith("/v1/")).toBe(true);
  });
});
