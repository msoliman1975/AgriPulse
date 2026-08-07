import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

// V1 hardcoded list mirrors backend migration 0008_seed_imagery_catalog.
// When `/v1/indices/catalog` ships, fetch dynamically with react-query
// and fall back to this list while loading.
export const SUPPORTED_INDICES = ["ndvi", "ndwi", "evi", "savi", "ndre", "gndvi"] as const;
export type IndexCode = (typeof SUPPORTED_INDICES)[number];

interface Props {
  value: IndexCode;
  onChange: (next: IndexCode) => void;
  ariaLabel?: string;
}

/**
 * Index selector, rendered as a chip row rather than a `<select>`.
 *
 * Six indices is a short enough list to show in full, and a dropdown hides
 * the alternatives behind a click: the reader has to already know NDRE
 * exists to go looking for it. Laid out flat, the row doubles as a menu of
 * what the farm can be asked about. Matches TimeSpanChips so the two
 * controls in this card's header read as one family.
 */
export function IndexPicker({ value, onChange, ariaLabel }: Props): ReactNode {
  const { t } = useTranslation("insights");
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel ?? t("trend.indexPicker.label")}
      className="flex flex-wrap gap-1"
    >
      {SUPPORTED_INDICES.map((code) => {
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
