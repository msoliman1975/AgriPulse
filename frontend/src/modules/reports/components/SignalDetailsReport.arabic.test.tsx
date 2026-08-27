/**
 * The Arabic signal details report must render Arabic, not just receive it.
 *
 * This asserts the rendered text, not the payload. The Arabic-names work
 * shipped once with a correct payload and an English page behind 1656 green
 * tests, because every assertion was written one layer below the broken one.
 * A test for a presentation fix has to read what is on screen.
 *
 * The categorical value is the case that matters most: the stored reading is
 * always the English code, so `emitter_blocked` is what the API sends and
 * `نقاط تنقيط مسدودة` is what a person must read.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SignalDetailsReportResponse } from "@/api/reports";
import { setupTestI18n } from "@/i18n/testing";

import { SignalDetailsReport } from "./SignalDetailsReport";

const getSignalDetailsReport = vi.fn();
vi.mock("@/api/reports", async () => {
  const actual = await vi.importActual<typeof import("@/api/reports")>("@/api/reports");
  return {
    ...actual,
    getSignalDetailsReport: () => getSignalDetailsReport(),
    getReportCustomFields: () => Promise.resolve({ fields: [] }),
  };
});

vi.mock("@/api/blocks", async () => {
  const actual = await vi.importActual<typeof import("@/api/blocks")>("@/api/blocks");
  return { ...actual, listBlocks: () => Promise.resolve({ items: [], next_cursor: null }) };
});

const FARM = "11111111-1111-1111-1111-111111111111";

const RESPONSE: SignalDetailsReportResponse = {
  farm_id: FARM,
  farm_name: "Bashier Elkhier",
  farm_name_ar: "بشاير الخير",
  period: { since: "2026-08-01T00:00:00Z", until: "2026-08-26T00:00:00Z" },
  filters: {
    signal_codes: [],
    block_ids: [],
    categorical_values: [],
    min_value: null,
    max_value: null,
    recorded_by: null,
    location_mode: null,
    with_notes_only: false,
    with_attachment_only: false,
  },
  rows: [
    {
      observation_id: "22222222-2222-2222-2222-222222222222",
      observed_at: "2026-08-20T07:30:00Z",
      recorded_at: "2026-08-20T07:31:00Z",
      signal_code: "irrigation_fault",
      signal_name: "Irrigation fault",
      signal_name_ar: "عطل في الري",
      value_kind: "categorical",
      unit: null,
      unit_ar: null,
      categorical_values: ["none", "emitter_blocked", "line_leak"],
      categorical_values_ar: ["لا يوجد", "نقاط تنقيط مسدودة", "تسريب في الخط"],
      value_numeric: null,
      value_categorical: "emitter_blocked",
      value_event: null,
      value_boolean: null,
      block_id: "33333333-3333-3333-3333-333333333333",
      block_name: "North Block",
      block_name_ar: "القطعة الشمالية",
      crop_path: null,
      notes: null,
      recorded_by: "44444444-4444-4444-4444-444444444444",
      recorded_by_name: "Ahmed Fathy",
      recorded_by_name_ar: "أحمد فتحي",
      location_mode: "block",
      has_attachment: false,
      template_observation_id: null,
      import_batch_id: null,
    },
  ],
  stats: [
    {
      signal_code: "irrigation_fault",
      signal_name: "Irrigation fault",
      signal_name_ar: "عطل في الري",
      value_kind: "categorical",
      unit: null,
      observation_count: 1,
      block_count: 1,
      recorder_count: 1,
      first_observed_at: "2026-08-20T07:30:00Z",
      last_observed_at: "2026-08-20T07:30:00Z",
      min_value: null,
      mean_value: null,
      max_value: null,
      categories: [{ value: "emitter_blocked", count: 1 }],
    },
  ],
  summary: {
    observation_count: 1,
    signal_count: 1,
    block_count: 1,
    recorder_count: 1,
    truncated: false,
  },
};

function renderReport() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SignalDetailsReport
        farmId={FARM}
        since="2026-08-01T00:00:00Z"
        until="2026-08-26T00:00:00Z"
      />
    </QueryClientProvider>,
  );
}

describe("SignalDetailsReport in Arabic", () => {
  beforeEach(() => {
    getSignalDetailsReport.mockReset();
    getSignalDetailsReport.mockResolvedValue(RESPONSE);
  });

  it("renders the Arabic signal name, block name, recorder and categorical label", async () => {
    await setupTestI18n("ar");
    renderReport();

    await waitFor(() => {
      expect(screen.getAllByText("عطل في الري").length).toBeGreaterThan(0);
    });
    expect(screen.getByText("القطعة الشمالية")).toBeInTheDocument();
    expect(screen.getByText("أحمد فتحي")).toBeInTheDocument();
    // The stored reading is the English code; the page must show the label.
    expect(screen.getByText("نقاط تنقيط مسدودة")).toBeInTheDocument();
    expect(screen.queryByText("emitter_blocked")).not.toBeInTheDocument();
    expect(screen.getByText("بشاير الخير")).toBeInTheDocument();
  });

  it("renders the English name when the page is in English", async () => {
    await setupTestI18n("en");
    renderReport();

    await waitFor(() => {
      expect(screen.getAllByText("Irrigation fault").length).toBeGreaterThan(0);
    });
    expect(screen.getByText("North Block")).toBeInTheDocument();
    expect(screen.getByText("Ahmed Fathy")).toBeInTheDocument();
    expect(screen.getByText("emitter_blocked")).toBeInTheDocument();
    expect(screen.queryByText("عطل في الري")).not.toBeInTheDocument();
  });
});
