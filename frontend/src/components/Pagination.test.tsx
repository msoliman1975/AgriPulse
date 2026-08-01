import { beforeAll, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { setupTestI18n } from "@/i18n/testing";

import { Pagination } from "./Pagination";

describe("Pagination", () => {
  beforeAll(async () => {
    await setupTestI18n("en");
  });

  it("renders nothing when everything fits on one page", () => {
    const { container } = render(
      <Pagination page={0} pageSize={25} total={3} onPageChange={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("reports the visible range", () => {
    render(<Pagination page={1} pageSize={25} total={60} onPageChange={vi.fn()} />);
    expect(screen.getByText("Showing 26–50 of 60")).toBeInTheDocument();
  });

  it("disables previous on the first page and next on the last", async () => {
    const onPageChange = vi.fn();
    const { rerender } = render(
      <Pagination page={0} pageSize={25} total={60} onPageChange={onPageChange} />,
    );
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(onPageChange).toHaveBeenCalledWith(1);

    rerender(<Pagination page={2} pageSize={25} total={60} onPageChange={onPageChange} />);
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  });
});
