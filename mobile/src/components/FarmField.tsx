import { useState, type ReactNode } from "react";

import type { FarmScope } from "@/api/me";
import { t, type Lang } from "@/i18n";

/**
 * Which farm this is being filed against.
 *
 * Shared by the capture sheet and the flag screen because they ask the same
 * question for the same reason, and the rules below have to be identical in
 * both or they read as a bug.
 *
 * **It is a statement first and a question second.** The farm rail on the
 * screen behind this one has already been answered, so re-asking it here was
 * a second answer to a settled question — and the commonest way to get a
 * reading filed against the wrong farm was to leave that dropdown alone.
 * So a farm already chosen is *stated*, with one control to change it.
 *
 * Three shapes, in order of how often they happen:
 *
 *   * **One farm** — not asked. The control is filled in and disabled rather
 *     than hidden: what a reading gets attributed to is not visibly wrong
 *     afterwards, so it is stated before it is taken. It dims its frame rather
 *     than its text, because it is stating something, not refusing to.
 *   * **A farm inherited from the rail** — stated, with "Change" beside it.
 *   * **No farm yet** — the rail is on "All farms", so this is the one place
 *     in the app that still asks outright. It opens on the picker with nothing
 *     preselected, because a default here is a wrong answer waiting to be
 *     accepted.
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
  /** Empty means no farm settled yet — see the third shape above. */
  value: string;
  disabled: boolean;
  onChange: (farmId: string) => void;
}): ReactNode {
  const [editing, setEditing] = useState(false);

  // A farm is settled and changeable: state it. Not for a one-farm scout —
  // there is nothing to change, so the disabled control below says it better.
  if (!disabled && value !== "" && !editing) {
    return (
      <div className="filing">
        <span className="lbl">{t(lang, "record.filingTo")}</span>
        <span className="nm" dir="auto">
          {farmName(value)}
        </span>
        <button type="button" className="link" onClick={() => setEditing(true)}>
          {t(lang, "record.changeFarm")}
        </button>
      </div>
    );
  }

  return (
    <>
      <label htmlFor="frm">{t(lang, "record.whichFarm")}</label>
      <select
        id="frm"
        value={value}
        disabled={disabled}
        onChange={(e) => {
          onChange(e.target.value);
          setEditing(false);
        }}
      >
        {/* Only while nothing is settled. Kept out of the list once a farm is
            chosen, so re-opening the picker cannot land back on "nothing". */}
        {value === "" ? <option value="">{t(lang, "record.pickFarm")}</option> : null}
        {farms.map((f) => (
          <option key={f.farm_id} value={f.farm_id}>
            {farmName(f.farm_id)}
          </option>
        ))}
      </select>
    </>
  );
}
