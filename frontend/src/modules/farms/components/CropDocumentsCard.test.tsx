// Block "Documents" (D29): lists what the crop path inherits and opens each
// through a link minted on the click.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { CropDocumentsCard } from "./CropDocumentsCard";

const http = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/api/client", () => ({ apiClient: http }));

const BLOCK = "22222222-2222-2222-2222-222222222222";

const DOC = {
  id: "d1",
  document_code: "medjool_organic_manual_ar",
  crop_path: "date_palm.medjool",
  title_en: "Organic Medjool Manual",
  title_ar: "دليل المجهول العضوي",
  language: "ar",
  kind: "manual",
  edition: "1.7",
  original_filename: "manual-ar.pdf",
  content_type: "application/pdf",
  size_bytes: 2_500_000,
  sha256: "a".repeat(64),
  superseded_at: null,
  superseded_by: null,
  retired_at: null,
  created_at: "2026-11-14T00:00:00Z",
  updated_at: "2026-11-14T00:00:00Z",
  is_current: true,
};

function wrap(node: ReactNode): ReactNode {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>;
}

describe("CropDocumentsCard", () => {
  beforeEach(() => {
    http.get.mockReset();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("lists inherited documents and opens a fresh download link", async () => {
    await setupTestI18n("en");
    http.get.mockImplementation((url: string) => {
      if (url === `/v1/blocks/${BLOCK}/crop-documents`) {
        return Promise.resolve({
          data: { block_id: BLOCK, crop_path: "date_palm.medjool", documents: [DOC] },
        });
      }
      if (url === `/v1/blocks/${BLOCK}/crop-documents/d1/link`) {
        return Promise.resolve({
          data: {
            url: "https://s3.test/x",
            expires_at: "2026-11-14T00:05:00Z",
            disposition: "attachment",
          },
        });
      }
      return Promise.reject(new Error(url));
    });
    const popup = { opener: {}, location: { href: "" }, close: vi.fn() };
    const openSpy = vi.spyOn(window, "open").mockReturnValue(popup as unknown as Window);

    render(wrap(<CropDocumentsCard blockId={BLOCK} />));
    expect(await screen.findByText("Organic Medjool Manual")).toBeInTheDocument();
    expect(screen.getByText(/Arabic · Edition 1\.7 · 2\.4 MB/)).toBeInTheDocument();
    expect(screen.getByText("For date_palm.medjool")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Download" }));
    expect(openSpy).toHaveBeenCalledWith("about:blank", "_blank");
    await waitFor(() => expect(popup.location.href).toBe("https://s3.test/x"));
    expect(http.get).toHaveBeenCalledWith(`/v1/blocks/${BLOCK}/crop-documents/d1/link`, {
      params: { disposition: "attachment" },
    });
    expect(popup.opener).toBeNull();
  });

  it("shows the Arabic title in Arabic and explains an empty list", async () => {
    await setupTestI18n("ar");
    http.get.mockResolvedValueOnce({
      data: { block_id: BLOCK, crop_path: "date_palm.medjool", documents: [DOC] },
    });
    render(wrap(<CropDocumentsCard blockId={BLOCK} />));
    expect(await screen.findByText("دليل المجهول العضوي")).toBeInTheDocument();
    expect(screen.getByText("المستندات")).toBeInTheDocument();
  });

  it("asks for a crop when the block has none", async () => {
    await setupTestI18n("en");
    http.get.mockResolvedValueOnce({ data: { block_id: BLOCK, crop_path: null, documents: [] } });
    render(wrap(<CropDocumentsCard blockId={BLOCK} />));
    expect(await screen.findByText("Assign a crop to see its documents.")).toBeInTheDocument();
  });
});
