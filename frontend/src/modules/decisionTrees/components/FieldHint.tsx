// The one-line explanation under a condition dropdown.
//
// Condition fields are codes — `gdd_cumulative_base10_season`,
// `baseline_deviation`, `worst_z` — and a code is only self-explanatory to
// whoever named it. Authors were picking from lists of identifiers with no way
// to learn what they meant short of asking, which is how you end up with a
// tree branching on surface water when it meant canopy moisture.
//
// Where the platform already stores a description — a tenant's signal
// definition, a crop-attribute definition, the weather-index catalog — the
// caller passes that text straight through, so the hint stays in sync with the
// catalog instead of being restated in the frontend. Everything else comes
// from the `editor.condition.hint.*` i18n block.

import { type ReactNode } from "react";

interface FieldHintProps {
  /** The description. Nothing renders when it is empty or missing — a blank
   *  line under a dropdown is worse than no line. */
  text?: string | null;
  /** Optional unit, appended in parentheses when the text doesn't carry one. */
  unit?: string | null;
}

export function FieldHint({ text, unit }: FieldHintProps): ReactNode {
  const trimmed = text?.trim();
  if (!trimmed) return null;
  const showUnit = unit?.trim() && !trimmed.includes(unit.trim());
  return (
    <span className="text-[11px] leading-snug text-ap-muted">
      {trimmed}
      {showUnit ? ` (${unit!.trim()})` : ""}
    </span>
  );
}
