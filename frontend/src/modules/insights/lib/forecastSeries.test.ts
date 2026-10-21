import { describe, expect, it } from "vitest";

import { splitForecastSeries } from "./forecastSeries";

interface P {
  date: string;
  isForecast: boolean;
  v: number | null;
}

const p = (date: string, v: number | null, isForecast = false): P => ({ date, v, isForecast });
const valueOf = (x: P): number | null => x.v;

describe("splitForecastSeries", () => {
  it("routes each point to the half it belongs to", () => {
    const { rows } = splitForecastSeries(
      [p("2026-06-01", 1), p("2026-06-02", 2), p("2026-06-03", 3, true)],
      valueOf,
    );
    expect(rows.map((r) => r.value)).toEqual([1, 2, null]);
    // 2026-06-02 is the handover and appears in BOTH lines.
    expect(rows.map((r) => r.forecast)).toEqual([null, 2, 3]);
  });

  it("repeats the last observed value so the two lines meet", () => {
    // Without this the dashed segment would start at 06-03 and leave a
    // one-day gap between the halves on the chart.
    const { rows } = splitForecastSeries([p("2026-06-02", 2), p("2026-06-03", 3, true)], valueOf);
    expect(rows[0]).toMatchObject({ value: 2, forecast: 2 });
  });

  it("reports the handover date for the reference line", () => {
    const { lastObservedDate } = splitForecastSeries(
      [p("2026-06-01", 1), p("2026-06-02", 2), p("2026-06-03", 3, true)],
      valueOf,
    );
    expect(lastObservedDate).toBe("2026-06-02");
  });

  it("skips a trailing observed gap when picking the handover", () => {
    // Today's row can exist with a null value before the first observations
    // land; the solid line must end at the last day that actually has one.
    const { lastObservedDate, rows } = splitForecastSeries(
      [p("2026-06-01", 1), p("2026-06-02", null), p("2026-06-03", 3, true)],
      valueOf,
    );
    expect(lastObservedDate).toBe("2026-06-01");
    expect(rows[0].forecast).toBe(1);
  });

  it("draws nothing forward when the series is entirely observed", () => {
    const { hasForecast, rows, lastObservedDate } = splitForecastSeries(
      [p("2026-06-01", 1), p("2026-06-02", 2)],
      valueOf,
    );
    expect(hasForecast).toBe(false);
    expect(lastObservedDate).toBe("2026-06-02");
    // The handover point is still seeded, but with no forecast after it the
    // second line is a single point and the chart simply omits it.
    expect(rows.map((r) => r.forecast)).toEqual([null, 2]);
  });

  it("does not claim a forecast half when every forecast point is null", () => {
    const { hasForecast } = splitForecastSeries(
      [p("2026-06-01", 1), p("2026-06-02", null, true)],
      valueOf,
    );
    expect(hasForecast).toBe(false);
  });

  it("handles an empty series", () => {
    const { rows, lastObservedDate, hasForecast } = splitForecastSeries([] as P[], valueOf);
    expect(rows).toEqual([]);
    expect(lastObservedDate).toBeNull();
    expect(hasForecast).toBe(false);
  });
});
