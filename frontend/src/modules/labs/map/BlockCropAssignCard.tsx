import { useState, type ReactNode } from "react";

import { assignBlockCrop } from "@/api/cropAssignments";
import { isApiError } from "@/api/errors";
import { CropPicker } from "@/modules/farms/components/CropPicker";
import { useCapability } from "@/rbac/useCapability";

interface Props {
  blockId: string;
  farmId: string;
  /** Whether the selected unit already has a current crop (drives the
   * button label: "Assign" vs "Change"). */
  hasCurrentCrop: boolean;
  /** Called after a successful assignment so the parent can refetch the
   * block detail (the read-only crop line above updates). */
  onAssigned: () => void;
}

/**
 * Inline crop-assignment control for the Labs-map block drawer. Mirrors the
 * legacy BlockDetailPage form (cascading Crop → Variety → Strain picker +
 * season + planting date) but lives in the canonical /labs/map panel.
 * Collapsed to a single button until the user opens it; renders nothing for
 * users without the crop_assignment.create capability on this farm.
 */
export function BlockCropAssignCard({
  blockId,
  farmId,
  hasCurrentCrop,
  onAssigned,
}: Props): ReactNode {
  const canAssign = useCapability("crop_assignment.create", { farmId });
  const [open, setOpen] = useState(false);
  const [cropId, setCropId] = useState<string | null>(null);
  const [varietyId, setVarietyId] = useState<string | null>(null);
  const [strainId, setStrainId] = useState<string | null>(null);
  const [complete, setComplete] = useState(false);
  const [season, setSeason] = useState("");
  const [planting, setPlanting] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!canAssign) return null;

  const reset = (): void => {
    setCropId(null);
    setVarietyId(null);
    setStrainId(null);
    setSeason("");
    setPlanting("");
    setError(null);
  };

  const submit = async (): Promise<void> => {
    if (!cropId || !complete || !season) return;
    setBusy(true);
    setError(null);
    try {
      await assignBlockCrop(blockId, {
        crop_id: cropId,
        crop_variety_id: varietyId,
        crop_variety_strain_id: strainId,
        season_label: season,
        planting_date: planting || null,
        make_current: true,
      });
      reset();
      setOpen(false);
      onAssigned();
    } catch (err) {
      setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mt-1 rounded border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50"
      >
        {hasCurrentCrop ? "Change crop" : "Assign crop"}
      </button>
    );
  }

  return (
    <form
      className="mt-2 space-y-2 rounded border border-slate-200 bg-slate-50 px-2 py-2"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <CropPicker
        cropId={cropId}
        cropVarietyId={varietyId}
        cropVarietyStrainId={strainId}
        onChange={(c, v, s) => {
          setCropId(c);
          setVarietyId(v);
          setStrainId(s);
        }}
        onValidityChange={setComplete}
      />
      <div className="grid grid-cols-2 gap-2">
        <label className="text-[11px] text-slate-600">
          Season
          <input
            className="input mt-0.5 h-8 text-xs"
            value={season}
            onChange={(e) => setSeason(e.target.value)}
            placeholder="2026A"
            required
          />
        </label>
        <label className="text-[11px] text-slate-600">
          Planting date
          <input
            type="date"
            className="input mt-0.5 h-8 text-xs"
            value={planting}
            onChange={(e) => setPlanting(e.target.value)}
          />
        </label>
      </div>
      {error ? <p className="text-[11px] text-red-600">{error}</p> : null}
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={!complete || !season || busy}
          className="rounded bg-slate-900 px-2 py-0.5 text-[11px] font-medium text-white disabled:opacity-50"
        >
          {busy ? "Saving…" : "Save"}
        </button>
        <button
          type="button"
          onClick={() => {
            reset();
            setOpen(false);
          }}
          disabled={busy}
          className="rounded border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
