import { describe, expect, it } from "vitest";

import type { BlockCropAssignment } from "@/api/cropAssignments";

import {
  currentAssignment,
  findConflict,
  gaps,
  humanDuration,
  isActiveOn,
  openAssignmentToClose,
  overlaps,
  stateOn,
} from "./assignmentValidity";

/** Mirrors `backend/.../validity.py`; a disagreement shows the user a panel the
 *  server then rejects, or hides a conflict it will refuse. */
function a(id: string, from: string, to: string | null, crop = "mango"): BlockCropAssignment {
  return { id, effective_from: from, effective_to: to, crop_path: crop } as BlockCropAssignment;
}

describe("half-open containment", () => {
  it("includes the start and excludes the end", () => {
    const row = a("1", "2026-01-01", "2026-04-01");
    expect(isActiveOn(row, "2026-01-01")).toBe(true);
    expect(isActiveOn(row, "2026-03-31")).toBe(true);
    // 1 Apr belongs to whatever starts next — inclusive `to` would make the
    // handover day overlap and the panel would refuse an ordinary changeover.
    expect(isActiveOn(row, "2026-04-01")).toBe(false);
  });

  it("treats a null end as ongoing", () => {
    expect(isActiveOn(a("1", "2019-03-04", null), "2026-08-06")).toBe(true);
  });
});

describe("currentAssignment", () => {
  it("picks the range containing today, not the newest row", () => {
    const finished = a("1", "2025-11-01", "2026-03-10", "tomato");
    const ongoing = a("2", "2026-03-10", null, "potato");
    expect(currentAssignment([finished, ongoing], "2026-08-06")?.id).toBe("2");
    expect(currentAssignment([finished, ongoing], "2026-03-09")?.id).toBe("1");
  });

  it("returns null once the last assignment has ended", () => {
    expect(currentAssignment([a("1", "2025-11-01", "2026-03-10")], "2026-08-06")).toBeNull();
  });

  it("ignores a future assignment", () => {
    const future = a("1", "2026-11-15", "2027-04-30", "wheat");
    expect(currentAssignment([future], "2026-08-06")).toBeNull();
    expect(stateOn(future, "2026-08-06")).toBe("scheduled");
  });
});

describe("overlap", () => {
  it("allows touching ranges", () => {
    expect(overlaps("2026-01-01", "2026-03-01", "2026-03-01", null)).toBe(false);
  });
  it("catches a single shared day", () => {
    expect(overlaps("2026-01-01", "2026-03-02", "2026-03-01", null)).toBe(true);
  });
  it("two open-ended ranges always overlap", () => {
    expect(overlaps("2019-01-01", null, "2026-01-01", null)).toBe(true);
  });
});

describe("auto-close", () => {
  it("selects the open assignment", () => {
    const rows = [a("1", "2018-11-05", "2019-03-04", "potato"), a("2", "2019-03-04", null)];
    expect(openAssignmentToClose(rows, "2026-08-06")?.id).toBe("2");
  });

  it("never touches a bounded assignment", () => {
    // The user set that end date deliberately; rewriting it is data loss.
    expect(openAssignmentToClose([a("1", "2025-11-01", "2026-03-10")], "2026-08-06")).toBeNull();
  });

  it("ignores an open assignment that starts later than the new one", () => {
    expect(openAssignmentToClose([a("1", "2027-01-01", null)], "2026-08-06")).toBeNull();
  });
});

describe("findConflict", () => {
  it("exempts the assignment being auto-closed", () => {
    const open = a("1", "2019-03-04", null);
    expect(findConflict([open], "2026-08-06", null, "1")).toBeNull();
    // ...but flags it when nothing is being closed.
    expect(findConflict([open], "2026-08-06", null, null)?.id).toBe("1");
  });

  it("names a historical collision", () => {
    const past = a("1", "2017-11-12", "2018-03-20", "potato.diamant");
    expect(findConflict([past], "2018-01-01", "2018-02-01", null)?.crop_path).toBe(
      "potato.diamant",
    );
  });
});

describe("gaps", () => {
  it("finds a fallow stretch between assignments", () => {
    const rows = [a("1", "2024-11-08", "2025-04-11"), a("2", "2025-10-31", null)];
    expect(gaps(rows)).toEqual([{ from: "2025-04-11", to: "2025-10-31" }]);
  });
  it("reports none when assignments touch", () => {
    expect(gaps([a("1", "2025-11-01", "2026-03-10"), a("2", "2026-03-10", null)])).toEqual([]);
  });
});

describe("humanDuration", () => {
  it("reads naturally at each scale", () => {
    expect(humanDuration("2026-01-01", "2026-01-13")).toBe("12d");
    expect(humanDuration("2026-01-01", "2026-05-01")).toBe("4m");
    expect(humanDuration("2019-03-04", "2026-08-06")).toBe("7y 5m");
  });
});
