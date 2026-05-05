import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen, waitFor } from "@testing-library/react";

import { setupTestI18n } from "@/i18n/testing";

const useAuthMock = vi.hoisted(() => vi.fn());
vi.mock("react-oidc-context", () => ({ useAuth: useAuthMock }));

import { AuthCallback } from "./AuthCallback";

function renderAt(initial: string): ReturnType<typeof render> {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <Routes>
        <Route path="/auth/callback" element={<AuthCallback />} />
        <Route path="/" element={<p>home</p>} />
        <Route path="/farms" element={<p>farms</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  useAuthMock.mockReset();
});

describe("AuthCallback", () => {
  it("shows a status while react-oidc-context is processing the code", async () => {
    await setupTestI18n("en");
    useAuthMock.mockReturnValue({ isAuthenticated: false, isLoading: true, error: null });
    renderAt("/auth/callback?code=abc&state=xyz");
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("surfaces auth errors instead of looping silently", async () => {
    await setupTestI18n("en");
    useAuthMock.mockReturnValue({
      isAuthenticated: false,
      isLoading: false,
      error: new Error("invalid_grant: code expired"),
    });
    renderAt("/auth/callback");
    expect(screen.getByRole("alert").textContent).toMatch(/invalid_grant/);
  });

  it("navigates to the original `from` location after sign-in completes", async () => {
    await setupTestI18n("en");
    useAuthMock.mockReturnValue({
      isAuthenticated: true,
      isLoading: false,
      error: null,
      user: { state: { from: "/farms" } },
    });
    renderAt("/auth/callback");
    await waitFor(() => {
      expect(screen.getByText("farms")).toBeInTheDocument();
    });
  });

  it("falls back to / when no `from` was preserved", async () => {
    await setupTestI18n("en");
    useAuthMock.mockReturnValue({
      isAuthenticated: true,
      isLoading: false,
      error: null,
      user: { state: undefined },
    });
    renderAt("/auth/callback");
    await waitFor(() => {
      expect(screen.getByText("home")).toBeInTheDocument();
    });
  });
});
