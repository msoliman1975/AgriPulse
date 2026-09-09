import { describe, expect, it } from "vitest";

import { apiRouteTemplate, errorCodeFrom } from "./capture";

/**
 * `api_route` is the field that tells you WHICH CALL broke. It only earns its
 * place if it groups, and it only stays safe if it never carries an id — the
 * props allow-list exists to keep customer data out of this store, and a
 * resolved URL is the easiest way to smuggle some in.
 */
describe("apiRouteTemplate", () => {
  it("replaces a uuid path segment", () => {
    expect(apiRouteTemplate("/v1/farms/8f3a1b2c-0000-4000-8000-000000000000/blocks")).toBe(
      "/v1/farms/:id/blocks",
    );
  });

  it("replaces every uuid, not just the first", () => {
    expect(
      apiRouteTemplate(
        "/v1/farms/8f3a1b2c-0000-4000-8000-000000000000/blocks/9c1b6f2e-0000-4000-8000-000000000001",
      ),
    ).toBe("/v1/farms/:id/blocks/:id");
  });

  it("replaces numeric ids", () => {
    expect(apiRouteTemplate("/v1/decision-trees/42/versions/7")).toBe(
      "/v1/decision-trees/:n/versions/:n",
    );
  });

  it("drops the query string whole", () => {
    // Filter values are user input and no grouping question needs them.
    expect(apiRouteTemplate("/v1/alerts?status=open&q=north%20field")).toBe("/v1/alerts");
  });

  it("leaves a static path alone", () => {
    expect(apiRouteTemplate("/v1/platform/usage/overview")).toBe("/v1/platform/usage/overview");
  });

  it("reports a missing url rather than throwing", () => {
    expect(apiRouteTemplate(undefined)).toBe("unknown");
  });
});

describe("errorCodeFrom", () => {
  it("names a network failure instead of calling it http_0", () => {
    expect(errorCodeFrom(undefined, 0)).toBe("network_error");
  });

  it("takes the last segment of an RFC-7807 type", () => {
    expect(errorCodeFrom("https://agripulse.cloud/problems/tenant-required", 403)).toBe(
      "tenant-required",
    );
  });

  it("falls back to the status when the body is not problem+json", () => {
    expect(errorCodeFrom("about:blank", 502)).toBe("http_502");
  });
});
