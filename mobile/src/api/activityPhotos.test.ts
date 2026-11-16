import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/auth/session", () => ({
  validAccessToken: vi.fn(async () => "tok"),
}));

import { completeActivity, initActivityPhotoUpload } from "./client";

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset().mockImplementation(async () =>
    new Response(
      JSON.stringify({
        id: "a1",
        status: "completed",
        s3_key: "tenants/t/farms/f/activity-photos/a1/p.jpg",
        upload_url: "https://s3.test/put",
        upload_headers: { "Content-Type": "image/jpeg" },
        expires_at: "2030-01-01T00:00:00Z",
      }),
      { status: 200 },
    ),
  );
  vi.stubGlobal("fetch", fetchMock);
});

function sentBody(): unknown {
  const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  return JSON.parse(String(init.body));
}

describe("activity photos on the complete call", () => {
  it("sends the keys with complete", async () => {
    await completeActivity("a1", "complete", ["k1", "k2"]);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/activities\/a1$/);
    expect(init.method).toBe("PATCH");
    expect(sentBody()).toEqual({
      state: "complete",
      attachment_s3_keys: ["k1", "k2"],
    });
  });

  it("sends only the verb without photos, and never photos with skip", async () => {
    await completeActivity("a1", "complete");
    expect(sentBody()).toEqual({ state: "complete" });
    fetchMock.mockClear();
    await completeActivity("a1", "skip", ["k1"]);
    expect(sentBody()).toEqual({ state: "skip" });
  });

  it("maps the init response onto the shared upload shape", async () => {
    const upload = await initActivityPhotoUpload("a1", {
      content_type: "image/jpeg",
      content_length: 1234,
    });
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/activities\/a1\/photos\/init$/);
    expect(sentBody()).toEqual({
      content_type: "image/jpeg",
      content_length: 1234,
    });
    expect(upload.attachment_s3_key).toBe(
      "tenants/t/farms/f/activity-photos/a1/p.jpg",
    );
    expect(upload.upload_url).toBe("https://s3.test/put");
  });
});
