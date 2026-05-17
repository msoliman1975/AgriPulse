import { useState } from "react";

export interface CascadeCounts {
  alerts_resolved: number;
  irrigation_skipped: number;
  plan_activities_skipped: number;
  weather_subs_deactivated: number;
  imagery_subs_deactivated: number;
  block_count?: number;
}

interface Props {
  // What is being inactivated, e.g. block code or farm code.
  // The user types this value verbatim to enable the destructive button.
  confirmKeyword: string;
  // "block" | "farm" — used in microcopy.
  entityLabel: string;
  // Preview counts to show; null while loading.
  preview: CascadeCounts | null;
  previewError: string | null;
  submitting: boolean;
  submitError: string | null;
  onCancel: () => void;
  onSubmit: (reason: string) => void;
}

const REASON_PRESETS = ["merged", "abandoned", "replanted", "wind-down", "other"];

export function InactivateConfirmModal({
  confirmKeyword,
  entityLabel,
  preview,
  previewError,
  submitting,
  submitError,
  onCancel,
  onSubmit,
}: Props) {
  const [typed, setTyped] = useState("");
  const [reason, setReason] = useState<string>("");

  const ready = typed.trim() === confirmKeyword && reason.trim().length > 0;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!ready) return;
    onSubmit(reason.trim());
  }

  return (
    <div className="absolute inset-0 z-30 flex items-center justify-center bg-black/40 px-4">
      <form onSubmit={handleSubmit} className="w-full max-w-md rounded-md bg-white p-4 shadow-xl">
        <h2 className="text-[14px] font-semibold text-slate-900">
          Inactivate {entityLabel} {confirmKeyword}
        </h2>
        <p className="mt-1 text-[11px] text-slate-500">
          This is a soft inactivation — history is kept, but new alerts, schedules and integrations
          will stop. You can reactivate later from the archive section.
        </p>

        <section className="mt-3 rounded border border-slate-200 bg-slate-50 px-3 py-2 text-[11px]">
          <h3 className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
            Cascade preview
          </h3>
          {previewError ? (
            <p className="text-red-700">{previewError}</p>
          ) : preview ? (
            <ul className="space-y-0.5">
              {preview.block_count != null ? (
                <li>
                  <strong>{preview.block_count}</strong> block(s) will inactivate
                </li>
              ) : null}
              <li>
                <strong>{preview.alerts_resolved}</strong> open alert(s) will resolve
              </li>
              <li>
                <strong>{preview.irrigation_skipped}</strong> future irrigation schedule(s) will
                skip
              </li>
              <li>
                <strong>{preview.plan_activities_skipped}</strong> planned activity(ies) will skip
              </li>
              <li>
                <strong>{preview.weather_subs_deactivated}</strong> weather subscription(s) will
                deactivate
              </li>
              <li>
                <strong>{preview.imagery_subs_deactivated}</strong> imagery subscription(s) will
                deactivate
              </li>
            </ul>
          ) : (
            <p className="text-slate-500">Loading…</p>
          )}
        </section>

        <label className="mt-3 block text-[11px] font-medium text-slate-700">
          Reason
          <select
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className="mt-1 block w-full rounded border border-slate-300 bg-white px-2 py-1 text-[13px] focus:border-slate-500 focus:outline-none"
            disabled={submitting}
          >
            <option value="">— select —</option>
            {REASON_PRESETS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>

        <label className="mt-3 block text-[11px] font-medium text-slate-700">
          Type <code className="rounded bg-slate-100 px-1">{confirmKeyword}</code> to confirm
          <input
            type="text"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            className="mt-1 block w-full rounded border border-slate-300 px-2 py-1 text-[13px] focus:border-slate-500 focus:outline-none"
            disabled={submitting}
            autoComplete="off"
          />
        </label>

        {submitError ? (
          <p className="mt-3 rounded bg-red-50 px-2 py-1 text-[11px] text-red-700">{submitError}</p>
        ) : null}

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={submitting}
            className="rounded border border-slate-300 px-3 py-1 text-[12px] text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={!ready || submitting}
            className="rounded bg-red-700 px-3 py-1 text-[12px] font-medium text-white hover:bg-red-800 disabled:opacity-50"
          >
            {submitting ? "Inactivating…" : "Inactivate"}
          </button>
        </div>
      </form>
    </div>
  );
}
