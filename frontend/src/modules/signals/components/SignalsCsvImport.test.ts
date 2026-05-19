import { AxiosError, AxiosHeaders, type AxiosResponse } from "axios";
import { describe, expect, it } from "vitest";

import { _parseError } from "./SignalsCsvImport";

function _axiosError(status: number, body: unknown): AxiosError {
  const response = {
    status,
    statusText: "X",
    data: body,
    headers: {},
    config: { headers: new AxiosHeaders() },
  } as AxiosResponse;
  return new AxiosError("X", "ERR_BAD_REQUEST", undefined, undefined, response);
}

describe("_parseError", () => {
  it("unwraps CsvImportFailedError row list", () => {
    const out = _parseError(
      _axiosError(422, {
        title: "Signal CSV import rejected",
        detail: "2 row(s) failed validation; no observations were inserted.",
        extras: {
          errors: [
            { row_number: 2, field: "value_numeric", message: "Could not parse '6.x'." },
            { row_number: 3, field: null, message: "No value column populated." },
          ],
        },
      }),
    );
    expect(out.rowErrors).toHaveLength(2);
    expect(out.rowErrors[0].row_number).toBe(2);
    expect(out.message).toMatch(/2 row/);
  });

  it("unwraps CsvImportTooLargeError byte caps", () => {
    const out = _parseError(
      _axiosError(413, {
        title: "Signal CSV import too large",
        detail: "Uploaded file exceeds the limit.",
        extras: { size_bytes: 6_000_000, limit_bytes: 5_242_880 },
      }),
    );
    expect(out.rowErrors).toEqual([]);
    expect(out.message).toMatch(/too large/i);
    expect(out.message).toMatch(/5242880/);
  });

  it("falls back to detail when no extras present", () => {
    const out = _parseError(_axiosError(400, { title: "Bad request", detail: "Garbage body" }));
    expect(out.rowErrors).toEqual([]);
    expect(out.message).toBe("Garbage body");
  });

  it("handles non-axios errors", () => {
    const out = _parseError(new Error("Network down"));
    expect(out.rowErrors).toEqual([]);
    expect(out.message).toBe("Network down");
  });

  it("handles plain values", () => {
    const out = _parseError("oops");
    expect(out.message).toBe("Unknown error.");
  });
});
