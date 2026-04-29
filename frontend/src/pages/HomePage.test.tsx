import { render, screen } from "@testing-library/react";
import { describe, expect, it, beforeEach } from "vitest";

import { setupTestI18n } from "@/i18n/testing";
import { HomePage } from "./HomePage";

describe("HomePage", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
  });

  it("renders the welcome heading in English (LTR)", async () => {
    await setupTestI18n("en");
    render(<HomePage />);
    expect(screen.getByRole("heading", { name: "Welcome" })).toBeInTheDocument();
    expect(document.documentElement.getAttribute("dir")).toBe("ltr");
  });

  it("renders the welcome heading in Arabic (RTL)", async () => {
    await setupTestI18n("ar");
    render(<HomePage />);
    expect(screen.getByRole("heading", { name: "مرحبًا" })).toBeInTheDocument();
    expect(document.documentElement.getAttribute("dir")).toBe("rtl");
  });
});
