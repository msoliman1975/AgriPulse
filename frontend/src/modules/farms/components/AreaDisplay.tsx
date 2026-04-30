import { useTranslation } from "react-i18next";

import { usePrefs } from "@/prefs/PrefsContext";
import { formatArea } from "@/lib/units";

interface Props {
  areaM2: number;
  fractionDigits?: number;
}

/**
 * Displays an area value in the user's preferred unit. Source of truth
 * is m² from the API; the prefs context owns the unit toggle.
 */
export function AreaDisplay({ areaM2, fractionDigits = 1 }: Props): JSX.Element {
  const { unit } = usePrefs();
  const { t, i18n } = useTranslation("farms");
  const { formatted } = formatArea(areaM2, unit, {
    locale: i18n.language,
    fractionDigits,
  });
  return (
    <span data-testid="area-display">
      {formatted} {t(`area.${unit}`)}
    </span>
  );
}
