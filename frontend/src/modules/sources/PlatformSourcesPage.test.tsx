// The sources library (D27): list, how each document numbers a source, what
// cites it, and the EN/AR copy.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CONFIDENCES, SOURCE_KINDS, type Source, type SourceDetail } from "@/api/sources";
import ar from "@/i18n/locales/ar/sources.json";
import en from "@/i18n/locales/en/sources.json";
import { setupTestI18n } from "@/i18n/testing";

import { PlatformSourcesPage } from "./PlatformSourcesPage";
import { SourcesMarker } from "./SourcesMarker";

const http = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }));
vi.mock("@/api/client", () => ({ apiClient: http }));
const can = vi.hoisted(() => ({ manage: true }));
vi.mock("@/rbac/useCapability", () => ({ useCapability: () => can.manage }));

const FAO: Source = {
  id: "s1",
  kind: "web",
  citation: "FAO (2002). Date Palm Cultivation",
  title: null,
  authors: null,
  year: 2002,
  publisher: null,
  doi: null,
  url: "https://www.fao.org/4/y4360e/y4360e00.htm",
  language: null,
  notes: null,
  is_active: true,
  created_at: "2026-11-13T00:00:00Z",
  updated_at: "2026-11-13T00:00:00Z",
  link_count: 1,
  aliases: [
    { document_code: "medjool_manual_1_7", ref_number: 5 },
    { document_code: "medjool_trees_v2", ref_number: 40 },
  ],
};
const DETAIL: SourceDetail = {
  ...FAO,
  links: [
    {
      id: "l1",
      source_id: "s1",
      entity_type: "tree_parameter",
      entity_key: "date_palm_medjool_cold",
      detail: "cold_irrigate_c",
      confidence: "expert_inference",
      note: null,
      created_at: "2026-11-13T00:00:00Z",
      citation: FAO.citation,
      url: FAO.url,
      doi: null,
      year: 2002,
      kind: "web",
    },
  ],
};

function wrap(node: ReactNode): ReactNode {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>
  );
}

beforeEach(async () => {
  await setupTestI18n("en");
  can.manage = true;
  http.get.mockReset();
  http.get.mockImplementation((url: string) => {
    if (url === "/v1/sources/documents")
      return Promise.resolve({
        data: [{ document_code: "medjool_manual_1_7", document_title: "x", entries: 82 }],
      });
    if (url === "/v1/sources") return Promise.resolve({ data: [FAO] });
    if (url === "/v1/sources/s1") return Promise.resolve({ data: DETAIL });
    if (url === "/v1/sources/links") return Promise.resolve({ data: DETAIL.links });
    return Promise.reject(new Error(url));
  });
});

describe("PlatformSourcesPage", () => {
  it("lists sources with each document's number", async () => {
    render(wrap(<PlatformSourcesPage />));
    expect(await screen.findByText(FAO.citation)).toBeInTheDocument();
    expect(screen.getByText("Manual 1.7 [5] · Trees v2 [40]")).toBeInTheDocument();
    expect(await screen.findByRole("option", { name: "Manual 1.7 (82)" })).toBeInTheDocument();
  });

  it("shows what cites a source, with its confidence, and can unlink", async () => {
    render(wrap(<PlatformSourcesPage />));
    fireEvent.click(await screen.findByText(FAO.citation));
    const usedBy = await screen.findByText("Used by (1)");
    const panel = usedBy.closest("div")!.parentElement!;
    const row = within(panel)
      .getByText(/date_palm_medjool_cold · cold_irrigate_c/)
      .closest("li")!;
    expect(within(row).getByText("Expert inference")).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "Remove link" })).toBeInTheDocument();
  });

  it("hides editing from someone who cannot manage the catalogue", async () => {
    can.manage = false;
    render(wrap(<PlatformSourcesPage />));
    fireEvent.click(await screen.findByText(FAO.citation));
    await screen.findByText("Used by (1)");
    expect(screen.queryByRole("button", { name: "New source" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove link" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
  });
});

describe("SourcesMarker", () => {
  it("opens the linked sources with their confidence", async () => {
    render(wrap(<SourcesMarker entityType="tree_parameter" entityKey="date_palm_medjool_cold" />));
    fireEvent.click(await screen.findByRole("button", { name: "Source" }));
    expect(screen.getByRole("link", { name: FAO.citation })).toHaveAttribute("href", FAO.url);
    expect(screen.getByText("Expert inference")).toBeInTheDocument();
  });

  it("renders nothing when the item cites nothing", async () => {
    http.get.mockImplementation(() => Promise.resolve({ data: [] }));
    const { container } = render(wrap(<SourcesMarker entityType="finding" entityKey="x" />));
    await new Promise((r) => setTimeout(r, 20));
    expect(container).toBeEmptyDOMElement();
  });
});

describe("sources copy", () => {
  it.each([
    ["en", en],
    ["ar", ar],
  ] as const)("%s has every kind, confidence and entity label", (_lang, bundle) => {
    const b = bundle as unknown as Record<string, Record<string, string>>;
    for (const k of SOURCE_KINDS) expect(b.kind[k]).toBeTruthy();
    for (const c of CONFIDENCES) expect(b.confidence[c]).toBeTruthy();
    expect(Object.keys(b.entity)).toHaveLength(8);
  });
});
