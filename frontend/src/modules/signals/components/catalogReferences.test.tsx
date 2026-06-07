import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError, AxiosHeaders } from "axios";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/errors";
import type { SignalDefinition, SignalReferences, ValueKind } from "@/api/signals";
import { setupTestI18n } from "@/i18n/testing";

import { filterDefinitions } from "./catalogFilter";
import { ArchiveConflictModal, refCount, referencesFromError } from "./ReferenceWidgets";

function defn(p: Partial<SignalDefinition> & Pick<SignalDefinition, "id" | "code" | "name">): SignalDefinition {
  return {
    description: null,
    value_kind: "numeric",
    unit: null,
    categorical_values: null,
    value_min: null,
    value_max: null,
    attachment_allowed: false,
    is_active: true,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    aggregation: "latest",
    aggregation_window_days: null,
    ...p,
  };
}

const DEFS: SignalDefinition[] = [
  defn({ id: "1", code: "soil_ph", name: "Soil pH", description: "acidity" }),
  defn({ id: "2", code: "scout_sev", name: "Scout severity", value_kind: "categorical" }),
  defn({ id: "3", code: "old_one", name: "Archived signal", is_active: false }),
];

describe("filterDefinitions", () => {
  const base = { search: "", kinds: new Set<ValueKind>(), showArchived: false };

  it("hides archived unless showArchived", () => {
    expect(filterDefinitions(DEFS, base).map((d) => d.id)).toEqual(["1", "2"]);
    expect(filterDefinitions(DEFS, { ...base, showArchived: true })).toHaveLength(3);
  });

  it("matches name / code / description case-insensitively", () => {
    expect(filterDefinitions(DEFS, { ...base, search: "PH" }).map((d) => d.id)).toEqual(["1"]);
    expect(filterDefinitions(DEFS, { ...base, search: "scout_sev" }).map((d) => d.id)).toEqual(["2"]);
    expect(filterDefinitions(DEFS, { ...base, search: "acidity" }).map((d) => d.id)).toEqual(["1"]);
  });

  it("filters by value-kind chips", () => {
    const kinds = new Set<ValueKind>(["categorical"]);
    expect(filterDefinitions(DEFS, { ...base, kinds }).map((d) => d.id)).toEqual(["2"]);
  });
});

describe("referencesFromError", () => {
  function err409(extras: unknown): AxiosError {
    const e = new AxiosError("conflict");
    e.response = {
      status: 409,
      data: { extras },
      statusText: "",
      headers: {},
      config: { headers: new AxiosHeaders() },
    };
    return e;
  }

  it("extracts the reference list from a 409", () => {
    const refs = referencesFromError(
      err409({ decision_trees: [{ id: "t", code: "w", name: "W", kind: "decision_tree" }], templates: [] }),
    );
    expect(refCount(refs)).toBe(1);
  });

  it("extracts references from an ApiError (flattened problem+json)", () => {
    const apiErr = new ApiError({
      type: "x",
      title: "in use",
      status: 409,
      decision_trees: [],
      templates: [{ id: "tpl", code: "soiltest", name: "Soil test", kind: "signal_template" }],
    });
    expect(refCount(referencesFromError(apiErr))).toBe(1);
  });

  it("returns null for non-409 / non-axios errors", () => {
    expect(referencesFromError(new Error("boom"))).toBeNull();
  });
});

describe("ArchiveConflictModal", () => {
  beforeAll(async () => {
    await setupTestI18n("en");
  });

  it("lists references and fires onForce", async () => {
    const refs: SignalReferences = {
      decision_trees: [{ id: "t1", code: "wheat", name: "Wheat tree", kind: "decision_tree" }],
      templates: [],
    };
    const onForce = vi.fn();
    render(
      <ArchiveConflictModal references={refs} pending={false} onCancel={vi.fn()} onForce={onForce} />,
    );
    expect(screen.getByText("Wheat tree")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Archive anyway/i }));
    expect(onForce).toHaveBeenCalledOnce();
  });
});
