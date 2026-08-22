import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { AppErrorBoundary, RouteErrorBoundary } from "./ErrorBoundary";

function Boom(): never {
  throw new Error("data.map is not a function");
}

function GoButton(): ReactNode {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => navigate("/fine")}>
      go
    </button>
  );
}

describe("<ErrorBoundary>", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    // React logs the caught error itself, and the boundary logs it again on
    // purpose. Neither belongs in the test output.
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // The whole reason this component exists: before it, a throw here left an
  // empty document and the operator reported "the page is blank", which
  // looks the same as a permissions problem or a bad deploy.
  it("shows the error instead of rendering nothing", () => {
    render(
      <MemoryRouter initialEntries={["/platform/alerts"]}>
        <RouteErrorBoundary>
          <Boom />
        </RouteErrorBoundary>
      </MemoryRouter>,
    );

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("This page could not be shown")).toBeInTheDocument();
    // The raw message is shown on purpose - it is what turns a support
    // conversation into a search.
    expect(screen.getByText("data.map is not a function")).toBeInTheDocument();
  });

  it("keeps rendering children when nothing throws", () => {
    render(
      <MemoryRouter>
        <RouteErrorBoundary>
          <p>page content</p>
        </RouteErrorBoundary>
      </MemoryRouter>,
    );

    expect(screen.getByText("page content")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  // React latches a boundary once it catches. Without the pathname key,
  // navigating away from a broken page would leave the error panel up on
  // every page visited afterwards.
  it("clears when the route changes", async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={["/broken"]}>
        <RouteErrorBoundary>
          <Routes>
            <Route path="/broken" element={<Boom />} />
            <Route path="/fine" element={<p>healthy page</p>} />
          </Routes>
        </RouteErrorBoundary>
        <GoButton />
      </MemoryRouter>,
    );

    expect(screen.getByText("data.map is not a function")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "go" }));

    expect(screen.getByText("healthy page")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("the shell fallback does not need i18n", async () => {
    // i18n failing to initialise is one of the things that can throw above
    // the routes, so the outermost fallback must not call useTranslation.
    await setupTestI18n("ar");
    render(
      <AppErrorBoundary>
        <Boom />
      </AppErrorBoundary>,
    );

    expect(screen.getByText("AgriPulse could not start")).toBeInTheDocument();
  });
});
