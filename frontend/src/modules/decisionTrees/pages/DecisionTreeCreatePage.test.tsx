import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { DecisionTreeCreatePage } from "./DecisionTreeCreatePage";

const mutate = vi.fn();

vi.mock("@/queries/decisionTrees", () => ({
  useCreateDecisionTree: () => ({
    mutate: (...a: unknown[]) => mutate(...a),
    isPending: false,
    isError: false,
    error: null,
  }),
}));
vi.mock("@/rbac/useCapability", () => ({ useCapability: () => true }));
// The targeting picker fetches the country list + the whole crop catalog;
// the code/YAML sync is what's under test, so stand in a button that reports
// one crop path — the minimum that enables the create buttons.
vi.mock("../components/TreeTargetingPicker", () => ({
  TreeTargetingPicker: ({ onCropPathsChange }: { onCropPathsChange: (n: string[]) => void }) => (
    <button type="button" onClick={() => onCropPathsChange(["mango"])}>
      pick mango
    </button>
  ),
}));

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <DecisionTreeCreatePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DecisionTreeCreatePage code ↔ YAML sync", () => {
  beforeEach(async () => {
    mutate.mockReset();
    await setupTestI18n();
  });

  it("writes the typed code into the YAML body", async () => {
    const user = userEvent.setup();
    renderPage();

    const body = document.querySelector("textarea") as HTMLTextAreaElement;
    expect(body.value).toContain("code: REPLACE_ME");

    await user.type(screen.getByLabelText(/Code \(stable identifier\)/), "newttt");

    expect(body.value).toContain("code: newttt");
    expect(body.value).not.toContain("REPLACE_ME");
  });

  it("uses a code pattern the browser can actually compile", () => {
    renderPage();
    const pattern = screen.getByLabelText(/Code \(stable identifier\)/).getAttribute("pattern");

    // Chrome parses the `pattern` attribute with the `v` flag, where a bare
    // `-` inside a character class is a syntax error — and an uncompilable
    // pattern is silently IGNORED, so the field validated nothing and threw
    // on every page load. `u` is checked too, since older engines use it.
    expect(pattern).toBeTruthy();
    for (const flag of ["u", "v"]) {
      expect(() => new RegExp(pattern as string, flag)).not.toThrow();
    }

    const re = new RegExp(pattern as string, "v");
    expect(re.test("scout_for_stress_v1")).toBe(true);
    expect(re.test("a-b_c9")).toBe(true);
    expect(re.test("Bad Code!")).toBe(false);
    expect(re.test("-leading")).toBe(false);
  });

  it("posts a YAML body whose code matches the form field", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText(/Code \(stable identifier\)/), "newttt");
    await user.click(screen.getByRole("button", { name: "pick mango" }));
    await user.click(screen.getByRole("button", { name: "Create tree" }));

    expect(mutate).toHaveBeenCalledTimes(1);
    const payload = mutate.mock.calls[0][0] as { code: string; tree_yaml: string };
    expect(payload.code).toBe("newttt");
    // The regression this guards: the seeded body used to keep its own
    // placeholder code, and the backend rejected the save outright with
    // "YAML body has code 'my_tree_v1' but the URL says 'newttt'".
    expect(payload.tree_yaml).toContain("code: newttt\n");
  });
});
