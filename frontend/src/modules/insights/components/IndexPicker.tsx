import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { INDEX_CODES, THERMAL_INDEX_CODES, type AnyIndexCode } from "@/api/indices";

// Sourced from the API module rather than restated here. This list was a
// hardcoded copy of migration 0008's original six and never learned about
// ndmi, bsi or msi — so the picker silently offered a stale subset of what the
// platform computes. Re-exported under its old name so callers still work.
//
// The thermal three come from a different product at a much coarser
// resolution, so they sit in their own group rather than being mixed into
// the optical row: the visual separation is the first half of not
// presenting a 100 m reading as though it were a 10 m one. The other half
// is `ThermalResolutionNote`, which the caller renders alongside.
export const SUPPORTED_INDICES = [...INDEX_CODES, ...THERMAL_INDEX_CODES] as const;
export type IndexCode = AnyIndexCode;

interface Props {
  value: IndexCode;
  onChange: (next: IndexCode) => void;
  ariaLabel?: string;
}

/**
 * Index selector, rendered as a chip row rather than a `<select>`.
 *
 * The index set is short enough to show in full, and a dropdown hides the
 * alternatives behind a click: the reader has to already know NDRE exists to
 * go looking for it. Laid out flat, the row doubles as a menu of what the farm
 * can be asked about. Matches TimeSpanChips so the two controls in this card's
 * header read as one family. The row wraps, so growth in the catalog costs a
 * second line rather than the flat layout.
 */
export function IndexPicker({ value, onChange, ariaLabel }: Props): ReactNode {
  const { t } = useTranslation("insights");
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel ?? t("trend.indexPicker.label")}
      className="flex flex-wrap gap-1"
    >
      {SUPPORTED_INDICES.map((code, i) => {
        const active = code === value;
        const firstThermal = i === INDEX_CODES.length;
        return (
          <span key={code} className="contents">
            {firstThermal ? (
              // A visible break, not decoration: everything to its right is
              // 100 m thermal, everything left is 10 m optical.
              <span
                aria-hidden="true"
                data-testid="thermal-group-divider"
                className="mx-1 self-stretch border-l border-ap-line"
              />
            ) : null}
            <button
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => onChange(code)}
              className={
                "rounded-full px-2.5 py-0.5 text-[11px] font-medium transition-colors " +
                (active
                  ? "bg-ap-accent text-white"
                  : "border border-ap-line bg-white text-ap-muted hover:bg-ap-bg")
              }
            >
              {t(`trend.indexPicker.options.${code}`, code.toUpperCase())}
            </button>
          </span>
        );
      })}
    </div>
  );
}
