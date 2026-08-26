// Display labels for a signal definition and its categorical values.
//
// A signal definition carries parallel English and Arabic columns since
// public migration 0074. `categorical_values_ar` is a parallel array: same
// length, same order, one Arabic label per code, and a CHECK in the DB keeps
// the lengths equal. These helpers are the only place that pairing is read,
// so a mismatched or missing Arabic array degrades to the stored code in one
// place rather than in every screen.

import type { SignalDefinition } from "@/api/signals";
import { localizedName } from "@/lib/localizedField";

type NamedDefinition = Pick<SignalDefinition, "name" | "name_ar">;
type CategoricalDefinition = Pick<SignalDefinition, "categorical_values" | "categorical_values_ar">;

/** The definition's name in the reader's language. */
export function signalName(lang: string | undefined, d: NamedDefinition): string {
  return localizedName(lang, d.name, d.name_ar);
}

/**
 * The label for one stored categorical value.
 *
 * The stored value is the English code; the Arabic label is found by
 * position, because the value itself is what every observation row, decision
 * tree condition and CSV import holds. Returns the code unchanged when there
 * is no Arabic list, when the lists disagree in length, or when the value is
 * not in the list at all (an older observation of a since-edited definition).
 */
export function categoricalLabel(
  lang: string | undefined,
  d: CategoricalDefinition,
  value: string,
): string {
  if (lang !== "ar") return value;
  const values = d.categorical_values;
  const labels = d.categorical_values_ar;
  if (!values || !labels || values.length !== labels.length) return value;
  const i = values.indexOf(value);
  if (i < 0) return value;
  const label = labels[i];
  return label && label.trim() !== "" ? label : value;
}
