import { describe, expect, it } from "vitest";

import { captureDateUrl, parseCaptureDate } from "./imageryDate";

describe("Esri capture date", () => {
  it("reads SRC_DATE as an ISO day", () => {
    const body = { results: [{ attributes: { SRC_DATE: "20200419", NICE_DESC: "Vantor" } }] };
    expect(parseCaptureDate(body)).toBe("2020-04-19");
  });

  it("is null when the service has no answer", () => {
    expect(parseCaptureDate({ results: [] })).toBeNull();
    expect(parseCaptureDate(null)).toBeNull();
  });

  it("asks for the topmost capture under the holding", () => {
    const url = new URL(captureDateUrl(32.6368, 30.0804));
    expect(url.searchParams.get("geometry")).toBe("32.6368,30.0804");
    expect(url.searchParams.get("layers")).toMatch(/^top:/);
  });
});
