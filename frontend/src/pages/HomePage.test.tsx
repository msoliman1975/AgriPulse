import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, beforeEach, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";

import { setupTestI18n } from "@/i18n/testing";
import { HomePage } from "./HomePage";

// Mock the farms API so the redirect path is deterministic per test.
vi.mock("@/api/farms", () => ({
  listFarms: vi.fn(() => Promise.resolve({ items: [], total: 0 })),
}));

function renderWithProviders(node: ReactNode): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <MemoryRouter>
      <QueryClientProvider client={qc}>{node}</QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("HomePage", () => {
  beforeEach(() => {
    void setupTestI18n("en");
    vi.clearAllMocks();
  });

  it("renders the welcome heading in English (LTR) when there are no farms", async () => {
    await setupTestI18n("en");
    renderWithProviders(<HomePage />);
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Welcome" })).toBeInTheDocument(),
    );
    expect(document.documentElement.getAttribute("dir")).toBe("ltr");
  });

  it("renders the welcome heading in Arabic (RTL) when there are no farms", async () => {
    await setupTestI18n("ar");
    renderWithProviders(<HomePage />);
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "مرحبًا" })).toBeInTheDocument(),
    );
    expect(document.documentElement.getAttribute("dir")).toBe("rtl");
  });
});
