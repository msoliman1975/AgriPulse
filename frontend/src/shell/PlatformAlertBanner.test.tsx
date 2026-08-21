import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { PlatformAlertBanner } from "./PlatformAlertBanner";

const mockUseCapability = vi.fn();
vi.mock("@/rbac/useCapability", () => ({
  useCapability: (cap: string) => mockUseCapability(cap),
}));

const mockUseSummary = vi.fn();
vi.mock("@/queries/platformAlerts", () => ({
  usePlatformAlertSummary: (enabled: boolean) => mockUseSummary(enabled),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

function renderBanner(): ReturnType<typeof render> {
  return render(
    <MemoryRouter>
      <PlatformAlertBanner />
    </MemoryRouter>,
  );
}

const NONE = { critical: 0, warning: 0, open: 0, acknowledged: 0, newest_at: null };

describe("<PlatformAlertBanner>", () => {
  it("renders nothing for a user without the platform capability", () => {
    mockUseCapability.mockReturnValue(false);
    mockUseSummary.mockReturnValue({ data: { ...NONE, critical: 9 } });
    const { container } = renderBanner();
    expect(container).toBeEmptyDOMElement();
  });

  it("does not fetch the summary for a non-platform user", () => {
    // A tenant user hitting /admin/alerts/summary would only earn a 403 on
    // every page load. The hook is still called (rules of hooks) but must be
    // disabled.
    mockUseCapability.mockReturnValue(false);
    mockUseSummary.mockReturnValue({ data: undefined });
    renderBanner();
    expect(mockUseSummary).toHaveBeenCalledWith(false);
  });

  it("stays hidden when nothing is wrong", () => {
    mockUseCapability.mockReturnValue(true);
    mockUseSummary.mockReturnValue({ data: NONE });
    const { container } = renderBanner();
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a red bar when anything is critical", () => {
    mockUseCapability.mockReturnValue(true);
    mockUseSummary.mockReturnValue({ data: { ...NONE, critical: 3 } });
    renderBanner();
    const bar = screen.getByRole("alert");
    expect(bar).toHaveClass("bg-ap-crit");
    expect(screen.getByText("platformAlerts.banner.critical")).toBeInTheDocument();
    expect(screen.getByText("platformAlerts.banner.review").closest("a")).toHaveAttribute(
      "href",
      "/platform/alerts",
    );
  });

  it("shows an amber bar when only warnings stand", () => {
    // Keeping the two apart is what stops red reading as routine.
    mockUseCapability.mockReturnValue(true);
    mockUseSummary.mockReturnValue({ data: { ...NONE, warning: 2 } });
    renderBanner();
    const bar = screen.getByRole("alert");
    expect(bar).toHaveClass("bg-ap-warn");
    expect(screen.getByText("platformAlerts.banner.warning")).toBeInTheDocument();
  });

  it("keeps the bar up while the summary is still loading nothing", () => {
    // `data` undefined means the request has not resolved; the banner must
    // not flash an empty red bar before it knows anything.
    mockUseCapability.mockReturnValue(true);
    mockUseSummary.mockReturnValue({ data: undefined });
    const { container } = renderBanner();
    expect(container).toBeEmptyDOMElement();
  });

  it("counts an acknowledged alert as still broken", () => {
    // Acknowledging says "seen", not "fixed". Only resolving clears the bar,
    // so the summary's critical count (which spans open + acknowledged) is
    // what the banner reads.
    mockUseCapability.mockReturnValue(true);
    mockUseSummary.mockReturnValue({ data: { ...NONE, critical: 1, acknowledged: 1, open: 0 } });
    renderBanner();
    expect(screen.getByRole("alert")).toHaveClass("bg-ap-crit");
  });
});
