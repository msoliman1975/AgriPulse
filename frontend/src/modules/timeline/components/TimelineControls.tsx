// The header bar: scope, window, index.
//
// Live controls rather than a set-up wizard. Changing any of them
// re-reads and keeps the play head on the same date where that date still
// exists, so a reader can widen the window or switch index without losing
// their place.

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { INDEX_CODES, THERMAL_INDEX_CODES, type AnyIndexCode } from "@/api/indices";
import { MAX_WINDOW_DAYS } from "../constants";

export interface BlockOption {
  id: string;
  label: string;
}

interface Props {
  blocks: readonly BlockOption[];
  blockId: string | null;
  onBlockChange: (blockId: string | null) => void;
  from: string;
  to: string;
  onWindowChange: (from: string, to: string) => void;
  index: AnyIndexCode;
  onIndexChange: (index: AnyIndexCode) => void;
  /** Set when the chosen window is wider than the API will answer. */
  windowError: string | null;
}

const FIELD_CLASS =
  "rounded border border-ap-line bg-ap-panel px-2 py-1.5 text-sm text-ap-ink " +
  "focus:outline-none focus:ring-2 focus:ring-ap-primary/40";

export function TimelineControls({
  blocks,
  blockId,
  onBlockChange,
  from,
  to,
  onWindowChange,
  index,
  onIndexChange,
  windowError,
}: Props): ReactNode {
  const { t } = useTranslation("timeline");

  return (
    <div className="flex flex-wrap items-end gap-3">
      <label className="flex flex-col gap-1">
        <span className="text-meta font-medium text-ap-muted">{t("controls.scope")}</span>
        <select
          className={FIELD_CLASS}
          value={blockId ?? ""}
          onChange={(e) => onBlockChange(e.target.value || null)}
        >
          {/* Whole farm first, because it is the default and because the
              phenology lane only exists below it — see the hint. */}
          <option value="">{t("controls.wholeFarm")}</option>
          {blocks.map((b) => (
            <option key={b.id} value={b.id}>
              {b.label}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-meta font-medium text-ap-muted">{t("controls.from")}</span>
        <input
          type="date"
          className={FIELD_CLASS}
          value={from}
          max={to}
          onChange={(e) => onWindowChange(e.target.value, to)}
        />
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-meta font-medium text-ap-muted">{t("controls.to")}</span>
        <input
          type="date"
          className={FIELD_CLASS}
          value={to}
          min={from}
          onChange={(e) => onWindowChange(from, e.target.value)}
        />
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-meta font-medium text-ap-muted">{t("controls.index")}</span>
        <select
          className={FIELD_CLASS}
          value={index}
          onChange={(e) => onIndexChange(e.target.value as AnyIndexCode)}
        >
          {/* Optical and thermal are separate products with disjoint bands.
              Grouping them says so, rather than offering thirteen entries as
              if a farm could always draw any of them. */}
          <optgroup label={t("controls.optical")}>
            {INDEX_CODES.map((code) => (
              <option key={code} value={code}>
                {code.toUpperCase()}
              </option>
            ))}
          </optgroup>
          <optgroup label={t("controls.thermal")}>
            {THERMAL_INDEX_CODES.map((code) => (
              <option key={code} value={code}>
                {code.toUpperCase()}
              </option>
            ))}
          </optgroup>
        </select>
      </label>

      <div className="min-w-0 flex-1 pb-1.5 text-meta text-ap-muted">
        {windowError ? (
          <p className="text-ap-crit">{windowError}</p>
        ) : (
          <p>
            {blockId === null ? t("controls.hintFarm") : t("controls.hintBlock")}{" "}
            {t("controls.hintWindow", { days: MAX_WINDOW_DAYS })}
          </p>
        )}
      </div>
    </div>
  );
}
