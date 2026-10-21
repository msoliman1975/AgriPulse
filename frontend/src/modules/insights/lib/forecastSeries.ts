/**
 * Splitting a weather-index series into its observed and forecast halves.
 *
 * The timeseries endpoint returns one date-ascending list in which the points
 * past today carry `is_forecast`. Drawing that list as a single line would
 * pass a five-day prediction off as measured data, which is the whole reason
 * the flag exists — so every chart splits it into two keys and gives the
 * forward half its own (dashed) stroke.
 *
 * The split is done here rather than per chart because the join between the
 * halves is easy to get subtly wrong: the last observed point has to appear in
 * BOTH series, otherwise recharts draws the dashed segment starting a day
 * later and the two lines float apart with a visible notch between them.
 */

export interface ForecastSplitInput {
  date: string;
  isForecast: boolean;
}

export interface ForecastSplit<T> {
  /** Chart rows: every input field, plus `value` (observed) and `forecast`. */
  rows: Array<T & { value: number | null; forecast: number | null }>;
  /**
   * Last day with an observed value — where "now" sits on the axis, and where
   * a reference line marking the handover belongs. Null when the series is
   * entirely forecast or entirely empty.
   */
  lastObservedDate: string | null;
  /** Whether any forecast point survived, i.e. whether to draw the second line. */
  hasForecast: boolean;
}

export function splitForecastSeries<T extends ForecastSplitInput>(
  points: readonly T[],
  valueOf: (point: T) => number | null,
): ForecastSplit<T> {
  let lastObserved = -1;
  for (let i = points.length - 1; i >= 0; i -= 1) {
    const p = points[i];
    if (!p.isForecast && valueOf(p) !== null) {
      lastObserved = i;
      break;
    }
  }

  const rows = points.map((p, i) => ({
    ...p,
    value: p.isForecast ? null : valueOf(p),
    // The handover point belongs to both lines: as the last value of the
    // solid one and the first of the dashed one. Without it the forecast
    // line begins one day adrift of where observation stopped.
    forecast: p.isForecast || i === lastObserved ? valueOf(p) : null,
  }));

  return {
    rows,
    lastObservedDate: lastObserved >= 0 ? points[lastObserved].date : null,
    hasForecast: points.some((p) => p.isForecast && valueOf(p) !== null),
  };
}
