import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { enUS } from "date-fns/locale";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ActionItem, ActionItemMembersResponse } from "@/api/actionCenter";
import { setupTestI18n } from "@/i18n/testing";

import { ItemRow } from "./ItemRow";

const listMembers = vi.fn<() => Promise<ActionItemMembersResponse>>();

vi.mock("@/api/actionCenter", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/actionCenter")>()),
  listActionItemMembers: () => listMembers(),
}));

const CELL = {
  cell_id: "c1",
  row: 2,
  col: 3,
  ordinal: 5,
  total: 36,
  lat: 30.04421,
  lon: 31.23578,
  area_m2: "400",
};

function item(over: Partial<ActionItem> = {}): ActionItem {
  return {
    id: "i1",
    kind: "recommendation",
    status: "needs_action",
    native_status: "open",
    farm_id: "f1",
    block_id: "b1",
    block_code: "B-01",
    block_name: "North",
    cell: null,
    action_type: "scout",
    severity: "warning",
    title_en: "Aphid pressure rising",
    title_ar: null,
    detail_en: null,
    detail_ar: null,
    tree_code: "mango_pest_v1",
    tree_version: 2,
    confidence: "0.82",
    created_at: "2026-08-12T06:00:00Z",
    valid_until: null,
    due_bucket: "week",
    due_date: null,
    responsible_membership_id: null,
    assigned_membership_id: null,
    activity_id: null,
    scheduled_date: null,
    why: "ndvi < -0.15",
    reasoning: {},
    aggregation: { is_group: false, member_count: 0, previous_member_count: 0, trend: "unknown" },
    recurrence: {
      state: "new",
      occurrence_count: 1,
      day_streak: 1,
      first_seen_at: "2026-08-12T06:00:00Z",
      last_seen_at: "2026-08-12T06:00:00Z",
    },
    ...over,
  };
}

function renderRow(value: ActionItem) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ItemRow
          item={value}
          isAr={false}
          dateLocale={enUS}
          selected={false}
          expanded={false}
          canDispatch
          onToggleSelect={() => {}}
          onToggleExpand={() => {}}
          onDispatch={() => {}}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ItemRow — aggregation and recurrence", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    listMembers.mockReset();
  });

  it("says nothing extra about an ordinary single-cell item", () => {
    renderRow(item({ cell: CELL }));
    expect(screen.queryByText(/zones/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/recurring/i)).not.toBeInTheDocument();
    // The coordinate is still the lead for a single cell — a group is the only
    // thing that trades it for an extent.
    expect(screen.getByText("30.04421, 31.23578")).toBeInTheDocument();
  });

  it("leads a group with its extent instead of a coordinate it does not have", () => {
    renderRow(
      item({
        aggregation: {
          is_group: true,
          member_count: 12,
          previous_member_count: 12,
          trend: "steady",
        },
      }),
    );
    expect(screen.getByText("12 zones")).toBeInTheDocument();
    expect(screen.getByText("12 zones in block B-01")).toBeInTheDocument();
    // "Whole block" would be a lie: the finding is in some cells, not all.
    expect(screen.queryByText(/whole block/i)).not.toBeInTheDocument();
  });

  /**
   * The specific regression this guards: `recurrence.state` is a union
   * mirrored from the backend, and an unmatched member renders the raw i18n
   * key. That has shipped to prod from this codebase before.
   */
  it.each([
    ["recurring", 3, "Recurring · 3 days"],
    ["persistent", 6, "Not acted on · 6 days"],
  ] as const)("badges %s without leaking a translation key", (state, streak, expected) => {
    renderRow(
      item({
        recurrence: {
          state,
          occurrence_count: streak,
          day_streak: streak,
          first_seen_at: "2026-08-06T06:00:00Z",
          last_seen_at: "2026-08-12T06:00:00Z",
        },
      }),
    );
    const badge = screen.getByText(expected);
    expect(badge).toBeInTheDocument();
    expect(badge.textContent).not.toContain("recurrence.");
  });

  /**
   * Aggregation's own failure mode. With only a current count on the card, a
   * 12-cell finding and a 20-cell one render identically — the grouping would
   * be hiding the deterioration it was built to summarise.
   */
  it("says which way a group is moving, and what it moved from", () => {
    renderRow(
      item({
        aggregation: {
          is_group: true,
          member_count: 20,
          previous_member_count: 12,
          trend: "spreading",
        },
      }),
    );
    expect(screen.getByText("20 zones ▲ from 12")).toBeInTheDocument();
  });

  it("shows a receding group as receding, not as a bare count", () => {
    renderRow(
      item({
        aggregation: {
          is_group: true,
          member_count: 4,
          previous_member_count: 14,
          trend: "receding",
        },
      }),
    );
    expect(screen.getByText("4 zones ▼ from 14")).toBeInTheDocument();
  });

  it("stays a plain count when there is no yesterday to compare against", () => {
    renderRow(
      item({
        aggregation: {
          is_group: true,
          member_count: 7,
          previous_member_count: 0,
          trend: "unknown",
        },
      }),
    );
    // `unknown` must not be drawn as steadiness — it is the absence of a
    // baseline, and an arrow here would be an invented comparison.
    expect(screen.getByText("7 zones")).toBeInTheDocument();
    expect(screen.queryByText(/▲|▼/)).not.toBeInTheDocument();
  });

  it("shows when a recurring item last fired, not only when it was raised", () => {
    renderRow(
      item({
        recurrence: {
          state: "recurring",
          occurrence_count: 4,
          day_streak: 4,
          first_seen_at: "2026-08-06T06:00:00Z",
          last_seen_at: "2026-08-12T06:00:00Z",
        },
      }),
    );
    // Without this the row reads as stale — it fired again this morning, and
    // that is the fact that decides whether it still needs doing.
    expect(screen.getByText(/last seen/i)).toBeInTheDocument();
  });

  it("does not fetch a group's cells until the row is expanded", async () => {
    listMembers.mockResolvedValue({
      item_id: "i1",
      kind: "recommendation",
      total: 2,
      active: 1,
      members: [
        {
          id: "m1",
          cell: CELL,
          severity: "warning",
          native_status: "open",
          text_en: "Aphids here",
          text_ar: null,
          created_at: "2026-08-12T06:00:00Z",
          last_seen_at: "2026-08-12T06:00:00Z",
          cleared_at: null,
          occurrence_count: 3,
          day_streak: 3,
        },
        {
          id: "m2",
          cell: { ...CELL, cell_id: "c2", row: 4, col: 1 },
          severity: "warning",
          native_status: "open",
          text_en: null,
          text_ar: null,
          created_at: "2026-08-10T06:00:00Z",
          last_seen_at: "2026-08-11T06:00:00Z",
          cleared_at: "2026-08-12T06:00:00Z",
          occurrence_count: 2,
          day_streak: 1,
        },
      ],
    });

    const grouped = item({
      aggregation: { is_group: true, member_count: 1, previous_member_count: 1, trend: "steady" },
    });
    const { rerender } = renderRow(grouped);
    // A farm-wide queue holds hundreds of groups; eagerly loading every
    // membership would swap the request-per-row this feature removes for a
    // different one.
    expect(listMembers).not.toHaveBeenCalled();

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    rerender(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <ItemRow
            item={grouped}
            isAr={false}
            dateLocale={enUS}
            selected={false}
            expanded
            canDispatch
            onToggleSelect={() => {}}
            onToggleExpand={() => {}}
            onDispatch={() => {}}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Zones (1 of 2 still firing)")).toBeInTheDocument();
    expect(screen.getByText("R2C3")).toBeInTheDocument();
    // A cell that stopped is listed, not dropped: a receding outbreak and one
    // that never spread look identical otherwise.
    expect(screen.getByText("Stopped")).toBeInTheDocument();
  });

  it("keeps the dispatch button on a group — the group is the actionable unit", async () => {
    const onDispatch = vi.fn();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <ItemRow
            item={item({
              aggregation: {
                is_group: true,
                member_count: 9,
                previous_member_count: 9,
                trend: "steady",
              },
            })}
            isAr={false}
            dateLocale={enUS}
            selected={false}
            expanded={false}
            canDispatch
            onToggleSelect={() => {}}
            onToggleExpand={() => {}}
            onDispatch={onDispatch}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Dispatch" }));
    expect(onDispatch).toHaveBeenCalledOnce();
  });
});
