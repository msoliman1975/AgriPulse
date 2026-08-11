import clsx from "clsx";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "./Button";
import { FilterChip } from "./FilterChip";

export interface FilterOption {
  value: string;
  label: string;
}

export interface FilterAxis {
  key: string;
  label: string;
  options: readonly FilterOption[];
  /** Single-select axes collapse to at most one value. Defaults to multi. */
  single?: boolean;
}

/** axis key -> selected values. Absent or empty means "any". */
export type FilterValues = Record<string, readonly string[]>;

interface ToolbarProps {
  search?: {
    value: string;
    onChange: (value: string) => void;
    placeholder?: string;
    label?: string;
  };
  /** The one high-traffic axis, kept inline and one click away. */
  chips?: ReactNode;
  /** Everything else — goes behind the counted popover. */
  axes?: readonly FilterAxis[];
  /**
   * `popover` (default) puts every axis behind one counted "Filters" button.
   * `inline` gives each axis its own labelled dropdown — use it when there
   * are only a few axes and each is high-traffic, so the axis a value belongs
   * to is readable without opening anything.
   */
  axisLayout?: "popover" | "inline";
  values?: FilterValues;
  onValuesChange?: (next: FilterValues) => void;
  /** Renders "Showing N of M" beside the applied-filter chips. */
  resultCount?: { shown: number; total: number };
  right?: ReactNode;
  className?: string;
}

function countActive(values: FilterValues | undefined): number {
  if (!values) return 0;
  return Object.values(values).reduce((sum, list) => sum + (list?.length ?? 0), 0);
}

/*
 * Decision 2C — chips for the axis people actually toggle, a counted popover
 * for the rest, and applied filters echoed back as removable chips.
 *
 * Pure chips don't survive four axes (`/decision-trees` wraps to two lines and
 * gives no hint that "Egypt" and "Sandy" belong to different axes). Pure
 * selects make a list page read as a settings form. The applied-filter row
 * also carries the result count, which every index page in the app is
 * currently missing.
 */
export function Toolbar({
  search,
  chips,
  axes,
  axisLayout = "popover",
  values,
  onValuesChange,
  resultCount,
  right,
  className,
}: ToolbarProps): ReactNode {
  const { t } = useTranslation("common");
  const activeCount = countActive(values);
  const hasAxes = Boolean(axes && axes.length > 0);

  const applied = (axes ?? []).flatMap((axis) =>
    (values?.[axis.key] ?? []).map((value) => ({
      axisKey: axis.key,
      value,
      label: axis.options.find((o) => o.value === value)?.label ?? value,
    })),
  );

  function toggle(axis: FilterAxis, value: string): void {
    if (!onValuesChange) return;
    const current = values?.[axis.key] ?? [];
    const isOn = current.includes(value);
    const next = axis.single
      ? isOn
        ? []
        : [value]
      : isOn
        ? current.filter((v) => v !== value)
        : [...current, value];
    onValuesChange({ ...values, [axis.key]: next });
  }

  function remove(axisKey: string, value: string): void {
    if (!onValuesChange) return;
    onValuesChange({
      ...values,
      [axisKey]: (values?.[axisKey] ?? []).filter((v) => v !== value),
    });
  }

  function clearAll(): void {
    onValuesChange?.({});
  }

  return (
    <div className={clsx("flex flex-col gap-3", className)}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          {search ? (
            <input
              type="search"
              value={search.value}
              onChange={(e) => search.onChange(e.target.value)}
              placeholder={search.placeholder ?? t("toolbar.search")}
              aria-label={search.label ?? search.placeholder ?? t("toolbar.search")}
              className="w-full min-w-[12rem] rounded-md border border-ap-line bg-ap-panel px-3 py-1.5 text-sm text-ap-ink shadow-sm focus:border-ap-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-ap-primary sm:w-64"
            />
          ) : null}
          {chips}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {right}
          {hasAxes && axisLayout === "inline"
            ? (axes ?? []).map((axis) => (
                <FilterPopover
                  key={axis.key}
                  label={axis.label}
                  axes={[axis]}
                  values={values}
                  activeCount={(values?.[axis.key] ?? []).length}
                  onToggle={toggle}
                  onClearAll={() => onValuesChange?.({ ...values, [axis.key]: [] })}
                />
              ))
            : null}
          {hasAxes && axisLayout === "popover" ? (
            <FilterPopover
              axes={axes ?? []}
              values={values}
              activeCount={activeCount}
              onToggle={toggle}
              onClearAll={clearAll}
            />
          ) : null}
        </div>
      </div>

      {applied.length > 0 || resultCount ? (
        <div className="flex flex-wrap items-center gap-2 text-xs text-ap-muted">
          {resultCount ? (
            <span>
              {t("toolbar.showing", { shown: resultCount.shown, total: resultCount.total })}
            </span>
          ) : null}
          {applied.map((a) => (
            <button
              key={`${a.axisKey}:${a.value}`}
              type="button"
              onClick={() => remove(a.axisKey, a.value)}
              className="inline-flex items-center gap-1.5 rounded-full border border-ap-primary bg-ap-primary-soft px-2.5 py-0.5 text-xs font-medium text-ap-primary hover:bg-ap-primary/15 focus:outline-none focus-visible:ring-2 focus-visible:ring-ap-primary"
            >
              {a.label}
              <span aria-hidden="true">✕</span>
              <span className="sr-only">{t("toolbar.removeFilter", { name: a.label })}</span>
            </button>
          ))}
          {applied.length > 0 ? (
            <Button variant="ghost" size="sm" onClick={clearAll}>
              {t("toolbar.clearAll")}
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function FilterPopover({
  axes,
  values,
  activeCount,
  onToggle,
  onClearAll,
  label,
}: {
  axes: readonly FilterAxis[];
  values: FilterValues | undefined;
  activeCount: number;
  onToggle: (axis: FilterAxis, value: string) => void;
  onClearAll: () => void;
  /** Trigger text. Defaults to the generic "Filters" for the combined popover;
   *  the inline layout passes the axis name so each dropdown reads for itself. */
  label?: string;
}): ReactNode {
  const { t } = useTranslation("common");
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    function onDocClick(event: globalThis.MouseEvent): void {
      if (!wrapRef.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKey(event: globalThis.KeyboardEvent): void {
      if (event.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="relative" ref={wrapRef}>
      <button
        ref={triggerRef}
        type="button"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-2 rounded-md border border-ap-line bg-ap-panel px-3 py-1.5 text-sm text-ap-ink hover:bg-ap-line/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-ap-primary"
      >
        {label ?? t("toolbar.filters")}
        {activeCount > 0 ? (
          <span className="inline-grid h-4 min-w-4 place-items-center rounded-full bg-ap-primary px-1 text-[10px] font-semibold text-white">
            {activeCount}
          </span>
        ) : null}
        <span aria-hidden="true" className="text-ap-muted">
          ▾
        </span>
      </button>
      {open ? (
        <div
          id={menuId}
          className="absolute end-0 z-20 mt-1.5 w-60 rounded-xl border border-ap-line bg-ap-panel p-3 shadow-lg"
        >
          {axes.map((axis, i) => (
            <fieldset key={axis.key} className={i > 0 ? "mt-3 border-t border-ap-line pt-3" : ""}>
              {/* The inline layout already names the axis on the trigger, so
                  repeating it as a legend is noise. */}
              <legend
                className={clsx(
                  "mb-1 text-[10px] font-semibold uppercase tracking-wider text-ap-muted",
                  label !== undefined && axes.length === 1 && "sr-only",
                )}
              >
                {axis.label}
              </legend>
              {axis.options.map((option) => {
                const checked = (values?.[axis.key] ?? []).includes(option.value);
                return (
                  <label
                    key={option.value}
                    className="flex cursor-pointer items-center gap-2 py-1 text-sm text-ap-ink"
                  >
                    <input
                      type={axis.single ? "radio" : "checkbox"}
                      name={axis.single ? `${menuId}-${axis.key}` : undefined}
                      checked={checked}
                      onChange={() => onToggle(axis, option.value)}
                      className="accent-ap-primary"
                    />
                    {option.label}
                  </label>
                );
              })}
            </fieldset>
          ))}
          {activeCount > 0 ? (
            <div className="mt-3 border-t border-ap-line pt-3">
              <Button variant="ghost" size="sm" className="w-full" onClick={onClearAll}>
                {t("toolbar.clearAll")}
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/** Convenience for the inline single-axis chip strip. */
export function ToolbarChips({
  options,
  value,
  onChange,
  allLabel,
}: {
  options: readonly FilterOption[];
  value: string | null;
  onChange: (next: string | null) => void;
  allLabel?: string;
}): ReactNode {
  return (
    <>
      {allLabel !== undefined ? (
        <FilterChip active={value === null} onToggle={() => onChange(null)}>
          {allLabel}
        </FilterChip>
      ) : null}
      {options.map((o) => (
        <FilterChip
          key={o.value}
          active={value === o.value}
          onToggle={() => onChange(value === o.value ? null : o.value)}
        >
          {o.label}
        </FilterChip>
      ))}
    </>
  );
}
