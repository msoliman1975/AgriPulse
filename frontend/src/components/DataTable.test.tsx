import { beforeAll, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { setupTestI18n } from "@/i18n/testing";

import { Button } from "./Button";
import { DataTable, RowActions, type Column } from "./DataTable";
import { EmptyState } from "./EmptyState";
import type { AsyncState } from "./asyncState";

interface Farm {
  id: string;
  code: string;
  name: string;
}

const FARMS: Farm[] = [
  { id: "f1", code: "BSH-01", name: "Bashayer" },
  { id: "f2", code: "AGR-01", name: "Agrosina" },
];

const COLUMNS: Column<Farm>[] = [
  { key: "code", header: "Code", cell: (f) => f.code },
  { key: "name", header: "Name", cell: (f) => f.name },
];

function renderTable(props: Partial<Parameters<typeof DataTable<Farm>>[0]> = {}) {
  return render(
    <MemoryRouter initialEntries={["/farms"]}>
      <Routes>
        <Route
          path="/farms"
          element={
            <DataTable<Farm>
              columns={COLUMNS}
              rowKey={(f) => f.id}
              rows={FARMS}
              empty={<EmptyState message="No farms yet." />}
              {...props}
            />
          }
        />
        <Route path="/farms/:farmId" element={<p>farm detail</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("DataTable", () => {
  beforeAll(async () => {
    await setupTestI18n("en");
  });

  // Decision 3B — the reason this component owns the async ladder instead of
  // sitting inside <AsyncBoundary>.
  it("keeps column headers mounted while rows are loading", () => {
    const state: AsyncState<Farm[]> = { status: "loading" };
    renderTable({ rows: undefined, state });

    expect(screen.getByRole("columnheader", { name: "Code" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Name" })).toBeInTheDocument();
    expect(screen.queryByText("Bashayer")).not.toBeInTheDocument();
  });

  // Decision 1C — both halves.
  it("renders a real link in the identity cell", () => {
    renderTable({ rowHref: (f) => `/farms/${f.id}` });

    const link = screen.getByRole("link", { name: "BSH-01" });
    expect(link).toHaveAttribute("href", "/farms/f1");
  });

  it("navigates when the row body is clicked", async () => {
    renderTable({ rowHref: (f) => `/farms/${f.id}` });

    await userEvent.click(screen.getByText("Bashayer"));
    expect(screen.getByText("farm detail")).toBeInTheDocument();
  });

  // The one real cost of decision 1C, handled in the primitive so no page can
  // forget it: "Archive" must not also navigate.
  it("does not navigate when a control inside RowActions is clicked", async () => {
    const onArchive = vi.fn();
    renderTable({
      rowHref: (f) => `/farms/${f.id}`,
      columns: [
        ...COLUMNS,
        {
          key: "actions",
          header: "Actions",
          align: "end",
          cell: () => (
            <RowActions>
              <Button size="sm" variant="danger" onClick={onArchive}>
                Archive
              </Button>
            </RowActions>
          ),
        },
      ],
    });

    await userEvent.click(screen.getAllByRole("button", { name: "Archive" })[0]);
    expect(onArchive).toHaveBeenCalledOnce();
    expect(screen.queryByText("farm detail")).not.toBeInTheDocument();
  });

  it("renders the empty state inside the table body", () => {
    renderTable({ rows: [], state: { status: "success", data: [] } });
    expect(screen.getByText("No farms yet.")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Code" })).toBeInTheDocument();
  });

  it("distinguishes no-results from empty when filtered", () => {
    renderTable({
      rows: undefined,
      state: { status: "success", data: [] },
      filtered: true,
      noResults: <EmptyState message="No farms match." />,
    });
    expect(screen.getByText("No farms match.")).toBeInTheDocument();
  });

  it("surfaces a retry control on error", async () => {
    const retry = vi.fn();
    renderTable({
      rows: undefined,
      state: { status: "error", error: new Error("nope"), retry },
    });

    expect(screen.getByRole("alert")).toHaveTextContent("nope");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalledOnce();
  });
});
