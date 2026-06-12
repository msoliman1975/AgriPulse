import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
  fromDateInput,
  presetRange,
  toDateInput,
  type DateRange,
} from "../dateRange";

interface Props {
  value: DateRange;
  onChange: (range: DateRange) => void;
}

/**
 * Shared report date-range control: two day inputs plus quick presets
 * (last 30 / 90 days). Marked `print-hide` so it drops out of the
 * print-to-PDF output. Emits inclusive ISO bounds.
 */
export function DateRangePicker({ value, onChange }: Props): ReactNode {
  const { t } = useTranslation("reports");

  return (
    <div className="print-hide flex flex-wrap items-end gap-3">
      <label className="flex flex-col">
        <span className="label">{t("range.from")}</span>
        <input
          type="date"
          className="input w-auto"
          value={toDateInput(value.since)}
          max={toDateInput(value.until)}
          onChange={(e) =>
            e.target.value && onChange({ ...value, since: fromDateInput(e.target.value, "start") })
          }
        />
      </label>
      <label className="flex flex-col">
        <span className="label">{t("range.to")}</span>
        <input
          type="date"
          className="input w-auto"
          value={toDateInput(value.until)}
          min={toDateInput(value.since)}
          onChange={(e) =>
            e.target.value && onChange({ ...value, until: fromDateInput(e.target.value, "end") })
          }
        />
      </label>
      <div className="flex items-center gap-1.5">
        <button type="button" className="btn btn-ghost text-xs" onClick={() => onChange(presetRange(30))}>
          {t("range.last30")}
        </button>
        <button type="button" className="btn btn-ghost text-xs" onClick={() => onChange(presetRange(90))}>
          {t("range.last90")}
        </button>
      </div>
    </div>
  );
}
