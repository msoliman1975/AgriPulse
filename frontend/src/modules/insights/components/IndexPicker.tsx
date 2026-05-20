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

export function IndexPicker({ value, onChange, ariaLabel }: Props): ReactNode {
  const { t } = useTranslation("insights");
  return (
    <label className="flex items-center gap-2 text-[11px] text-ap-muted">
      <span>{t("trend.indexPicker.label")}</span>
      <select
        aria-label={ariaLabel ?? t("trend.indexPicker.label")}
        value={value}
        onChange={(e) => onChange(e.target.value as IndexCode)}
        className="rounded-md border border-ap-line bg-white px-2 py-0.5 text-[11px] font-medium text-ap-ink"
      >
        {SUPPORTED_INDICES.map((code) => (
          <option key={code} value={code}>
            {t(`trend.indexPicker.options.${code}`, code.toUpperCase())}
          </option>
        ))}
      </select>
    </label>
  );
}
