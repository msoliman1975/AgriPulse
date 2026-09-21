/**
 * The walk explainer, against the shapes the server really sends.
 *
 * The steps here are a copy of what `POST .../dry-run/cell` answers with, and
 * the tree is laid out by the real `layoutBetaTree`, not by a stub. The dry
 * run panel took the whole page down once on a field written from a contract
 * the server never implemented, and every test passed because the only other
 * copy of that shape was a stub written from the same wrong contract.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { WalkExplainer } from "./WalkExplainer";
import { layoutBetaTree } from "../lib/betaLayout";
import { walkStepsFromDryRun } from "../lib/walkTrace";
import type { BetaTreeDoc } from "../lib/betaTree";

const DOC: BetaTreeDoc = {
  code: "tiny",
  name_en: "Tiny",
  root: "n_dry",
  registers: ["dry"],
  nodes: {
    n_dry: {
      label_en: "Is the soil dry?",
      condition: { tree: { op: "lt", left: { source: "index", index_code: "smi" }, right: 0.2 } },
      on_match: "n_reg",
      on_miss: "n_cold",
    },
    n_reg: {
      label_en: "Soil is dry",
      register: { code: "dry", severity: "warning" },
      next: "n_end",
    },
    n_cold: {
      label_en: "Frost risk?",
      condition: { tree: {} },
      on_match: "n_end",
      on_miss: "n_end",
    },
    n_end: { label_en: "Done", stop: true },
  },
};

const PATH = [
  {
    node_id: "n_dry",
    kind: "condition",
    matched: true,
    label_en: "Is the soil dry?",
    label_ar: null,
    values: { "indices.smi.mean": 0.1234567 },
    detail: null,
  },
  {
    node_id: "n_reg",
    kind: "register",
    matched: null,
    label_en: "Soil is dry",
    label_ar: null,
    values: {},
    detail: { code: "dry", severity: "warning", repeat: false, raised: false },
  },
  {
    node_id: "n_end",
    kind: "stop",
    matched: null,
    label_en: "Done",
    label_ar: null,
    values: {},
    detail: null,
  },
];

function renderExplainer(over: Partial<Parameters<typeof WalkExplainer>[0]> = {}) {
  return render(
    <WalkExplainer
      steps={walkStepsFromDryRun(PATH)}
      layout={layoutBetaTree(DOC)}
      identity={["dry"]}
      textEn="Soil moisture is low."
      {...over}
    />,
  );
}

describe("WalkExplainer", () => {
  beforeEach(async () => {
    await setupTestI18n();
  });

  it("lists every step of the walk in order", () => {
    renderExplainer();
    const steps = screen.getAllByRole("listitem");
    expect(steps).toHaveLength(3);
    expect(steps[0]).toHaveTextContent("Is the soil dry?");
    expect(steps[1]).toHaveTextContent("Soil is dry");
  });

  it("says yes or no on a condition, and names the finding on a register", () => {
    renderExplainer();
    const steps = screen.getAllByRole("listitem");
    expect(within(steps[0]).getByText("Yes")).toBeInTheDocument();
    expect(within(steps[1]).getByText("dry")).toBeInTheDocument();
  });

  it("dims every node the walk did not reach", () => {
    // The whole point of the read-only canvas. Marking the route without
    // dimming the rest reads as "here is the tree, and some of it is
    // highlighted", which on 74 nodes answers nothing.
    const { container } = renderExplainer();
    const dry = container.querySelector('[data-node-id="n_dry"]');
    const cold = container.querySelector('[data-node-id="n_cold"]');
    expect(dry).toHaveAttribute("data-off-path", "false");
    expect(cold).toHaveAttribute("data-off-path", "true");
  });

  it("shows the values a condition read, cut to three decimals", async () => {
    const user = userEvent.setup();
    renderExplainer();
    const steps = screen.getAllByRole("listitem");
    await user.click(within(steps[0]).getByRole("button"));
    expect(screen.getByText("indices.smi.mean")).toBeInTheDocument();
    expect(screen.getByText("0.123")).toBeInTheDocument();
  });

  it("names the combination rule that wrote the text", () => {
    renderExplainer({
      rule: {
        code: "dry_only",
        codes: ["dry"],
        text_en: "Water it now.",
        text_ar: null,
        status: "issue",
        action_type: "irrigate",
      },
    });
    expect(screen.getByText("Rule matched")).toBeInTheDocument();
    expect(screen.getByText("dry_only")).toBeInTheDocument();
    expect(screen.getByText("Water it now.")).toBeInTheDocument();
  });

  it("says a rule fired even when the rule carries no code", () => {
    // Every stored version saved before the compiler fix is in this state.
    renderExplainer({
      rule: {
        code: null,
        codes: ["dry"],
        text_en: "Water.",
        text_ar: null,
        status: null,
        action_type: null,
      },
    });
    expect(screen.getByText("Rule matched")).toBeInTheDocument();
    expect(screen.getByText("this rule has no code")).toBeInTheDocument();
  });

  it("lists the clauses composition joined", () => {
    renderExplainer({
      composedFrom: [
        { code: "dry", severity: "warning", clause_en: "soil moisture is low", clause_ar: null },
      ],
    });
    expect(screen.getByText("Composed")).toBeInTheDocument();
    expect(screen.getByText("soil moisture is low")).toBeInTheDocument();
  });

  it("calls a cell with no findings healthy rather than inventing a result", () => {
    renderExplainer({ identity: [], textEn: null });
    expect(screen.getByText(/registered no findings/i)).toBeInTheDocument();
  });

  it("names the node a failed walk died on, and folds nothing", () => {
    renderExplainer({
      steps: walkStepsFromDryRun(PATH.slice(0, 1)),
      identity: [],
      error: "unknown node id 'nowhere'",
    });
    expect(screen.getByText(/ended on node n_dry/i)).toBeInTheDocument();
    expect(screen.getByText("unknown node id 'nowhere'")).toBeInTheDocument();
    expect(screen.getByText(/never reached a stop node/i)).toBeInTheDocument();
  });

  it("hides the variable steps until asked", async () => {
    const user = userEvent.setup();
    const withSet = [
      PATH[0],
      {
        node_id: "n_set",
        kind: "set",
        matched: null,
        label_en: "Remember vigour",
        label_ar: null,
        values: {},
        detail: { wrote: { vigour: "low" } },
      },
      PATH[2],
    ];
    renderExplainer({ steps: walkStepsFromDryRun(withSet) });
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    await user.click(screen.getByText("Show 1 variable step"));
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByText("Remember vigour")).toBeInTheDocument();
  });

  it("still reads when the tree could not be drawn", () => {
    renderExplainer({ layout: null });
    expect(screen.getByText(/only the steps are shown/i)).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
  });
});
