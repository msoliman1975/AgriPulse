import type { AreaUnit } from "@/prefs/PrefsContext";

// Conversion constants per ARCHITECTURE.md § 12 and prompt-02 § "Units".
// Keep in lock-step with backend `app/modules/farms/service.py`.
export const M2_PER_FEDDAN = 4200.83;
export const M2_PER_ACRE = 4046.86;
export const M2_PER_HECTARE = 10000;

export function m2ToUnit(areaM2: number, unit: AreaUnit): number {
  switch (unit) {
    case "feddan":
      return areaM2 / M2_PER_FEDDAN;
    case "acre":
      return areaM2 / M2_PER_ACRE;
    case "hectare":
      return areaM2 / M2_PER_HECTARE;
  }
}

export function unitToM2(value: number, unit: AreaUnit): number {
  switch (unit) {
    case "feddan":
      return value * M2_PER_FEDDAN;
    case "acre":
      return value * M2_PER_ACRE;
    case "hectare":
      return value * M2_PER_HECTARE;
  }
}

export interface FormatAreaOptions {
  locale?: string;
  fractionDigits?: number;
}

export function formatAreaValue(value: number, options: FormatAreaOptions = {}): string {
  const { locale = "en", fractionDigits = 1 } = options;
  // ar-EG with western digits per ARCHITECTURE.md § 11. i18next gives us
  // 'en' or 'ar'; map to BCP 47 locales explicitly so grouping is stable.
  const bcp47 = locale.startsWith("ar") ? "ar-EG" : "en-US";
  return new Intl.NumberFormat(bcp47, {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
    useGrouping: true,
    // Force Latin digits in Arabic UI per ARCHITECTURE.md § 11.
    numberingSystem: "latn",
  }).format(value);
}

export function formatArea(
  areaM2: number,
  unit: AreaUnit,
  options: FormatAreaOptions = {},
): { value: number; formatted: string; unit: AreaUnit } {
  const value = m2ToUnit(areaM2, unit);
  return { value, formatted: formatAreaValue(value, options), unit };
}
