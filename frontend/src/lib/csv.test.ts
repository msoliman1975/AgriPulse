import { describe, expect, it } from "vitest";

import { toCsv } from "./csv";

describe("toCsv", () => {
  it("joins headers and rows with CRLF", () => {
    const csv = toCsv(["a", "b"], [
      [1, 2],
      [3, 4],
    ]);
    expect(csv).toBe("a,b\r\n1,2\r\n3,4");
  });

  it("quotes cells containing commas, quotes, or newlines", () => {
    const csv = toCsv(["x"], [["a,b"], ['has "quote"'], ["line\nbreak"]]);
    expect(csv).toBe('x\r\n"a,b"\r\n"has ""quote"""\r\n"line\nbreak"');
  });

  it("renders null and undefined as empty cells", () => {
    expect(toCsv(["a", "b"], [[null, undefined]])).toBe("a,b\r\n,");
  });

  it("stringifies numbers and booleans", () => {
    expect(toCsv(["n", "b"], [[0, false]])).toBe("n,b\r\n0,false");
  });
});
