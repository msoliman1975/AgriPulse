import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { HarvestLot } from "@/api/harvest";

const listHarvestLots = vi.fn();
const createHarvestLot = vi.fn();
const deleteHarvestLot = vi.fn();
vi.mock("@/api/harvest", () => ({
  listHarvestLots: (...a: unknown[]) => listHarvestLots(...a),
  createHarvestLot: (...a: unknown[]) => createHarvestLot(...a),
  updateHarvestLot: vi.fn(),
  deleteHarvestLot: (...a: unknown[]) => deleteHarvestLot(...a),
}));

let canManage = true;
vi.mock("@/rbac/useCapability", () => ({
  useCapability: (cap: string) => (cap === "harvest.manage" ? canManage : true),
}));

import { HarvestCard } from "./HarvestCard";

const lot = (over: Partial<HarvestLot>): HarvestLot => ({
  id: "l1",
  farm_id: "f1",
  block_id: "b1",
  block_crop_id: null,
  season_label: "2026",
  pick_no: 1,
  label: null,
  label_ar: null,
  harvested_on: "2026-10-01",
  weight_kg: "1000.00",
  price_per_kg: "12.5000",
  currency: "EGP",
  revenue: "12500.00",
  notes_internal: null,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
  ...over,
});

function wrap(ui: ReactNode): ReactNode {
  return <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>;
}

describe("HarvestCard", () => {
  beforeEach(() => {
    canManage = true;
    listHarvestLots.mockReset();
    createHarvestLot.mockReset().mockResolvedValue(lot({ id: "l3" }));
    deleteHarvestLot.mockReset().mockResolvedValue(undefined);
  });

  it("lists picks with totals", async () => {
    listHarvestLots.mockResolvedValue([
      lot({ id: "l2", pick_no: 2, weight_kg: "500.00", price_per_kg: null, revenue: null }),
      lot({}),
    ]);
    render(wrap(<HarvestCard blockId="b1" farmId="f1" />));
    expect(await screen.findAllByText("harvest.pickN")).toHaveLength(2);
    await waitFor(() => expect(screen.getAllByRole("row")).toHaveLength(3));
    expect(screen.getByText("harvest.totals")).toBeInTheDocument();
  });

  it("records a pick from the form", async () => {
    listHarvestLots.mockResolvedValue([]);
    render(wrap(<HarvestCard blockId="b1" farmId="f1" />));
    expect(await screen.findByText("harvest.empty")).toBeInTheDocument();
    fireEvent.click(screen.getByText("harvest.add"));
    fireEvent.change(screen.getByLabelText("harvest.date"), { target: { value: "2026-10-05" } });
    fireEvent.change(screen.getByLabelText("harvest.weight"), { target: { value: "800" } });
    fireEvent.click(screen.getByText("harvest.save"));
    await waitFor(() =>
      expect(createHarvestLot).toHaveBeenCalledWith("b1", {
        harvested_on: "2026-10-05",
        weight_kg: "800",
        price_per_kg: null,
        label: null,
        label_ar: null,
        notes_internal: null,
      }),
    );
  });

  it("refuses a pick without a weight", async () => {
    listHarvestLots.mockResolvedValue([]);
    render(wrap(<HarvestCard blockId="b1" farmId="f1" />));
    fireEvent.click(await screen.findByText("harvest.add"));
    fireEvent.change(screen.getByLabelText("harvest.date"), { target: { value: "2026-10-05" } });
    fireEvent.click(screen.getByText("harvest.save"));
    expect(screen.getByRole("alert")).toHaveTextContent("harvest.needDateWeight");
    expect(createHarvestLot).not.toHaveBeenCalled();
  });

  it("asks before removing a pick", async () => {
    listHarvestLots.mockResolvedValue([lot({})]);
    render(wrap(<HarvestCard blockId="b1" farmId="f1" />));
    fireEvent.click(await screen.findByText("harvest.delete"));
    fireEvent.click(screen.getByText("harvest.confirmDelete"));
    await waitFor(() => expect(deleteHarvestLot).toHaveBeenCalledWith("l1"));
  });

  it("is read-only without harvest.manage", async () => {
    canManage = false;
    listHarvestLots.mockResolvedValue([lot({})]);
    render(wrap(<HarvestCard blockId="b1" farmId="f1" />));
    await screen.findByText("harvest.pickN");
    expect(screen.queryByText("harvest.add")).not.toBeInTheDocument();
    expect(screen.queryByText("harvest.edit")).not.toBeInTheDocument();
  });
});
