/**
 * The panel is shut until it has something to say.
 *
 * It had no test at all before this. The two that matter are the ones that
 * would turn a collapsed panel into a lie: a publish the server refused, and
 * a publish it accepted. Either answer behind a shut panel reads as a button
 * that did nothing.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";
import type { BetaValidationError } from "@/api/decisionTreesBeta";

import { PublishChecksPanel } from "./PublishChecksPanel";
import type { EditorHint } from "../lib/betaCompile";

const ERROR: BetaValidationError = {
  rule: "path-ends-without-stop",
  node_id: "reg_2",
  node_ids: ["reg_2"],
  message_en: "A path ends without a stop node.",
  message_ar: "",
};

const HINT: EditorHint = {
  rule: "tree-bad-root",
  messageKey: "missing_root",
  node_id: null,
  detail: "the tree names no root",
};

function renderPanel(over: Partial<Parameters<typeof PublishChecksPanel>[0]> = {}) {
  return render(
    <PublishChecksPanel
      errors={[]}
      serverState="unchecked"
      hints={[]}
      canPublish
      onPublish={vi.fn()}
      onSelectNode={vi.fn()}
      {...over}
    />,
  );
}

describe("PublishChecksPanel", () => {
  beforeEach(async () => {
    await setupTestI18n();
  });

  it("is collapsed on first render", () => {
    renderPanel({ hints: [HINT] });
    expect(screen.queryByText("While you edit")).not.toBeInTheDocument();
  });

  it("keeps the publish button reachable while collapsed", () => {
    // The button lives in the header, so folding the body never hides the
    // action the panel exists for.
    renderPanel();
    expect(screen.getByRole("button", { name: "Publish" })).toBeEnabled();
  });

  it("says what is inside while it is shut", () => {
    renderPanel({ hints: [HINT, HINT] });
    expect(screen.getByRole("button", { name: "Show publish checks" })).toHaveTextContent(
      "2 hints",
    );
  });

  it("says there is nothing wrong when there is nothing wrong", () => {
    renderPanel();
    expect(screen.getByRole("button", { name: "Show publish checks" })).toHaveTextContent(
      "No problems",
    );
  });

  it("opens and closes on the toggle", async () => {
    const user = userEvent.setup();
    renderPanel({ hints: [HINT] });
    await user.click(screen.getByRole("button", { name: "Show publish checks" }));
    expect(screen.getByText("While you edit")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Hide publish checks" }));
    expect(screen.queryByText("While you edit")).not.toBeInTheDocument();
  });

  it("opens itself when the server refuses the version", () => {
    // A refusal behind a shut panel is a publish button that looks like it
    // did nothing.
    const { rerender } = renderPanel();
    expect(screen.queryByText(/refused this version/i)).not.toBeInTheDocument();
    rerender(
      <PublishChecksPanel
        errors={[ERROR]}
        serverState="refused"
        hints={[]}
        canPublish
        onPublish={vi.fn()}
        onSelectNode={vi.fn()}
      />,
    );
    expect(screen.getByText(/refused this version/i)).toBeInTheDocument();
    expect(screen.getByText("A path ends without a stop node.")).toBeInTheDocument();
  });

  it("opens itself when the server accepts the version", () => {
    // And an acceptance behind a shut panel is a silent success.
    const { rerender } = renderPanel();
    rerender(
      <PublishChecksPanel
        errors={[]}
        serverState="accepted"
        hints={[]}
        canPublish
        onPublish={vi.fn()}
        onSelectNode={vi.fn()}
      />,
    );
    expect(screen.getByText("The server published this version.")).toBeInTheDocument();
  });

  it("opens itself on a failure that is not a compiler rejection", () => {
    renderPanel({ error: "You do not have permission to publish." });
    expect(screen.getByText("You do not have permission to publish.")).toBeInTheDocument();
  });

  it("lets the author shut it again after a refusal", async () => {
    // The reopen is keyed on a signature of the answer, not on the array, so
    // a re-render with the same refusal must not fight the close button.
    const user = userEvent.setup();
    renderPanel({ errors: [ERROR], serverState: "refused" });
    expect(screen.getByText(/refused this version/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Hide publish checks" }));
    expect(screen.queryByText(/refused this version/i)).not.toBeInTheDocument();
  });

  it("counts the errors on the toggle and marks it as the blocking kind", () => {
    renderPanel({ errors: [ERROR], serverState: "refused" });
    expect(screen.getByRole("button", { name: "Hide publish checks" })).toHaveTextContent(
      "1 error",
    );
    expect(screen.getByRole("button", { name: "Publish" })).toBeDisabled();
  });
});
