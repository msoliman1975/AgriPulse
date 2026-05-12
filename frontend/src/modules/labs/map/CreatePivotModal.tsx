import { useState } from "react";

interface Props {
  centerLat: number;
  centerLon: number;
  radiusM: number;
  submitting: boolean;
  errorMessage: string | null;
  onCancel: () => void;
  onSubmit: (vals: { code: string; name: string; sector_count: number }) => void;
}

const SECTOR_PRESETS = [1, 4, 6, 8, 12];

export function CreatePivotModal({
  centerLat,
  centerLon,
  radiusM,
  submitting,
  errorMessage,
  onCancel,
  onSubmit,
}: Props) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [sectorCount, setSectorCount] = useState(4);

  const hectares = ((Math.PI * radiusM * radiusM) / 10_000).toFixed(2);
  const codeError =
    code.length === 0
      ? "Code is required"
      : code.length > 60
        ? "Code too long (leave room for -S<n> suffix)"
        : null;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (codeError) return;
    onSubmit({ code: code.trim(), name: name.trim(), sector_count: sectorCount });
  }

  return (
    <div className="absolute inset-0 z-30 flex items-center justify-center bg-black/30 px-4">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-md rounded-md bg-white p-4 shadow-xl"
      >
        <h2 className="text-[14px] font-semibold text-slate-900">Create pivot</h2>
        <p className="mt-1 text-[11px] text-slate-500">
          Center {centerLat.toFixed(5)}, {centerLon.toFixed(5)} · radius{" "}
          {Math.round(radiusM)} m · ~{hectares} ha
        </p>

        <label className="mt-3 block text-[11px] font-medium text-slate-700">
          Code
          <input
            type="text"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            className="mt-1 block w-full rounded border border-slate-300 px-2 py-1 text-[13px] focus:border-slate-500 focus:outline-none"
            placeholder="e.g. P-3"
            autoFocus
            disabled={submitting}
            required
          />
          {codeError && code.length > 0 ? (
            <span className="mt-0.5 block text-[10px] text-red-700">{codeError}</span>
          ) : null}
        </label>

        <label className="mt-3 block text-[11px] font-medium text-slate-700">
          Name (optional)
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="mt-1 block w-full rounded border border-slate-300 px-2 py-1 text-[13px] focus:border-slate-500 focus:outline-none"
            placeholder="e.g. North pivot"
            disabled={submitting}
          />
        </label>

        <label className="mt-3 block text-[11px] font-medium text-slate-700">
          Sectors (equal slices)
          <div className="mt-1 flex gap-1.5">
            {SECTOR_PRESETS.map((n) => (
              <button
                key={n}
                type="button"
                onClick={() => setSectorCount(n)}
                disabled={submitting}
                className={`rounded px-2 py-1 text-[12px] ${
                  n === sectorCount
                    ? "bg-slate-900 text-white"
                    : "border border-slate-300 text-slate-700 hover:bg-slate-50"
                }`}
              >
                {n}
              </button>
            ))}
            <input
              type="number"
              min={1}
              max={16}
              value={sectorCount}
              onChange={(e) =>
                setSectorCount(Math.max(1, Math.min(16, Number(e.target.value) || 1)))
              }
              disabled={submitting}
              className="w-16 rounded border border-slate-300 px-2 py-1 text-[12px]"
            />
          </div>
        </label>

        {errorMessage ? (
          <p className="mt-3 rounded bg-red-50 px-2 py-1 text-[11px] text-red-700">
            {errorMessage}
          </p>
        ) : null}

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={submitting}
            className="rounded border border-slate-300 px-3 py-1 text-[12px] text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            Discard
          </button>
          <button
            type="submit"
            disabled={submitting || codeError != null}
            className="rounded bg-slate-900 px-3 py-1 text-[12px] font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {submitting ? "Saving…" : "Create pivot"}
          </button>
        </div>
      </form>
    </div>
  );
}
