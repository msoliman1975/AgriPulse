// Pure rules for a crop's canopy size classes.
//
// Size classes are the sibling of the stage calendar: the same ordered,
// bilingual, unique-coded list, minus the advance rule. They fill the block
// canopy-size dropdown, and like the stage ladder they have never been
// authorable — they were set in migrations or not at all.
//
// Mirrors `SizeClasses` / `SizeClass` in backend/app/modules/farms/phenology.py:
// at least one class, unique codes, unique orders, both names required.

import type { SizeClass } from "@/api/crops";

const CODE_RE = /^[a-z0-9][a-z0-9_]*$/;

/** Everything wrong with the list, in the author's words — same contract as
 *  `validateStages`, so a save is refused here before the server's 422. */
export function validateSizeClasses(classes: SizeClass[]): string[] {
  const problems: string[] = [];
  const seen = new Set<string>();
  for (const cls of classes) {
    const name = cls.code || "(unnamed)";
    if (!CODE_RE.test(cls.code)) problems.push(`${name}: code must be lower_snake_case`);
    if (seen.has(cls.code)) problems.push(`${name}: duplicate code`);
    seen.add(cls.code);
    if (!cls.name_en.trim()) problems.push(`${name}: English name is required`);
    if (!cls.name_ar.trim()) problems.push(`${name}: Arabic name is required`);
  }
  if (classes.length === 0) problems.push("A size-class list needs at least one class.");
  return problems;
}
