import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { INDEX_CODES, type IndexCode } from "@/api/indices";

// Sourced from the API module rather than restated here. This list was a
// hardcoded copy of migration 0008's original six and never learned about
// ndmi, bsi or msi — so the picker silently offered a stale subset of what the
// platform computes. Re-exported under its old name so callers still work.
export { INDEX_CODES as SUPPORTED_INDICES, type IndexCode };

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
      {INDEX_CODES.map((code) => {
        const active = code === value;
        return (
          <button
            key={code}
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
        );
      })}
    </div>
  );
}
