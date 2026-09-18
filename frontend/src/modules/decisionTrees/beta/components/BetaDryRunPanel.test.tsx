/**
 * The dry run table, against a body the server really sent.
 *
 * The panel read `finding_set`, `matched_rule_codes` and `unresolved`. The
 * server sends `identity`, `rule_code` and `composed`, and has never sent an
 * unresolved list, so the first cell took the page down with "Cannot read
 * properties of undefined (reading 'length')". Every test passed, because the
 * only other place this shape appears was a stub written from the same wrong
 * contract.
 *
 * So the fixture below is a copy of a live response — `POST
 * /v1/platform/decision-trees/beta/{id}/dry-run` on 2026-09-18 — and not a
 * hand-written one.
 */

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";
import type { AsyncState } from "@/components/asyncState";
import type { BetaCandidateBlock, BetaDryRunResponse } from "@/api/decisionTreesBeta";

import { BetaDryRunPanel } from "./BetaDryRunPanel";

const BLOCKS: AsyncState<BetaCandidateBlock[]> = {
  status: "success",
  data: [{ block_id: "b1", label: "Bashier / 009", label_ar: null }],
};

function response(overrides: Partial<BetaDryRunResponse> = {}): BetaDryRunResponse {
  return {
    tree_id: "01a0b34a-9ad6-7229-b044-30dfd2346827",
    code: "mango_unified_ags",
    block_id: "019f98f9-22de-7787-9c02-fcf1aae86b1e",
    scope: "cell",
    version_id: "01a0b34a-9ae0-7d6b-9d6c-6a2bbb4f7c66",
    cells_evaluated: 2,
    cells_carded: 1,
    cells_errored: 0,
    cells_composed: 0,
    cells: [
      {
        cell_id: "019fd304-6b6c-73f0-82fd-f4b41aee0ea6",
        cell_row: 110896,
        cell_col: 15508,
        identity: [],
        findings: [],
        severity: null,
        status: null,
        action_type: null,
        text_en: null,
        text_ar: null,
        composed: false,
        rule_code: null,
        stopped_at: "n_stop",
        error: null,
      },
      {
        cell_id: "019fd304-6b6c-73f0-82fd-f4b41aee0ea7",
        cell_row: 110897,
        cell_col: 15508,
        identity: ["dry", "vigour_low"],
        findings: [
          { code: "dry", severity: "warning", registered_by: ["n_reg_dry"] },
          { code: "vigour_low", severity: "warning", registered_by: ["n_reg_vigour"] },
        ],
        severity: "warning",
        status: "alert",
        action_type: "irrigate",
        text_en: "Water shortage is the cause.",
        text_ar: "السبب نقص ماء.",
        composed: false,
        rule_code: "vigour_low+dry",
        stopped_at: "n_stop",
        error: null,
      },
    ],
    ...overrides,
  };
}

function renderPanel(result: BetaDryRunResponse | null) {
  render(
    <BetaDryRunPanel
      blocks={BLOCKS}
      blockId="b1"
      onBlockChange={vi.fn()}
      onRun={vi.fn()}
      running={false}
      result={result}
      error={null}
      dirty={false}
    />,
  );
}

beforeEach(async () => {
  await setupTestI18n("en");
});

describe("<BetaDryRunPanel>", () => {
  it("draws a live response without falling over", () => {
    renderPanel(response());
    expect(screen.getByText("1 of 2 cells produce a card.")).toBeInTheDocument();
    expect(screen.getByText("dry")).toBeInTheDocument();
    expect(screen.getByText("vigour_low")).toBeInTheDocument();
  });

  it("says a cell with no findings has no card, rather than showing an empty row", () => {
    renderPanel(response());
    expect(screen.getAllByText("No card").length).toBe(1);
  });

  it("names the rule that matched", () => {
    renderPanel(response());
    expect(screen.getByText("vigour_low+dry")).toBeInTheDocument();
  });

  it("marks a composed card as composed", () => {
    const body = response();
    body.cells[1].composed = true;
    body.cells[1].rule_code = null;
    renderPanel(body);
    expect(screen.getByText("Composed")).toBeInTheDocument();
  });

  it("counts the cells that errored, so they never read as healthy", () => {
    renderPanel(response({ cells_errored: 3 }));
    expect(screen.getByText("3 cells errored.")).toBeInTheDocument();
  });

  it("says nothing about errors when there are none", () => {
    renderPanel(response());
    expect(screen.queryByText(/errored/)).toBeNull();
  });

  it("shows a block with no cells as an answer, not as a failure", () => {
    renderPanel(response({ cells: [], cells_evaluated: 0, cells_carded: 0 }));
    expect(
      screen.getByText("This block has no grid, so there are no cells to fold."),
    ).toBeInTheDocument();
  });
});
