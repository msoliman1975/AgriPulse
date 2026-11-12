import { describe, expect, it } from "vitest";

import { scopeAtPath, withPath, withoutPath } from "./signalScope";

describe("scopeAtPath", () => {
  it("treats an unscoped row as every crop", () => {
    expect(scopeAtPath([], "date_palm.medjool")).toBe("all");
  });

  it("tells a row scoped here from one inherited from a crop above", () => {
    expect(scopeAtPath(["date_palm.medjool"], "date_palm.medjool")).toBe("here");
    expect(scopeAtPath(["date_palm"], "date_palm.medjool")).toBe("inherited");
  });

  it("does not apply a variety's row to its crop, or match on a bare prefix", () => {
    expect(scopeAtPath(["date_palm.medjool"], "date_palm")).toBe("none");
    expect(scopeAtPath(["date_palm"], "date_palmyra")).toBe("none");
    expect(scopeAtPath(["mango"], "date_palm.medjool")).toBe("none");
  });
});

describe("withPath / withoutPath", () => {
  it("adds once and keeps the list sorted", () => {
    expect(withPath(["mango"], "date_palm.medjool")).toEqual(["date_palm.medjool", "mango"]);
    expect(withPath(["mango"], "mango")).toEqual(["mango"]);
  });

  it("removes only the named path", () => {
    expect(withoutPath(["date_palm.medjool", "mango"], "mango")).toEqual(["date_palm.medjool"]);
  });
});
