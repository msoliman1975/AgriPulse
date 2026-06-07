import { useCallback, useMemo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

const inputCls =
  "w-full rounded-md border border-ap-line bg-white px-2 py-1 text-sm shadow-sm focus:border-ap-primary focus:outline-none focus:ring-1 focus:ring-ap-primary";

export interface ObservedAtPickerProps {
  /** ISO-8601 (UTC) string, or null when the user hasn't picked anything yet. */
  value: string | null;
  onChange: (next: string | null) => void;
  /** Optional aria label override. */
  label?: string;
}

// `datetime-local` inputs are timezone-naive — they show the user's wall
// clock. We round-trip via local components so a backdate of "today 9 AM"
// stays "today 9 AM" no matter the user's offset, then serialize as a UTC
// ISO string for the backend.
function isoToLocalInput(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

function localInputToIso(local: string): string | null {
  if (!local) return null;
  const d = new Date(local);
  if (Number.isNaN(d.getTime())) return null;
  return d.toISOString();
}

export function ObservedAtPicker({ value, onChange, label }: ObservedAtPickerProps): ReactNode {
  const { t } = useTranslation("signals");
  const inputValue = useMemo(() => (value ? isoToLocalInput(value) : ""), [value]);

  const handleChange = useCallback(
    (next: string) => {
      onChange(localInputToIso(next));
    },
    [onChange],
  );

  const handleNow = useCallback(() => {
    onChange(new Date().toISOString());
  }, [onChange]);

  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-ap-muted">{label ?? t("log.form.observedAt.label")}</span>
      <div className="flex items-center gap-2">
        <input
          type="datetime-local"
          value={inputValue}
          onChange={(e) => handleChange(e.target.value)}
          className={inputCls}
          aria-label={label ?? t("log.form.observedAt.label")}
        />
        <button
          type="button"
          onClick={handleNow}
          className="flex-none rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40"
        >
          {t("log.form.observedAt.nowButton")}
        </button>
      </div>
      <span className="text-[11px] text-ap-muted">{t("log.form.observedAt.hint")}</span>
    </label>
  );
}

// Exposed for tests.
export const _internals = { isoToLocalInput, localInputToIso };
