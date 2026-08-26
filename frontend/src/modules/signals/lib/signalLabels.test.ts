import { describe, expect, it } from "vitest";

import { categoricalLabel, signalName } from "./signalLabels";

const VALUES = ["none", "emitter_blocked", "line_leak"];
const LABELS = ["لا يوجد", "نقاط تنقيط مسدودة", "تسريب في الخط"];

const defn = {
  categorical_values: VALUES,
  categorical_values_ar: LABELS,
};

describe("signalName", () => {
  it("prefers the Arabic name in Arabic", () => {
    expect(signalName("ar", { name: "Irrigation fault", name_ar: "عطل في الري" })).toBe(
      "عطل في الري",
    );
  });

  it("uses English otherwise, and when no Arabic name exists", () => {
    expect(signalName("en", { name: "Irrigation fault", name_ar: "عطل في الري" })).toBe(
      "Irrigation fault",
    );
    expect(signalName("ar", { name: "Irrigation fault", name_ar: null })).toBe("Irrigation fault");
  });
});

describe("categoricalLabel", () => {
  it("maps a stored code to its Arabic label by position", () => {
    expect(categoricalLabel("ar", defn, "emitter_blocked")).toBe("نقاط تنقيط مسدودة");
    expect(categoricalLabel("ar", defn, "none")).toBe("لا يوجد");
  });

  it("returns the stored code unchanged outside Arabic", () => {
    expect(categoricalLabel("en", defn, "emitter_blocked")).toBe("emitter_blocked");
  });

  it("returns the code when there is no Arabic list", () => {
    expect(
      categoricalLabel("ar", { categorical_values: VALUES, categorical_values_ar: null }, "none"),
    ).toBe("none");
  });

  it("returns the code when the two lists disagree in length", () => {
    // The DB CHECK makes this unreachable through the API, but a stale cached
    // payload can still hold an older pair. Showing the code beats showing
    // the wrong label.
    expect(
      categoricalLabel(
        "ar",
        { categorical_values: VALUES, categorical_values_ar: LABELS.slice(0, 2) },
        "line_leak",
      ),
    ).toBe("line_leak");
  });

  it("returns the code when the value is not in the list", () => {
    // An observation recorded before the definition's list was edited.
    expect(categoricalLabel("ar", defn, "no_pressure")).toBe("no_pressure");
  });

  it("returns the code when its Arabic slot is blank", () => {
    expect(
      categoricalLabel(
        "ar",
        { categorical_values: VALUES, categorical_values_ar: ["لا يوجد", "  ", "تسريب"] },
        "emitter_blocked",
      ),
    ).toBe("emitter_blocked");
  });
});
