import { useState } from "react";

import type { IrrigationSystem } from "@/api/blocks";

export interface DrawBlockFormValues {
  code: string;
  name: string;
  irrigation_system: IrrigationSystem | null;
}

interface Props {
  polygonAreaM2: number;
  submitting: boolean;
  errorMessage: string | null;
  onCancel: () => void;
  onSubmit: (values: DrawBlockFormValues) => void;
}

const IRRIGATION_OPTIONS: { value: IrrigationSystem | ""; label: string }[] = [
  { value: "", label: "—" },
  { value: "drip", label: "Drip" },
  { value: "micro_sprinkler", label: "Micro-sprinkler" },
  { value: "pivot", label: "Pivot" },
  { value: "furrow", label: "Furrow" },
  { value: "flood", label: "Flood" },
  { value: "surface", label: "Surface" },
  { value: "none", label: "None" },
];

export function DrawBlockModal({
  polygonAreaM2,
  submitting,
  errorMessage,
  onCancel,
  onSubmit,
}: Props) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [irrigation, setIrrigation] = useState<IrrigationSystem | "">("");

  const hectares = (polygonAreaM2 / 10_000).toFixed(3);
  const codeError =
    code.length === 0
      ? "Code is required"
      : code.length > 64
        ? "Code too long"
        : null;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (codeError) return;
    onSubmit({
      code: code.trim(),
      name: name.trim(),
      irrigation_system: irrigation === "" ? null : irrigation,
    });
  }

  return (
    <div className="absolute inset-0 z-30 flex items-center justify-center bg-black/30 px-4">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-md rounded-md bg-white p-4 shadow-xl"
      >
        <h2 className="text-[14px] font-semibold text-slate-900">Create block</h2>
        <p className="mt-1 text-[11px] text-slate-500">
          Polygon area · {hectares} ha
        </p>

        <label className="mt-3 block text-[11px] font-medium text-slate-700">
          Code
          <input
            type="text"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            className="mt-1 block w-full rounded border border-slate-300 px-2 py-1 text-[13px] focus:border-slate-500 focus:outline-none"
            placeholder="e.g. B-12"
            autoFocus
            disabled={submitting}
            required
          />
          {codeError && code.length > 0 ? (
            <span className="mt-0.5 block text-[10px] text-red-700">
              {codeError}
            </span>
          ) : null}
        </label>

        <label className="mt-3 block text-[11px] font-medium text-slate-700">
          Name (optional)
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="mt-1 block w-full rounded border border-slate-300 px-2 py-1 text-[13px] focus:border-slate-500 focus:outline-none"
            placeholder="e.g. West orchard"
            disabled={submitting}
          />
        </label>

        <label className="mt-3 block text-[11px] font-medium text-slate-700">
          Irrigation system
          <select
            value={irrigation}
            onChange={(e) => setIrrigation(e.target.value as IrrigationSystem | "")}
            className="mt-1 block w-full rounded border border-slate-300 bg-white px-2 py-1 text-[13px] focus:border-slate-500 focus:outline-none"
            disabled={submitting}
          >
            {IRRIGATION_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
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
            {submitting ? "Saving…" : "Create block"}
          </button>
        </div>
      </form>
    </div>
  );
}
