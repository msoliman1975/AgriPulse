import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApiError } from "@/api/errors";

import { MutationErrorBanner } from "./MutationErrorBanner";

describe("<MutationErrorBanner>", () => {
  it("shows the problem detail the API returned", () => {
    // The shape the tree-authoring endpoints actually answer with. Rendering
    // a fixed string instead is what left an author staring at "Save failed"
    // with no way to learn which code was wrong.
    const error = new ApiError({
      type: "https://agripulse.cloud/problems/recommendations/unknown-crop-attribute",
      title: "Unknown crop attribute",
      status: 422,
      detail:
        "crop attribute(s) seed_generation are not defined for crop path(s) mango — " +
        "the tree would branch on a value none of its blocks can carry, so the " +
        "comparison would never match.",
    });

    render(<MutationErrorBanner error={error} fallback="Save failed." />);

    expect(screen.getByRole("alert")).toHaveTextContent(/seed_generation/);
    expect(screen.getByRole("alert")).toHaveTextContent(/mango/);
  });

  it("falls back to the title when the problem carries no detail", () => {
    const error = new ApiError({ title: "Unknown crop attribute", status: 422 } as never);
    render(<MutationErrorBanner error={error} fallback="Save failed." />);
    expect(screen.getByRole("alert")).toHaveTextContent("Unknown crop attribute");
  });

  it("falls back to the supplied copy when there is no message at all", () => {
    render(<MutationErrorBanner error={new Error("")} fallback="Save failed." />);
    expect(screen.getByRole("alert")).toHaveTextContent("Save failed.");
  });

  it("falls back when the error is null", () => {
    render(<MutationErrorBanner error={null} fallback="Publish failed." />);
    expect(screen.getByRole("alert")).toHaveTextContent("Publish failed.");
  });

  it("does not render an empty bar for a whitespace-only message", () => {
    render(<MutationErrorBanner error={new Error("   ")} fallback="Save failed." />);
    expect(screen.getByRole("alert")).toHaveTextContent("Save failed.");
  });

  // A 422's `detail` is the same sentence every time; the field and the
  // reason are in `errors`. Showing only `detail` told an author their
  // input was rejected without saying which input.
  it("lists the per-field reasons from a request-validation 422", () => {
    const error = new ApiError({
      type: "https://agripulse.cloud/problems/validation",
      title: "Request validation failed",
      status: 422,
      detail: "One or more request fields failed validation.",
      errors: [
        {
          type: "string_pattern_mismatch",
          loc: ["body", "code"],
          msg: "String should match pattern '^[a-z0-9][a-z0-9_-]*$'",
        },
      ],
    });

    render(<MutationErrorBanner error={error} fallback="Save failed." />);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("One or more request fields failed validation.");
    expect(alert).toHaveTextContent("code: String should match pattern");
  });

  it("renders only the detail when the problem has no field errors", () => {
    const error = new ApiError({
      type: "about:blank",
      title: "Conflict",
      status: 409,
      detail: "A decision tree with code 'x' already exists.",
    });

    render(<MutationErrorBanner error={error} fallback="Save failed." />);

    expect(screen.getByRole("alert")).toHaveTextContent("already exists");
    expect(screen.queryByRole("list")).toBeNull();
  });
});
