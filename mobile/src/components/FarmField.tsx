import type { ReactNode } from "react";

import type { FarmScope } from "@/api/me";
import { t, type Lang } from "@/i18n";

/**
 * Which farm this is being filed against.
 *
 * Shared by the capture sheet and the flag screen because they ask the same
 * question for the same reason, and the one-farm rule has to be identical in
 * both or it reads as a bug.
 *
 * **A scout with one farm is not asked, but is still told.** The control is
 * filled in and disabled rather than hidden: what a reading gets attributed to
 * is not visibly wrong afterwards, so it is stated before it is taken. A
 * disabled field that gives the answer beats no field at all — and it dims its
 * frame rather than its text, because it is stating something, not refusing to.
 */
export function FarmField({
  lang,
  farms,
  farmName,
  value,
  disabled,
  onChange,
}: {
  lang: Lang;
  farms: FarmScope[];
  farmName: (farmId: string) => string;
  value: string;
  disabled: boolean;
  onChange: (farmId: string) => void;
}): ReactNode {
  return (
    <>
      <label htmlFor="frm">{t(lang, "record.whichFarm")}</label>
      <select id="frm" value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
        {farms.map((f) => (
          <option key={f.farm_id} value={f.farm_id}>
            {farmName(f.farm_id)}
          </option>
        ))}
      </select>
    </>
  );
}
