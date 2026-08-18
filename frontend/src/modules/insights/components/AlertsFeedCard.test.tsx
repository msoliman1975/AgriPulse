import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Alert } from "@/api/alerts";
import { listAlerts } from "@/api/alerts";
import { setupTestI18n } from "@/i18n/testing";

import { AlertsFeedCard } from "./AlertsFeedCard";

const FARM_ID = "11111111-1111-1111-1111-111111111111";

function alert(id: string, blockId: string): Alert {
  return {
    id,
    block_id: blockId,
    cell_id: null,
    cell_row: null,
    cell_col: null,
    rule_code: "NDVI_DROP",
    severity: "warning",
    status: "open",
    diagnosis_en: `diagnosis ${id}`,
    diagnosis_ar: null,
    prescription_en: null,
    prescription_ar: null,
    prescription_activity_id: null,
    signal_snapshot: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
    acknowledged_at: null,
    acknowledged_by: null,
    resolved_at: null,
    resolved_by: null,
    snoozed_until: null,
    is_group: false,
    member_count: 0,
    occurrence_count: 1,
    day_streak: 1,
    first_seen_at: null,
    last_seen_at: null,
  };
}

vi.mock("@/api/alerts", async () => {
  const actual = await vi.importActual<typeof import("@/api/alerts")>("@/api/alerts");
  return { ...actual, listAlerts: vi.fn(() => Promise.resolve([])) };
});

const listAlertsMock = vi.mocked(listAlerts);

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AlertsFeedCard farmId={FARM_ID} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AlertsFeedCard", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    listAlertsMock.mockClear();
    listAlertsMock.mockResolvedValue([]);
  });

  // Regression: an unscoped /v1/alerts call is tenant-wide, so the feed
  // listed other farms' alerts and their Resolve button pointed at a lane
  // this farm's board does not have.
  it("scopes the alert list to the farm", async () => {
    renderCard();
    await waitFor(() => expect(listAlertsMock).toHaveBeenCalled());
    for (const [params] of listAlertsMock.mock.calls) {
      expect(params).toMatchObject({ farm_id: FARM_ID, status: "open" });
    }
  });

  it("renders the alerts the farm-scoped query returned", async () => {
    listAlertsMock.mockResolvedValue([alert("a1", "b1"), alert("a2", "b2")]);
    renderCard();
    expect(await screen.findByText("diagnosis a1")).toBeInTheDocument();
    expect(screen.getByText("diagnosis a2")).toBeInTheDocument();
  });

  it("shows the all-clear copy when the farm has no open alerts", async () => {
    renderCard();
    expect(
      await screen.findByText("All clear — nothing needs your attention."),
    ).toBeInTheDocument();
  });
});
