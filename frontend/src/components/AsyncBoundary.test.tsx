import { beforeAll, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { setupTestI18n } from "@/i18n/testing";
import { ApiError } from "@/api/errors";

import { AsyncBoundary } from "./AsyncBoundary";
import { EmptyState } from "./EmptyState";
import type { AsyncState } from "./asyncState";

function renderBoundary(state: AsyncState<string[]>, extra: { filtered?: boolean } = {}) {
  return render(
    <AsyncBoundary
      state={state}
      filtered={extra.filtered}
      empty={<EmptyState message="Nothing here yet." />}
      noResults={<EmptyState message="Nothing matches your filters." />}
    >
      {(rows) => (
        <ul>
          {rows.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
    </AsyncBoundary>,
  );
}

describe("AsyncBoundary", () => {
  beforeAll(async () => {
    await setupTestI18n("en");
  });

  it("renders a skeleton while loading", () => {
    const { container } = renderBoundary({ status: "loading" });
    expect(container.querySelector(".animate-pulse")).not.toBeNull();
  });

  it("renders the problem detail and a retry control on error", async () => {
    const retry = vi.fn();
    renderBoundary({
      status: "error",
      error: new ApiError({ type: "about:blank", title: "Bad", status: 500, detail: "Boom" }),
      retry,
    });

    expect(screen.getByRole("alert")).toHaveTextContent("Boom");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("falls back to a generic message when the error carries none", () => {
    renderBoundary({ status: "error", error: {} });
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't load this");
  });

  it("shows the empty state when nothing exists", () => {
    renderBoundary({ status: "success", data: [] });
    expect(screen.getByText("Nothing here yet.")).toBeInTheDocument();
  });

  // The distinction that most pages get wrong today: a user who mistyped a
  // search is told the system holds no data.
  it("shows no-results — not empty — when a filter is narrowing the view", () => {
    renderBoundary({ status: "success", data: [] }, { filtered: true });
    expect(screen.getByText("Nothing matches your filters.")).toBeInTheDocument();
    expect(screen.queryByText("Nothing here yet.")).not.toBeInTheDocument();
  });

  it("renders children with the resolved data", () => {
    renderBoundary({ status: "success", data: ["alpha", "beta"] });
    expect(screen.getByText("alpha")).toBeInTheDocument();
    expect(screen.getByText("beta")).toBeInTheDocument();
  });
});
