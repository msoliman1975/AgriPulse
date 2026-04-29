import type { ChangeEvent, ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { SUPPORTED_AREA_UNITS, type AreaUnit, usePrefs } from "@/prefs/PrefsContext";

export function UnitToggle(): ReactNode {
  const { t } = useTranslation("common");
  const { unit, setUnit } = usePrefs();

  const onChange = (event: ChangeEvent<HTMLSelectElement>): void => {
    setUnit(event.target.value as AreaUnit);
  };

  return (
    <label className="inline-flex items-center gap-2 text-sm">
      <span className="sr-only">{t("shell.unitToggle")}</span>
      <select
        aria-label={t("shell.unitToggle")}
        value={unit}
        onChange={onChange}
        className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
      >
        {SUPPORTED_AREA_UNITS.map((u) => (
          <option key={u} value={u}>
            {t(`shell.unit${u.charAt(0).toUpperCase() + u.slice(1)}`)}
          </option>
        ))}
      </select>
    </label>
  );
}
