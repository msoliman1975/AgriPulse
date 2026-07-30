import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PurgeJob, PurgePreview } from "@/api/purge";
import { setupTestI18n } from "@/i18n/testing";

import { PurgeDialog, type PurgeTarget } from "./PurgeDialog";

vi.mock("react-oidc-context", () => ({
  useAuth: () => ({ user: { access_token: "" } }),
}));

const previewMock = vi.hoisted(() => vi.fn());
const submitMock = vi.hoisted(() => vi.fn());
vi.mock("@/api/purge", async () => {
  const actual = await vi.importActual<object>("@/api/purge");
  return { ...actual, getPurgePreview: previewMock, submitPurge: submitMock };
});

const TENANT_ID = "11111111-1111-1111-1111-111111111111";
const BLOCK_ID = "22222222-2222-2222-2222-222222222222";

const TARGET: PurgeTarget = {
  kind: "block",
  id: BLOCK_ID,
  tenantId: TENANT_ID,
  label: "B-01",
};

function preview(overrides: Partial<PurgePreview> = {}): PurgePreview {
  return {
    kind: "block",
    id: BLOCK_ID,
    label: "B-01",
    confirmation_phrase: "B-01",
    tenant_id: TENANT_ID,
    tenant_slug: "acme",
    archived: true,
    blocking: [],
    db_rows: [
      { table: "block_index_aggregates", rows: 1840 },
      { table: "alerts", rows: 3 },
    ],
    total_rows: 1843,
    storage: {
      attachment_objects: 2,
      imagery_objects: 40,
      imagery_objects_kept_shared: 0,
    },
    pgstac: { items: 40, collections: 0 },
    ...overrides,
  };
}

function job(overrides: Partial<PurgeJob> = {}): PurgeJob {
  return {
    id: "33333333-3333-3333-3333-333333333333",
    kind: "block",
    target_id: BLOCK_ID,
    target_label: "B-01",
    tenant_id: TENANT_ID,
    tenant_slug: "acme",
    status: "succeeded",
    phase: "verify",
    phases: [],
    preview: preview(),
    dry_run: false,
    reason: null,
    error: null,
    created_at: "2026-07-29T10:00:00Z",
    started_at: "2026-07-29T10:00:00Z",
    completed_at: "2026-07-29T10:00:05Z",
    created_by_email: "ops@agripulse.test",
    receipt: {
      id: "44444444-4444-4444-4444-444444444444",
      kind: "block",
      target_label: "B-01",
      actor_email: "ops@agripulse.test",
      reason: null,
      started_at: "2026-07-29T10:00:00Z",
      finished_at: "2026-07-29T10:00:05Z",
      deleted: { total_rows: 1843, storage_objects: 42 },
      verification: { orphans_found: 0, scanned_tables: 57 },
      errors: [],
      created_at: "2026-07-29T10:00:05Z",
    },
    ...overrides,
  };
}

function renderDialog(target: PurgeTarget | null = TARGET) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <PurgeDialog target={target} onClose={() => {}} />
    </QueryClientProvider>,
  );
}

describe("<PurgeDialog>", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    previewMock.mockReset();
    submitMock.mockReset();
  });

  it("shows the server's impact numbers rather than anything computed locally", async () => {
    previewMock.mockResolvedValue(preview());
    renderDialog();

    expect(await screen.findByText("1,843 rows across 2 tables")).toBeInTheDocument();
    expect(screen.getByText("42 storage objects")).toBeInTheDocument();
    expect(screen.getByText("block_index_aggregates")).toBeInTheDocument();
  });

  it("keeps the destructive button disabled until the exact phrase is typed", async () => {
    previewMock.mockResolvedValue(preview());
    const user = userEvent.setup();
    renderDialog();

    // The buttons render before the preview resolves; wait for the impact
    // table, which only appears once it has.
    await screen.findByText("1,843 rows across 2 tables");
    const confirm = screen.getByRole("button", { name: "Delete permanently" });
    expect(confirm).toBeDisabled();

    const input = screen.getByRole("textbox", { name: /type to confirm/i });
    await user.type(input, "B-0");
    expect(confirm).toBeDisabled();

    await user.type(input, "1");
    await waitFor(() => expect(confirm).toBeEnabled());
  });

  it("refuses a live entity but still offers the dry run", async () => {
    previewMock.mockResolvedValue(
      preview({
        archived: false,
        blocking: [{ reason: "not_archived", detail: "Archive the block first." }],
      }),
    );
    const user = userEvent.setup();
    renderDialog();

    expect(await screen.findByText("Archive the block first.")).toBeInTheDocument();

    const input = screen.getByRole("textbox", { name: /type to confirm/i });
    await user.type(input, "B-01");
    // Typing the phrase is not enough — archive-first is a separate gate.
    expect(screen.getByRole("button", { name: "Delete permanently" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Dry run" })).toBeEnabled();
  });

  it("dry run submits with dry_run true and reports that nothing was deleted", async () => {
    previewMock.mockResolvedValue(preview());
    submitMock.mockResolvedValue(
      job({
        dry_run: true,
        receipt: {
          ...job().receipt!,
          deleted: { total_rows: 1843, dry_run: true },
          verification: { skipped: "dry run" },
        },
      }),
    );
    const user = userEvent.setup();
    renderDialog();

    await user.click(await screen.findByRole("button", { name: "Dry run" }));

    await waitFor(() => expect(submitMock).toHaveBeenCalledTimes(1));
    expect(submitMock.mock.calls[0][0]).toMatchObject({ dry_run: true, confirmation: "B-01" });
    expect(
      await screen.findByText("Dry run complete — nothing was deleted"),
    ).toBeInTheDocument();
  });

  it("renders a clean receipt when verification finds no orphans", async () => {
    previewMock.mockResolvedValue(preview());
    submitMock.mockResolvedValue(job());
    const user = userEvent.setup();
    renderDialog();

    const input = await screen.findByRole("textbox", { name: /type to confirm/i });
    await user.type(input, "B-01");
    await user.click(screen.getByRole("button", { name: "Delete permanently" }));

    expect(await screen.findByText("Purged “B-01”")).toBeInTheDocument();
    expect(screen.getByText("Verification: 0 orphans across 57 tables")).toBeInTheDocument();
  });

  it("flags a purge that left residue behind", async () => {
    previewMock.mockResolvedValue(preview());
    submitMock.mockResolvedValue(
      job({
        receipt: {
          ...job().receipt!,
          verification: { orphans_found: 2, scanned_tables: 57 },
          errors: ["object k1: boom"],
        },
      }),
    );
    const user = userEvent.setup();
    renderDialog();

    const input = await screen.findByRole("textbox", { name: /type to confirm/i });
    await user.type(input, "B-01");
    await user.click(screen.getByRole("button", { name: "Delete permanently" }));

    expect(await screen.findByText("Purge finished with problems")).toBeInTheDocument();
    expect(screen.getByText("Verification: 2 orphans across 57 tables")).toBeInTheDocument();
    expect(screen.getByText("object k1: boom")).toBeInTheDocument();
  });
});
