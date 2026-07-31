import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { PageHeader } from "./PageHeader";
import { Pill } from "./Pill";

describe("PageHeader", () => {
  it("renders the title as the page h1", () => {
    render(<PageHeader title="Farm asdsad" />);
    expect(screen.getByRole("heading", { level: 1, name: "Farm asdsad" })).toBeInTheDocument();
  });

  // 4C puts the status pill inline with the title. Rendering it *inside* the
  // h1 is what makes that a bug: the badge text joins the heading's
  // accessible name, so "Farm asdsad" is announced as "Farm asdsad Active"
  // and an exact-name heading query stops matching.
  it("keeps a badge out of the heading's accessible name", () => {
    render(<PageHeader title="Farm asdsad" badge={<Pill kind="ok">Active</Pill>} />);

    expect(screen.getByRole("heading", { level: 1, name: "Farm asdsad" })).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
  });
});
