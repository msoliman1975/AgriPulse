import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Crop } from "@/api/crops";
import { setupTestI18n } from "@/i18n/testing";

import { defaultAdvance, validateStages } from "@/modules/admin/lib/phenologyStages";

import { PhenologyStagesEditor } from "./PhenologyStagesEditor";

const MANGO: Crop = {
  id: "c1",
  code: "mango",
  name_en: "Mango",
  name_ar: "مانجو",
  scientific_name: null,
  category: "fruit_tree",
  is_perennial: true,
  default_growing_season_days: null,
  relevant_indices: ["ndvi"],
  classification_depth: "variety_strain",
  is_active: true,
  gdd_base_temp_c: null,
  phenology_stages: {
    stages: [
      {
        code: "flowering",
        name_en: "Flowering",
        name_ar: "إزهار",
        order: 2,
        advance: { mode: "calendar_doy", start_doy: "02-01", end_doy: "03-31" },
      },
      {
        code: "pre_flowering",
        name_en: "Pre-flowering",
        name_ar: "ما قبل الإزهار",
        order: 1,
        advance: { mode: "calendar_doy", start_doy: "12-01", end_doy: "01-31" },
      },
    ],
  },
};

const POTATO: Crop = {
  ...MANGO,
  id: "c2",
  code: "potato",
  name_en: "Potato",
  category: "vegetable",
  is_perennial: false,
  phenology_stages: null,
};

const stage = (over: Record<string, unknown> = {}) => ({
  code: "flowering",
  name_en: "Flowering",
  name_ar: "إزهار",
  order: 1,
  advance: { mode: "calendar_doy", start_doy: "02-01", end_doy: "03-31" },
  ...over,
});

describe("validateStages", () => {
  it("accepts a well-formed perennial calendar", () => {
    expect(validateStages([stage() as never], MANGO)).toEqual([]);
  });

  it("rejects a calendar mode on an annual and vice versa", () => {
    // A perennial has no planting date to count from; an annual has no fixed
    // calendar window. The backend enforces this, so the form should too.
    expect(validateStages([stage() as never], POTATO).join()).toMatch(/not allowed for an annual/);
    const daysStage = stage({ advance: { mode: "days_from_planting", start_day: 0, end_day: 30 } });
    expect(validateStages([daysStage as never], MANGO).join()).toMatch(
      /not allowed for a perennial/,
    );
  });

  it("requires degree-day stages to have a base temperature on the crop", () => {
    const gdd = stage({ advance: { mode: "gdd_from_planting", start_gdd: 0, end_gdd: 500 } });
    expect(validateStages([gdd as never], POTATO).join()).toMatch(/GDD base temperature/);
    const withBase = { ...POTATO, gdd_base_temp_c: "10" };
    expect(validateStages([gdd as never], withBase)).toEqual([]);
  });

  it("catches duplicate codes", () => {
    const dupes = [stage(), stage()] as never[];
    expect(validateStages(dupes, MANGO).join()).toMatch(/duplicate code/);
  });

  it("requires ranges to run forwards", () => {
    const bad = stage({ advance: { mode: "days_from_planting", start_day: 30, end_day: 10 } });
    expect(validateStages([bad as never], POTATO).join()).toMatch(/end day must be after/);
  });

  it("allows a calendar window that wraps past new year", () => {
    // 12-01 -> 01-31 is a real perennial window, so it must not be flagged.
    const wrap = stage({ advance: { mode: "calendar_doy", start_doy: "12-01", end_doy: "01-31" } });
    expect(validateStages([wrap as never], MANGO)).toEqual([]);
  });

  it("rejects malformed dates and codes", () => {
    const badDoy = stage({
      advance: { mode: "calendar_doy", start_doy: "3-15", end_doy: "05-31" },
    });
    expect(validateStages([badDoy as never], MANGO).join()).toMatch(/MM-DD/);
    expect(validateStages([stage({ code: "Not Valid" }) as never], MANGO).join()).toMatch(
      /lower_snake_case/,
    );
  });

  it("treats an empty calendar as invalid", () => {
    expect(validateStages([], MANGO).join()).toMatch(/at least one stage/);
  });
});

describe("defaultAdvance", () => {
  it("seeds a usable rule for each mode", () => {
    expect(defaultAdvance("manual")).toEqual({ mode: "manual" });
    expect(defaultAdvance("calendar_doy")).toMatchObject({ start_doy: "01-01" });
    expect(defaultAdvance("days_from_planting")).toMatchObject({ start_day: 0, end_day: 30 });
    expect(defaultAdvance("gdd_from_planting")).toMatchObject({ start_gdd: 0, end_gdd: 500 });
  });
});

describe("<PhenologyStagesEditor>", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
  });

  it("lists existing stages in calendar order", () => {
    render(
      <PhenologyStagesEditor crop={MANGO} busy={false} onCancel={() => {}} onSave={() => {}} />,
    );
    const codes = screen.getAllByLabelText("Code").map((i) => (i as HTMLInputElement).value);
    // Stored order 1 then 2, regardless of array order.
    expect(codes).toEqual(["pre_flowering", "flowering"]);
  });

  it("offers only the modes the crop's cycle allows", () => {
    render(
      <PhenologyStagesEditor crop={MANGO} busy={false} onCancel={() => {}} onSave={() => {}} />,
    );
    const options = [...screen.getAllByLabelText(/Advances by/)[0].querySelectorAll("option")].map(
      (o) => o.getAttribute("value"),
    );
    expect(options).toEqual(["calendar_doy", "manual"]);
  });

  it("warns when a crop has no calendar at all", () => {
    render(
      <PhenologyStagesEditor crop={POTATO} busy={false} onCancel={() => {}} onSave={() => {}} />,
    );
    // The state 20 of 23 crops are in, and the reason their trees never fire.
    expect(screen.getByText(/never advance a growth stage/)).toBeInTheDocument();
  });

  it("renumbers order from position on save", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();
    render(<PhenologyStagesEditor crop={MANGO} busy={false} onCancel={() => {}} onSave={onSave} />);

    await user.click(screen.getAllByLabelText("Move later")[0]);
    await user.click(screen.getByRole("button", { name: "Save calendar" }));

    // Position is the order — a human should never maintain a number whose
    // only job is to be unique and ascending.
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(
      onSave.mock.calls[0][0].map((s: { code: string; order: number }) => [s.code, s.order]),
    ).toEqual([
      ["flowering", 1],
      ["pre_flowering", 2],
    ]);
  });

  it("refuses to save an invalid calendar and says why", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();
    render(<PhenologyStagesEditor crop={MANGO} busy={false} onCancel={() => {}} onSave={onSave} />);

    await user.clear(screen.getAllByLabelText("Code")[0]);
    await user.click(screen.getByRole("button", { name: "Save calendar" }));

    expect(onSave).not.toHaveBeenCalled();
    expect(await screen.findByRole("alert")).toHaveTextContent(/lower_snake_case/);
  });
});
