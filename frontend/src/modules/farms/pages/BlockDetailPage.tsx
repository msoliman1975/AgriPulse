import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { archiveBlock, getBlock, type BlockDetail } from "@/api/blocks";
import { assignBlockCrop, listBlockCrops, type BlockCropAssignment } from "@/api/cropAssignments";
import { isApiError } from "@/api/errors";
import { ImageryPanel } from "@/modules/imagery/components/ImageryPanel";
import { SubscriptionsTab } from "@/modules/imagery/components/SubscriptionsTab";
import { IndexTrendChart } from "@/modules/indices/components/IndexTrendChart";
import { useCapability } from "@/rbac/useCapability";
import { AreaDisplay } from "../components/AreaDisplay";
import { ArchiveButton } from "../components/ArchiveButton";
import { AttachmentsTab } from "../components/AttachmentsTab";
import { CropPicker } from "../components/CropPicker";
import { MapPreview } from "../components/MapPreview";

export function BlockDetailPage(): JSX.Element {
  const { farmId = "", blockId = "" } = useParams<{ farmId: string; blockId: string }>();
  const { t } = useTranslation("farms");
  const navigate = useNavigate();
  const canEdit = useCapability("block.update_metadata", { farmId });
  const canArchive = useCapability("block.delete", { farmId });
  const canAssignCrop = useCapability("crop_assignment.create", { farmId });
  const canReadImagery = useCapability("imagery.read", { farmId });
  const canReadIndex = useCapability("index.read", { farmId });

  const [block, setBlock] = useState<BlockDetail | null>(null);
  const [history, setHistory] = useState<BlockCropAssignment[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // assign-crop form state
  const [cropId, setCropId] = useState<string | null>(null);
  const [cropVarietyId, setCropVarietyId] = useState<string | null>(null);
  const [seasonLabel, setSeasonLabel] = useState("");
  const [plantingDate, setPlantingDate] = useState("");

  useEffect(() => {
    let cancelled = false;
    setError(null);
    Promise.all([getBlock(blockId), listBlockCrops(blockId)])
      .then(([b, h]) => {
        if (cancelled) return;
        setBlock(b);
        setHistory(h);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [blockId]);

  const handleArchive = async (): Promise<void> => {
    setBusy(true);
    try {
      await archiveBlock(blockId);
      navigate(`/farms/${farmId}`);
    } catch (err) {
      setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err));
    } finally {
      setBusy(false);
    }
  };

  const handleAssignCrop = async (): Promise<void> => {
    if (!cropId || !seasonLabel) return;
    setBusy(true);
    try {
      const created = await assignBlockCrop(blockId, {
        crop_id: cropId,
        crop_variety_id: cropVarietyId,
        season_label: seasonLabel,
        planting_date: plantingDate || null,
        make_current: true,
      });
      setHistory((prev) => [created, ...prev.map((h) => ({ ...h, is_current: false }))]);
      setCropId(null);
      setCropVarietyId(null);
      setSeasonLabel("");
      setPlantingDate("");
    } catch (err) {
      setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (error && !block) {
    return (
      <p role="alert" className="text-sm text-red-700">
        {error}
      </p>
    );
  }
  if (!block) {
    return <p role="status">{t("detail.loading")}</p>;
  }

  const current = history.find((h) => h.is_current);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-brand-800">
            {t("block.detailHeading")} {block.code}
          </h1>
          <p className="text-sm text-slate-600">
            <AreaDisplay areaM2={Number(block.area_m2)} /> ·{" "}
            {block.irrigation_system ? t(`irrigationSystem.${block.irrigation_system}`) : "—"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link to={`/farms/${farmId}`} className="btn btn-ghost">
            {t("block.back")}
          </Link>
          {canEdit ? (
            <Link to={`/farms/${farmId}/blocks/${block.id}/edit`} className="btn btn-ghost">
              {t("block.edit")}
            </Link>
          ) : null}
          {canArchive ? (
            <ArchiveButton label={t("block.archive")} busy={busy} onConfirm={handleArchive} />
          ) : null}
        </div>
      </div>

      <div className="card">
        <MapPreview geometry={block.boundary} />
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold text-slate-800">{t("block.currentCrop")}</h2>
        {current ? (
          <p className="mt-2 text-sm text-slate-700">
            {current.season_label} ·{" "}
            {t(`status.${current.status === "growing" ? "active" : "active"}`)}
          </p>
        ) : (
          <p className="mt-2 text-sm text-slate-600">{t("block.noCrop")}</p>
        )}

        {canAssignCrop ? (
          <form
            className="mt-4 space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              void handleAssignCrop();
            }}
          >
            <CropPicker
              cropId={cropId}
              cropVarietyId={cropVarietyId}
              onChange={(c, v) => {
                setCropId(c);
                setCropVarietyId(v);
              }}
            />
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label className="label" htmlFor="season-label">
                  {t("block.season")}
                </label>
                <input
                  id="season-label"
                  className="input"
                  value={seasonLabel}
                  onChange={(e) => setSeasonLabel(e.target.value)}
                  required
                />
              </div>
              <div>
                <label className="label" htmlFor="planting-date">
                  {t("block.plantingDate")}
                </label>
                <input
                  id="planting-date"
                  className="input"
                  type="date"
                  value={plantingDate}
                  onChange={(e) => setPlantingDate(e.target.value)}
                />
              </div>
            </div>
            <button type="submit" className="btn btn-primary" disabled={!cropId || busy}>
              {t("block.submit")}
            </button>
          </form>
        ) : null}
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold text-slate-800">{t("block.history")}</h2>
        {history.length === 0 ? (
          <p className="mt-2 text-sm text-slate-600">{t("block.noCrop")}</p>
        ) : (
          <ul className="mt-3 space-y-1 text-sm">
            {history.map((h) => (
              <li key={h.id} className="flex items-center justify-between">
                <span>
                  {h.season_label} · {h.is_current ? "★ " : ""}
                  {h.planting_date ?? "—"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <AttachmentsTab ownerKind="block" ownerId={block.id} farmId={farmId} />

      {canReadImagery ? (
        <ImageryPanel
          blockId={block.id}
          farmId={farmId}
          geometry={block.boundary}
          aoiHash={block.aoi_hash ?? undefined}
        />
      ) : null}

      {canReadIndex ? <IndexTrendChart blockId={block.id} /> : null}

      {canReadImagery ? <SubscriptionsTab blockId={block.id} farmId={farmId} /> : null}
    </div>
  );
}
