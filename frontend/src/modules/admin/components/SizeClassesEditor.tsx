// Author the canopy size classes offered on a block's crop assignment.
//
// The stage ladder's plainer sibling: an ordered, bilingual, unique-coded
// list with no advance rule, so nothing here depends on the crop's cycle.
// Order is taken from position — the backend requires it unique and there is
// no reason to make a human maintain a column of integers.
//
// Saved whole, for the same reason the calendar is: the list is validated as
// a unit (unique codes, unique orders) and a half-applied one would offer
// blocks a dropdown nobody authored.

import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { SizeClass } from "@/api/crops";
import { validateSizeClasses } from "@/modules/admin/lib/sizeClasses";

interface Props {
  classes: SizeClass[];
  heading: string;
  busy: boolean;
  onCancel: () => void;
  onSave: (classes: SizeClass[]) => void;
}

export function SizeClassesEditor({ classes, heading, busy, onCancel, onSave }: Props): ReactNode {
  const { t } = useTranslation("admin");
  const [rows, setRows] = useState<SizeClass[]>(() =>
    classes
      .slice()
      .sort((a, b) => a.order - b.order)
      .map((c) => ({ ...c })),
  );
  const [showProblems, setShowProblems] = useState(false);

  const problems = validateSizeClasses(rows);

  const patch = (idx: number, next: Partial<SizeClass>): void =>
    setRows((prev) => prev.map((c, i) => (i === idx ? { ...c, ...next } : c)));

  const move = (idx: number, delta: number): void =>
    setRows((prev) => {
      const to = idx + delta;
      if (to < 0 || to >= prev.length) return prev;
      const next = [...prev];
      [next[idx], next[to]] = [next[to], next[idx]];
      return next;
    });

  const submit = (): void => {
    if (problems.length > 0) {
      setShowProblems(true);
      return;
    }
    onSave(rows.map((c, i) => ({ ...c, order: i + 1 })));
  };

  return (
    <section className="rounded-md border border-ap-line bg-ap-panel p-3">
      <header className="mb-2">
        <h3 className="text-sm font-semibold text-ap-ink">{heading}</h3>
        <p className="text-[11px] text-ap-muted">{t("sizeClasses.hint")}</p>
      </header>

      {rows.length === 0 ? (
        <p className="rounded border border-ap-warn/40 bg-ap-warn/5 p-2 text-[11px] text-ap-warn">
          {t("sizeClasses.empty")}
        </p>
      ) : null}

      <ol className="flex flex-col gap-2">
        {rows.map((cls, idx) => (
          <li key={idx} className="rounded-md border border-ap-line bg-ap-bg/30 p-2">
            <div className="flex flex-wrap items-end gap-2">
              <span className="w-5 text-center text-xs text-ap-muted">{idx + 1}</span>
              <Text
                label={t("sizeClasses.code")}
                value={cls.code}
                mono
                onChange={(v) => patch(idx, { code: v })}
              />
              <Text
                label={t("sizeClasses.nameEn")}
                value={cls.name_en}
                onChange={(v) => patch(idx, { name_en: v })}
              />
              <Text
                label={t("sizeClasses.nameAr")}
                value={cls.name_ar}
                dir="rtl"
                onChange={(v) => patch(idx, { name_ar: v })}
              />
              <div className="ms-auto flex gap-1">
                <IconButton label={t("sizeClasses.moveUp")} onClick={() => move(idx, -1)}>
                  ↑
                </IconButton>
                <IconButton label={t("sizeClasses.moveDown")} onClick={() => move(idx, 1)}>
                  ↓
                </IconButton>
                <IconButton
                  label={t("sizeClasses.remove")}
                  danger
                  onClick={() => setRows((prev) => prev.filter((_, i) => i !== idx))}
                >
                  ✕
                </IconButton>
              </div>
            </div>
          </li>
        ))}
      </ol>

      <button
        type="button"
        onClick={() =>
          setRows((prev) => [
            ...prev,
            { code: "", name_en: "", name_ar: "", order: prev.length + 1 },
          ])
        }
        className="mt-2 self-start rounded-md border border-dashed border-ap-line px-2 py-1 text-xs text-ap-ink hover:bg-ap-bg/60"
      >
        {t("sizeClasses.addClass")}
      </button>

      {showProblems && problems.length > 0 ? (
        <ul role="alert" className="mt-2 flex flex-col gap-0.5">
          {problems.map((p) => (
            <li key={p} className="text-[11px] text-ap-crit">
              {p}
            </li>
          ))}
        </ul>
      ) : null}

      <footer className="mt-3 flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border border-ap-line bg-ap-panel px-3 py-1.5 text-xs text-ap-ink hover:bg-ap-line/40"
        >
          {t("sizeClasses.cancel")}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={submit}
          className="rounded-md bg-ap-primary px-3 py-1.5 text-xs font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
        >
          {busy ? t("sizeClasses.saving") : t("sizeClasses.save")}
        </button>
      </footer>
    </section>
  );
}

function Text({
  label,
  value,
  onChange,
  mono = false,
  dir,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  mono?: boolean;
  dir?: "rtl";
}): ReactNode {
  return (
    <label className="flex flex-col gap-1 text-[11px] text-ap-muted">
      {label}
      <input
        type="text"
        value={value}
        dir={dir}
        onChange={(e) => onChange(e.target.value)}
        aria-label={label}
        className={`w-32 rounded-md border border-ap-line bg-white px-2 py-1 text-xs text-ap-ink ${
          mono ? "font-mono" : ""
        }`}
      />
    </label>
  );
}

function IconButton({
  label,
  onClick,
  children,
  danger = false,
}: {
  label: string;
  onClick: () => void;
  children: ReactNode;
  danger?: boolean;
}): ReactNode {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className={`rounded-md border border-ap-line bg-white px-2 py-0.5 text-[11px] hover:bg-ap-line/30 ${
        danger ? "text-ap-crit" : "text-ap-ink"
      }`}
    >
      {children}
    </button>
  );
}
