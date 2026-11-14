// The board chip for an activity from an Agri Operation saved plan: its
// title, the Plan badge instead of the template badge, and the moved-date
// marker. A plain manual activity shows none of these.
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BoardActivity } from "@/api/plans";
import { setupTestI18n } from "@/i18n/testing";
import { ActivityChip } from "./ActivityChip";

vi.mock("@/hooks/useDateLocale", () => ({ useDateLocale: () => undefined }));

const base = {
  id: "a1",
  plan_id: "p1",
  farm_id: "f1",
  block_id: "b1",
  recommendation_id: null,
  activity_type: "spraying",
  scheduled_date: "2027-02-02",
  duration_days: 1,
  start_time: null,
  product_name: null,
  dosage: null,
  notes: null,
  status: "scheduled",
  completed_at: null,
  completed_by: null,
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
  resources: [],
} as unknown as BoardActivity;

describe("ActivityChip", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
  });

  it("marks saved-plan rows and moved dates", () => {
    render(
      <ActivityChip
        activity={{
          ...base,
          source: "template",
          title: "Spray against mango leafhopper",
          allocation_id: "alloc-1",
          date_overridden: true,
        }}
        onClick={() => undefined}
      />,
    );
    expect(screen.getByText("Spray against mango leafhopper")).toBeTruthy();
    expect(screen.getByText("Plan")).toBeTruthy();
    expect(screen.getByRole("img", { name: "Date moved from the plan" })).toBeTruthy();
  });

  it("shows nothing extra for a manual activity", () => {
    render(<ActivityChip activity={{ ...base, source: "manual" }} onClick={() => undefined} />);
    expect(screen.queryByText("Plan")).toBeNull();
    expect(screen.queryByRole("img", { name: "Date moved from the plan" })).toBeNull();
  });
});
