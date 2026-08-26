import type { ReactNode } from "react";

import type { FarmScope } from "@/api/me";
import { t, type Lang } from "@/i18n";

/**
 * Which farm's work is on screen, and how much of it there is.
 *
 * One control, one place, on every farm-scoped screen. It replaced three
 * separate answers to the same question: a tile level on Tasks that had to be
 * backed out of to change farm, a chip on Records rows, and a dropdown in the
 * capture sheet that was answered from scratch every time.
 *
 * **The count is the point.** A rail without numbers tells a scout which farms
 * exist, which they already know. With them it says where the day starts,
 * before anything is opened.
 *
 * **A scout with one farm never sees it.** Not a disabled rail, not a rail of
 * one: `null`, and the farm is stated once in the header instead. A choice of
 * one is not a choice, and rendering it would put a control on screen whose
 * only possible use is to confirm what is already true.
 */

/** The farm filter meaning "every farm at once". Empty rather than a sentinel
 *  word, so it can never collide with a real farm id. */
export const ALL_FARMS = "";

export interface FarmCount {
  /** Null while the work is still loading: the pill is tappable before the
   *  number lands, and a zero shown in the meantime would be a lie. */
  count: number | null;
  /**
   * Worst thing inside, one level coarser than a block tile — see `farmTone`.
   * Red is reserved for work already late, because a farm is dozens of blocks
   * and "something critical here" is the normal state.
   */
  tone: "" | "warn" | "crit";
  /** This farm's fetch threw. Distinct from a null count: one is "not yet",
   *  the other is "not at all", and they need different marks. */
  failed?: boolean;
}

export function FarmRail({
  lang,
  farms,
  farmName,
  value,
  counts,
  onChange,
}: {
  lang: Lang;
  /** Every farm this scout is granted. Never empty — the caller handles that. */
  farms: FarmScope[];
  farmName: (farmId: string) => string;
  /** The chosen farm id, or `ALL_FARMS`. */
  value: string;
  /** Per farm id. A farm missing from this map counts as still loading. */
  counts: Record<string, FarmCount>;
  onChange: (farmId: string) => void;
}): ReactNode {
  if (farms.length < 2) return null;

  const all = farms.map((f) => counts[f.farm_id]);
  // Still in flight is not the same as asked and refused. A farm that failed
  // has finished — it is named on the warning line and marked on its own pill
  // — so the total adds up what did answer rather than waiting for ever. This
  // used to test `known.length === farms.length`, which meant one permanently
  // broken farm left the "All farms" pill showing loading dots all day.
  const pending = all.some((c) => c === undefined || (c.count === null && !c.failed));
  const known = all.filter((c): c is FarmCount => c !== undefined && c.count !== null);
  const total = pending ? null : known.reduce((n, c) => n + (c.count ?? 0), 0);
  // Any farm late makes the whole-set pill late, which is the same rule one
  // level down and the reason this pill is worth a tone at all.
  const allTone = known.some((c) => c.tone === "crit")
    ? "crit"
    : known.some((c) => c.tone === "warn")
      ? "warn"
      : "";

  return (
    <div className="rail" role="tablist" aria-label={t(lang, "rail.label")}>
      <Pill
        label={t(lang, "rail.allFarms")}
        count={total}
        tone={allTone}
        on={value === ALL_FARMS}
        onPick={() => onChange(ALL_FARMS)}
      />
      {farms.map((f) => {
        const c = counts[f.farm_id];
        return (
          <Pill
            key={f.farm_id}
            label={farmName(f.farm_id)}
            count={c?.count ?? null}
            tone={c?.tone ?? ""}
            failed={c?.failed === true}
            failedLabel={t(lang, "rail.failed")}
            on={value === f.farm_id}
            onPick={() => onChange(f.farm_id)}
          />
        );
      })}
    </div>
  );
}

function Pill({
  label,
  count,
  tone,
  failed = false,
  failedLabel,
  on,
  onPick,
}: {
  label: string;
  count: number | null;
  tone: string;
  failed?: boolean;
  failedLabel?: string;
  on: boolean;
  onPick: () => void;
}): ReactNode {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={on}
      className={`pill${on ? " on" : ""}${count === 0 && !failed ? " empty" : ""}`}
      onClick={onPick}
    >
      {/* A farm name is tenant-written and may be in either script. `auto` lets
          each label find its own direction, so an Arabic farm name on an
          English screen is not laid out backwards. */}
      <span className="nm" dir="auto">
        {label}
      </span>
      {failed ? (
        <span className="n bad" title={failedLabel} aria-label={failedLabel}>
          !
        </span>
      ) : count === null ? (
        // Three dots rather than a spinner: the pill is already tappable, and
        // a spinner reads as "wait", which is the wrong instruction.
        <span className="dots" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
      ) : (
        <span className={`n${tone ? ` ${tone}` : ""}`}>{count}</span>
      )}
    </button>
  );
}
