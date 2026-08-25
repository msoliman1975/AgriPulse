import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { INDEX_CODES, THERMAL_INDEX_CODES } from "@/api/indices";

interface Props {
  value: string;
  onChange: (code: string) => void;
}

/**
 * Index selector shared by the crop-health and field-variability reports.
 *
 * Both reports offered a hardcoded copy of the original six until the shared
 * `INDEX_CODES` landed, and both still stopped at the optical product — so
 * `lst`, `cwsi` and `smi` were computed, stored, and unreachable from any
 * report. They are offered here in their own group rather than merged into
 * one flat list: thermal comes from a different product that most farms do not
 * carry, and a labelled group says that where a mixed list would just look
 * like three more choices that happen to return nothing.
 */
export function ReportIndexSelect({ value, onChange }: Props): ReactNode {
  const { t } = useTranslation("reports");
  return (
    <div className="flex items-center gap-2">
      <span className="label mb-0">{t("cropHealth.index")}</span>
      <select className="input w-auto" value={value} onChange={(e) => onChange(e.target.value)}>
        <optgroup label={t("index.group.optical")}>
          {INDEX_CODES.map((code) => (
            <option key={code} value={code}>
              {code.toUpperCase()}
            </option>
          ))}
        </optgroup>
        <optgroup label={t("index.group.thermal")}>
          {THERMAL_INDEX_CODES.map((code) => (
            <option key={code} value={code}>
              {code.toUpperCase()}
            </option>
          ))}
        </optgroup>
      </select>
    </div>
  );
}
