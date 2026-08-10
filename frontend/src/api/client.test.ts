import axios from "axios";
import { describe, expect, it } from "vitest";

import { apiClient } from "@/api/client";

/**
 * Array query params must repeat the key.
 *
 * This is not a style preference — FastAPI binds `list[X]` query params from
 * repeated keys and ignores `key[]=`. Axios's default is the bracket form, so
 * every array filter in the app was silently unfiltered: the request
 * succeeded, the server saw no filter, and the UI showed everything.
 *
 * The test asserts the emitted URL rather than the config object, because the
 * config looks identical either way — the serializer is the only thing that
 * differs, and it only runs at request time.
 */
function uri(params: Record<string, unknown>): string {
  // Read the serializer off the real instance rather than restating it, so the
  // test fails if someone removes it from client.ts.
  return axios.getUri({
    url: "/v1/thing",
    params,
    paramsSerializer: apiClient.defaults.paramsSerializer,
  });
}

describe("apiClient query serialization", () => {
  it("repeats the key for an array instead of using brackets", () => {
    const url = uri({ severity: ["critical", "warning"] });
    expect(url).toContain("severity=critical");
    expect(url).toContain("severity=warning");
    expect(url).not.toContain("severity%5B%5D");
    expect(url).not.toContain("severity[]");
  });

  it("handles a single-element array the same way", () => {
    // The case that shipped broken: one severity selected, filter ignored.
    const url = uri({ severity: ["critical"] });
    expect(url).toContain("severity=critical");
    expect(url).not.toContain("%5B%5D");
  });

  it("leaves scalars untouched", () => {
    const url = uri({ farm_id: "f-1", limit: 50 });
    expect(url).toContain("farm_id=f-1");
    expect(url).toContain("limit=50");
  });

  it("does not emit a key for undefined", () => {
    // Callers pass `undefined` to mean "no filter"; emitting `x=` would be a
    // filter on the empty string.
    expect(uri({ farm_id: "f-1", severity: undefined })).not.toContain("severity");
  });
});
