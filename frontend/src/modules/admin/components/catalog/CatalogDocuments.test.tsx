// Documents tab (D29): what a path sets, what it inherits, its history, and
// a curator's multipart upload of a new edition.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { DocumentsPanel } from "./CatalogDocuments";

const http = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn() }));
vi.mock("@/api/client", () => ({ apiClient: http }));

function doc(overrides: Record<string, unknown>) {
  return {
    id: "d1",
    document_code: "medjool_organic_manual_en",
    crop_path: "date_palm.medjool",
    title_en: "Organic Medjool Manual",
    title_ar: "دليل المجهول العضوي",
    language: "en",
    kind: "manual",
    edition: "1.7",
    original_filename: "manual-1.7.pdf",
    content_type: "application/pdf",
    size_bytes: 2_500_000,
    sha256: "a".repeat(64),
    superseded_at: null,
    superseded_by: null,
    retired_at: null,
    created_at: "2026-11-14T00:00:00Z",
    updated_at: "2026-11-14T00:00:00Z",
    is_current: true,
    ...overrides,
  };
}

const DOCS = [
  doc({}),
  doc({
    id: "d0",
    edition: "1.3",
    original_filename: "manual-1.3.pdf",
    superseded_at: "2026-11-14T00:00:00Z",
    superseded_by: "d1",
    is_current: false,
  }),
  doc({
    id: "p1",
    crop_path: "date_palm",
    document_code: "date_palm_standard",
    title_en: "Date palm standard",
    title_ar: "معيار نخيل التمر",
    kind: "standard",
  }),
];

function wrap(node: ReactNode): ReactNode {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>;
}

beforeEach(async () => {
  await setupTestI18n("en");
  http.get.mockReset();
  http.post.mockReset();
  http.patch.mockReset();
  http.get.mockImplementation((url: string) => {
    if (url === "/v1/admin/crop-documents") return Promise.resolve({ data: DOCS });
    return Promise.reject(new Error(url));
  });
});

describe("DocumentsPanel", () => {
  it("splits own, inherited and history, and hides curation from readers", async () => {
    render(wrap(<DocumentsPanel cropPath="date_palm.medjool" canManage={false} />));
    expect(await screen.findByText("On this path")).toBeInTheDocument();
    expect(http.get).toHaveBeenCalledWith("/v1/admin/crop-documents", {
      params: { crop_path: "date_palm.medjool" },
    });
    expect(screen.getByText("Inherited from above")).toBeInTheDocument();
    expect(screen.getByText("From date_palm")).toBeInTheDocument();
    expect(screen.getByText("Earlier editions and retired documents (1)")).toBeInTheDocument();
    expect(screen.getByText("Superseded")).toBeInTheDocument();
    expect(screen.queryByText("Upload a document")).not.toBeInTheDocument();
    expect(screen.queryByText("New edition")).not.toBeInTheDocument();
  });

  it("uploads a new edition with the document's code and both titles", async () => {
    http.post.mockResolvedValue({
      data: { ...doc({ id: "d2", edition: "1.8" }), superseded_id: "d1" },
    });
    render(wrap(<DocumentsPanel cropPath="date_palm.medjool" canManage />));
    await screen.findByText("On this path");

    const row = screen
      .getAllByText("Organic Medjool Manual")
      .map((el) => el.closest("li"))
      .find((li) => li && within(li).queryByText("New edition"));
    fireEvent.click(within(row as HTMLElement).getByText("New edition"));

    const form = screen.getByRole("form", { name: "Upload a document" });
    expect(within(form).getByText("New edition of medjool_organic_manual_en")).toBeInTheDocument();
    expect(within(form).getByDisplayValue("medjool_organic_manual_en")).toHaveAttribute("readonly");
    expect(within(form).getByDisplayValue("دليل المجهول العضوي")).toBeInTheDocument();

    fireEvent.change(within(form).getByPlaceholderText("1.7"), { target: { value: "1.8" } });
    const file = new File(["%PDF-1.7"], "manual-1.8.pdf", { type: "application/pdf" });
    const input = form.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.click(within(form).getByRole("button", { name: "Upload" }));

    await waitFor(() => expect(http.post).toHaveBeenCalledTimes(1));
    const [url, body, config] = http.post.mock.calls[0];
    expect(url).toBe("/v1/admin/crop-documents");
    const fd = body as FormData;
    expect(fd.get("crop_path")).toBe("date_palm.medjool");
    expect(fd.get("document_code")).toBe("medjool_organic_manual_en");
    expect(fd.get("title_ar")).toBe("دليل المجهول العضوي");
    expect(fd.get("edition")).toBe("1.8");
    expect((fd.get("file") as File).name).toBe("manual-1.8.pdf");
    expect(config).toEqual({ headers: { "Content-Type": "multipart/form-data" } });
  });

  it("retires a current document", async () => {
    http.patch.mockResolvedValue({ data: doc({ retired_at: "2026-11-14T00:00:00Z" }) });
    render(wrap(<DocumentsPanel cropPath="date_palm.medjool" canManage />));
    await screen.findByText("On this path");
    fireEvent.click(screen.getAllByRole("button", { name: "Retire" })[0]);
    await waitFor(() =>
      expect(http.patch).toHaveBeenCalledWith("/v1/admin/crop-documents/d1", { retired: true }),
    );
  });
});
