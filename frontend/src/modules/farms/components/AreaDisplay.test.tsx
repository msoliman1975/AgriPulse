import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { setupTestI18n } from "@/i18n/testing";
import { PrefsProvider } from "@/prefs/PrefsContext";
import { AreaDisplay } from "./AreaDisplay";

describe("AreaDisplay", () => {
  it("formats m² as feddan with one decimal in en", async () => {
    await setupTestI18n("en");
    render(
      <PrefsProvider>
        <AreaDisplay areaM2={42008.3} />
      </PrefsProvider>,
    );
    // 42008.3 / 4200.83 ≈ 10.0
    expect(screen.getByTestId("area-display")).toHaveTextContent("10.0 feddan");
  });

  it("formats area in Arabic with the translated unit and Latin digits", async () => {
    await setupTestI18n("ar");
    render(
      <PrefsProvider>
        <AreaDisplay areaM2={42008.3} />
      </PrefsProvider>,
    );
    expect(screen.getByTestId("area-display")).toHaveTextContent("10.0");
    expect(screen.getByTestId("area-display")).toHaveTextContent("فدان");
  });
});
