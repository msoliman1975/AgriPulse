import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { SceneTable } from "./SceneTable";

// A failed scenes request and a farm with no scenes both arrive here as zero
// rows. Reporting the first as the second is how prod told an operator that a
// farm had no imagery while the lock-exhaustion 500 (#378) was swallowing weeks
// of real scenes. The Observer's whole job is answering "did the pipeline run",
// so "no scenes" has to mean no scenes.

function renderTable(props: Partial<Parameters<typeof SceneTable>[0]> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <SceneTable
        tenantId="t1"
        farmId="f1"
        scenes={[]}
        isLoading={false}
        expanded={null}
        onToggleExpand={() => {}}
        {...props}
      />
    </QueryClientProvider>,
  );
}

describe("SceneTable empty vs failed", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
  });

  it("says the request failed when the query errored", () => {
    renderTable({ isError: true });
    expect(screen.getByText(/failed request, not an empty result/i)).toBeTruthy();
    expect(screen.queryByText(/No scenes match this selection/i)).toBeNull();
  });

  it("says there are no scenes only when the query actually succeeded", () => {
    renderTable({ isError: false });
    expect(screen.getByText(/No scenes match this selection/i)).toBeTruthy();
    expect(screen.queryByText(/failed request/i)).toBeNull();
  });

  it("checks the error before the row count, since a failure also has no rows", () => {
    // Guards the ordering specifically: if the length check ran first this
    // would render the empty state, because both states carry zero rows.
    renderTable({ isError: true, scenes: [] });
    expect(screen.getByText(/failed request, not an empty result/i)).toBeTruthy();
  });

  it("shows the skeleton while loading rather than either message", () => {
    renderTable({ isLoading: true });
    expect(screen.queryByText(/No scenes match this selection/i)).toBeNull();
    expect(screen.queryByText(/failed request/i)).toBeNull();
  });
});
