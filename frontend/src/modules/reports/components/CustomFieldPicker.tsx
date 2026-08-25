import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { CustomFieldDef } from "@/api/reports";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { useReportCustomFields } from "@/queries/reports";

import { fieldLabel, fieldUnit } from "../customFields";

/** Backend cap (reports/custom_fields.py MAX_CUSTOM_FIELDS). Restated here so
 * the picker can stop the user at the limit instead of letting them tick a
 * thirteenth column that silently never appears. */
const MAX_FIELDS = 12;

interface Props {
  farmId: string;
  /** Picked column keys, in display order. */
  value: readonly string[];
  onChange: (keys: string[]) => void;
}

/**
 * Column picker for tenant-defined report columns.
 *
 * Two groups, because the two catalogs answer different questions and a
 * merged list makes "Brix" and "Brix reading" look like duplicates when one is
 * a crop attribute recorded at assignment time and the other is a signal
 * logged on a scouting visit. The group heading is what tells them apart.
 *
 * Renders nothing at all when the farm offers no custom fields: an empty
 * "Add columns" control on a tenant that has authored none is a dead end that
 * every reader has to click once to learn is a dead end.
 */
export function CustomFieldPicker({ farmId, value, onChange }: Props): ReactNode {
  const { t, i18n } = useTranslation("reports");
  const { data } = useReportCustomFields(farmId);
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  // Close on an outside click or Escape. Both, not one: a keyboard user who
  // opened the panel with the button has no pointer to click away with.
  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent): void => {
      if (!wrapRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const groups = useMemo(() => {
    const all = data?.fields ?? [];
    return [
      { source: "crop_attribute", fields: all.filter((f) => f.source === "crop_attribute") },
      { source: "signal", fields: all.filter((f) => f.source === "signal") },
    ].filter((g) => g.fields.length > 0);
  }, [data]);

  const selected = useMemo(() => new Set(value), [value]);

  if (groups.length === 0) return null;

  const toggle = (def: CustomFieldDef): void => {
    if (selected.has(def.key)) {
      onChange(value.filter((k) => k !== def.key));
      return;
    }
    if (value.length >= MAX_FIELDS) return;
    // Append rather than insert in catalog order: the order the user ticked
    // them in is the order the columns appear, which is the only ordering
    // control this picker offers.
    onChange([...value, def.key]);
  };

  const atCap = value.length >= MAX_FIELDS;

  return (
    <div ref={wrapRef} className="print-hide relative">
      <Button
        variant="ghost"
        className="text-xs"
        aria-expanded={open}
        aria-haspopup="true"
        onClick={() => setOpen((o) => !o)}
      >
        {value.length > 0
          ? t("customFields.buttonCount", { count: value.length })
          : t("customFields.button")}
      </Button>

      {open ? (
        <Card
          role="group"
          aria-label={t("customFields.button")}
          noPadding
          className="absolute z-20 mt-1 max-h-80 w-72 overflow-y-auto p-2 shadow-lg"
        >
          <div className="flex items-center justify-between px-1 pb-1">
            <span className="text-[11px] text-ap-muted">
              {t("customFields.selectedOf", { count: value.length, max: MAX_FIELDS })}
            </span>
            {value.length > 0 ? (
              <button
                type="button"
                className="text-[11px] text-ap-accent hover:underline"
                onClick={() => onChange([])}
              >
                {t("customFields.clear")}
              </button>
            ) : null}
          </div>

          {groups.map((group) => (
            <div key={group.source} className="mt-1">
              <p className="px-1 py-1 text-[10px] font-semibold uppercase tracking-wide text-ap-muted">
                {t(`customFields.source.${group.source}`)}
              </p>
              {group.fields.map((def) => {
                const checked = selected.has(def.key);
                const unit = fieldUnit(def, i18n.language);
                return (
                  <label
                    key={def.key}
                    className={
                      "flex cursor-pointer items-center gap-2 rounded px-1 py-1 text-xs hover:bg-ap-bg " +
                      (!checked && atCap ? "cursor-not-allowed opacity-50" : "")
                    }
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={!checked && atCap}
                      onChange={() => toggle(def)}
                    />
                    <span className="min-w-0 flex-1 truncate text-ap-ink" dir="auto">
                      {fieldLabel(def, i18n.language)}
                      {unit ? <span className="text-ap-muted"> ({unit})</span> : null}
                    </span>
                  </label>
                );
              })}
            </div>
          ))}
        </Card>
      ) : null}
    </div>
  );
}
