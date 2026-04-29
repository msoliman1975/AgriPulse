import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";
import type { Me } from "@/api/me";
import { MePage } from "./MePage";

const fetchMeMock = vi.hoisted(() => vi.fn<() => Promise<Me>>());

vi.mock("@/api/me", async () => {
  const actual = await vi.importActual<typeof import("@/api/me")>("@/api/me");
  return { ...actual, fetchMe: fetchMeMock };
});

const sampleMe: Me = {
  id: "00000000-0000-0000-0000-000000000001",
  email: "dev@missionagre.local",
  full_name: "Dev User",
  phone: null,
  avatar_url: null,
  status: "active",
  last_login_at: null,
  preferences: {
    language: "en",
    numerals: "western",
    unit_system: "feddan",
    timezone: "Africa/Cairo",
    date_format: "YYYY-MM-DD",
    notification_channels: ["in_app", "email"],
  },
  platform_roles: [],
  tenant_memberships: [],
  farm_scopes: [],
};

describe("MePage", () => {
  beforeEach(() => {
    fetchMeMock.mockReset();
    fetchMeMock.mockResolvedValue(sampleMe);
  });

  it("renders the profile heading in English (LTR)", async () => {
    await setupTestI18n("en");
    render(<MePage />);
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "My profile" })).toBeInTheDocument(),
    );
    expect(screen.getByText("Dev User")).toBeInTheDocument();
    expect(document.documentElement.getAttribute("dir")).toBe("ltr");
  });

  it("renders the profile heading in Arabic (RTL)", async () => {
    await setupTestI18n("ar");
    render(<MePage />);
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "ملفي الشخصي" })).toBeInTheDocument(),
    );
    expect(document.documentElement.getAttribute("dir")).toBe("rtl");
  });
});
