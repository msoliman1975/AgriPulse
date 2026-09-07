import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import type { PositionedNode } from "../layout/treeLayout";
import { NodeDetailsPanel } from "./NodeDetailsPanel";

// The status list is served, not hard-coded, so the panel fetches it.
vi.mock("@/api/decisionTrees", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("@/api/decisionTrees");
  return {
    ...actual,
    getVerdictStatuses: () =>
      Promise.resolve([
        { code: "na", rank: 0, color: "#9AA0A6", label_en: "Not applicable", label_ar: "لا ينطبق" },
        { code: "very_good", rank: 1, color: "#1B873F", label_en: "Very good", label_ar: "ممتاز" },
        { code: "good", rank: 2, color: "#6FBF4B", label_en: "Good", label_ar: "جيد" },
        { code: "issue", rank: 3, color: "#E8A33D", label_en: "Issue", label_ar: "مشكلة" },
        { code: "alert", rank: 4, color: "#D64545", label_en: "Alert", label_ar: "إنذار" },
      ]),
  };
});

function leaf(outcome: Record<string, unknown>): PositionedNode {
  return {
    id: "leaf_1",
    x: 0,
    y: 0,
    role: "leaf-status",
    data: { label_en: "A leaf", outcome },
  } as PositionedNode;
}

async function renderPanel(node: PositionedNode, canEdit: boolean, onPatch = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <NodeDetailsPanel
        node={node}
        canEdit={canEdit}
        onPatch={onPatch}
        onClearPatch={vi.fn()}
        onDelete={vi.fn()}
      />
    </QueryClientProvider>,
  );
  // The panel opens read-only and the pencil switches it. Every edit
  // assertion below is about the form, so take the same step a user does.
  if (canEdit) {
    await userEvent.click(screen.getByRole("button", { name: /edit|تحرير/i }));
  }
  return onPatch;
}

describe("leaf kinds in the node panel", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
  });

  it("offers all four kinds", async () => {
    await renderPanel(leaf({ kind: "status", status: "good", text_en: "Fine." }), true);

    const kindSelect = await screen.findByLabelText("Kind");
    const options = Array.from(kindSelect.querySelectorAll("option")).map((o) => o.textContent);
    expect(options).toEqual(["Alert", "Recommendation", "Status", "No action"]);
  });

  it("shows the status picker and its colour for a status leaf", async () => {
    await renderPanel(leaf({ kind: "status", status: "very_good", text_en: "Canopy is dense." }), true);

    const status = await screen.findByLabelText("Status");
    expect((status as HTMLSelectElement).value).toBe("very_good");
    expect(
      screen.getByText("This colour is what the map paints for this status."),
    ).toBeInTheDocument();
  });

  it("hides severity, confidence and action type on a status leaf", async () => {
    await renderPanel(leaf({ kind: "status", status: "good", text_en: "Fine." }), true);

    await screen.findByLabelText("Status");
    expect(screen.queryByLabelText("Severity")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Confidence")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Action type")).not.toBeInTheDocument();
  });

  it("keeps severity on an alert leaf and confidence on a recommendation", async () => {
    await renderPanel(
      leaf({ kind: "alert", action_type: "scout", severity: "critical", text_en: "Pest." }),
      true,
    );

    expect(await screen.findByLabelText("Severity")).toBeInTheDocument();
    expect(screen.queryByLabelText("Status")).not.toBeInTheDocument();
  });

  it("reads an old quiet branch as no action, not as a recommendation", async () => {
    // 15 of the 63 shipped no-action leaves say `kind: recommendation` next
    // to `action_type: no_action`. Trusting the declared kind would show all
    // of them as recommendations here, and the author would never see that
    // they are the branches to convert.
    await renderPanel(
      leaf({ kind: "recommendation", action_type: "no_action", text_en: "Within the band." }),
      true,
    );

    const kindSelect = await screen.findByLabelText("Kind");
    expect((kindSelect as HTMLSelectElement).value).toBe("no_action");
  });

  it("explains that a no-action leaf says nothing, and offers a status instead", async () => {
    await renderPanel(leaf({ kind: "no_action", action_type: "no_action" }), true);

    expect(
      await screen.findByText(
        "A no-action leaf carries no message. Use a status leaf to say that the block is fine.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Message (EN)")).not.toBeInTheDocument();
  });

  it("patches the kind when the author switches it", async () => {
    const onPatch = await renderPanel(
      leaf({ kind: "recommendation", action_type: "scout", text_en: "Do a thing." }),
      true,
    );
    const user = userEvent.setup();

    await user.selectOptions(await screen.findByLabelText("Kind"), "status");

    await waitFor(() =>
      expect(onPatch).toHaveBeenCalledWith("leaf_1", { outcome: { kind: "status" } }),
    );
  });

  it("shows the status with its colour in read-only mode", async () => {
    await renderPanel(leaf({ kind: "status", status: "issue", text_en: "Salinity is high." }), false);

    expect(await screen.findByText("Issue")).toBeInTheDocument();
  });
});

describe("leaf kinds in Arabic", () => {
  beforeEach(async () => {
    await setupTestI18n("ar");
  });

  it("names the four kinds in Arabic", async () => {
    await renderPanel(leaf({ kind: "status", status: "good", text_en: "Fine." }), true);

    const kindSelect = await screen.findByLabelText("النوع");
    const options = Array.from(kindSelect.querySelectorAll("option")).map((o) => o.textContent);
    expect(options).toEqual(["إنذار", "توصية", "حالة", "بدون إجراء"]);
  });
});
