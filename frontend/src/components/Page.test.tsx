import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";

import { Page } from "./Page";

describe("Page", () => {
  it("defaults to the wide frame (decision 5)", () => {
    const { container } = render(
      <Page>
        <p>body</p>
      </Page>,
    );
    expect(container.firstElementChild).toHaveClass("max-w-6xl");
  });

  it("caps at max-w-5xl for the standard escape hatch", () => {
    const { container } = render(
      <Page width="standard">
        <p>body</p>
      </Page>,
    );
    expect(container.firstElementChild).toHaveClass("max-w-5xl");
  });

  it("leaves full-width surfaces uncapped but padded", () => {
    const { container } = render(
      <Page width="full">
        <p>body</p>
      </Page>,
    );
    const root = container.firstElementChild;
    expect(root?.className).not.toMatch(/max-w-/);
    expect(root).toHaveClass("px-4");
  });

  // The shell no longer pads, so `bleed` is expressible without the shell
  // special-casing routes by pathname.
  it("drops all padding for bleed surfaces", () => {
    const { container } = render(
      <Page width="bleed">
        <p>body</p>
      </Page>,
    );
    const root = container.firstElementChild;
    expect(root?.className).not.toMatch(/px-4|py-6/);
  });
});
