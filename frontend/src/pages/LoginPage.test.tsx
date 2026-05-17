import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";
import { LoginPage } from "./LoginPage";

const signinRedirect = vi.fn();

// Mock react-oidc-context so the page renders without an OIDC provider
// and the signinRedirect side-effect is observable.
vi.mock("react-oidc-context", () => ({
  useAuth: () => ({
    isAuthenticated: false,
    isLoading: false,
    activeNavigator: undefined,
    signinRedirect,
  }),
}));

describe("LoginPage", () => {
  beforeEach(async () => {
    signinRedirect.mockClear();
    await setupTestI18n("en");
  });

  it("renders the sign-in heading in English (LTR)", async () => {
    await setupTestI18n("en");
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { name: "Sign in to AgriPulse" })).toBeInTheDocument();
    expect(document.documentElement.getAttribute("dir")).toBe("ltr");
  });

  it("renders the sign-in heading in Arabic (RTL)", async () => {
    await setupTestI18n("ar");
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    );
    expect(
      screen.getByRole("heading", { name: "ØªØ³Ø¬ÙŠÙ„ Ø§Ù„Ø¯Ø®ÙˆÙ„ Ø¥Ù„Ù‰ Ø£Ø¬Ø±ÙŠ.Ø¨ÙŽÙ„Ø³" }),
    ).toBeInTheDocument();
    expect(document.documentElement.getAttribute("dir")).toBe("rtl");
  });
});
