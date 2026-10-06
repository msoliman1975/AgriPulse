import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { archiveBlock, getBlock, type BlockDetail } from "@/api/blocks";
import { assignBlockCrop, listBlockCrops, type BlockCropAssignment } from "@/api/cropAssignments";
import { getFarm } from "@/api/farms";
import { isApiError } from "@/api/errors";
import { Breadcrumb } from "@/components/Breadcrumb";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { ErrorState } from "@/components/ErrorState";
import { LinkButton } from "@/components/LinkButton";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Skeleton } from "@/components/Skeleton";
import { ImageryPanel } from "@/modules/imagery/components/ImageryPanel";
import { SubscriptionsTab } from "@/modules/imagery/components/SubscriptionsTab";
import { IndexTrendChart } from "@/modules/indices/components/IndexTrendChart";
import { WeatherForecastPanel } from "@/modules/weather/components/WeatherForecastPanel";
import { WeatherSubscriptionsTab } from "@/modules/weather/components/WeatherSubscriptionsTab";
import { localizedName } from "@/lib/localizedField";
import { useCapability } from "@/rbac/useCapability";
import { AreaDisplay } from "../components/AreaDisplay";
import { ArchiveButton } from "../components/ArchiveButton";
import { AttachmentsTab } from "../components/AttachmentsTab";
import { CropPicker } from "../components/CropPicker";
import { MapPreview } from "../components/MapPreview";

export function BlockDetailPage(): JSX.Element {
  const { farmId = "", blockId = "" } = useParams<{ farmId: string; blockId: string }>();
  const { t, i18n } = useTranslation("farms");
  const navigate = useNavigate();
  const canEdit = useCapability("block.update_metadata", { farmId });
  const canArchive = useCapability("block.delete", { farmId });
  const canAssignCrop = useCapability("crop_assignment.create", { farmId });
  const canReadImagery = useCapability("imagery.read", { farmId });
  const canReadIndex = useCapability("index.read", { farmId });
  const canReadWeather = useCapability("weather.read", { farmId });

  const [block, setBlock] = useState<BlockDetail | null>(null);
  const [farmNames, setFarmNames] = useState<{ name: string; name_ar: string | null } | null>(null);
  const [history, setHistory] = useState<BlockCropAssignment[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // assign-crop form state
  const [cropId, setCropId] = useState<string | null>(null);
  const [cropVarietyId, setCropVarietyId] = useState<string | null>(null);
  const [cropVarietyStrainId, setCropVarietyStrainId] = useState<string | null>(null);
  const [cropSelectionComplete, setCropSelectionComplete] = useState(false);
  const [seasonLabel, setSeasonLabel] = useState("");
  const [plantingDate, setPlantingDate] = useState("");

  useEffect(() => {
    let cancelled = false;
    setError(null);
    Promise.all([getBlock(blockId), listBlockCrops(blockId), getFarm(farmId)])
      .then(([b, h, f]) => {
        if (cancelled) return;
        setBlock(b);
        setHistory(h);
        setFarmNames({ name: f.name, name_ar: f.name_ar });
      })
      .catch((err) => {
        if (cancelled) return;
        setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [blockId, farmId]);

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
        crop_variety_strain_id: cropVarietyStrainId,
        season_label: seasonLabel,
        planting_date: plantingDate || null,
        make_current: true,
      });
      setHistory((prev) => [created, ...prev.map((h) => ({ ...h, is_current: false }))]);
      setCropId(null);
      setCropVarietyId(null);
      setCropVarietyStrainId(null);
      setSeasonLabel("");
      setPlantingDate("");
    } catch (err) {
      setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (error && !block) {
    return <ErrorState message={error} />;
  }
  if (!block) {
    return <Skeleton className="h-64 w-full rounded-xl" />;
  }

  const current = history.find((h) => h.is_current);

  return (
    <Page>
      <PageHeader
        above={
          <Breadcrumb
            items={[
              { label: t("list.heading"), to: "/farms" },
              {
                label: farmNames
                  ? localizedName(i18n.language, farmNames.name, farmNames.name_ar)
                  : "…",
                to: `/farms/${farmId}`,
              },
              { label: `${t("block.detailHeading")} ${block.code}` },
            ]}
          />
        }
        title={
          <span className="flex items-center gap-2">
            {t("block.detailHeading")} {block.code}
            {block.unit_type !== "block" ? (
              <span className="inline-flex items-center rounded-full bg-ap-primary-soft px-2 py-0.5 text-xs font-medium text-ap-primary">
                {t(`block.unitType.${block.unit_type}`)}
              </span>
            ) : null}
          </span>
        }
        subtitle={
          <>
            <AreaDisplay areaM2={Number(block.area_m2)} /> ·{" "}
            {block.irrigation_system ? t(`irrigationSystem.${block.irrigation_system}`) : "—"}
          </>
        }
        actions={
          <>
            {canEdit ? (
              <LinkButton variant="ghost" to={`/farms/${farmId}/blocks/${block.id}/edit`}>
                {t("block.edit")}
              </LinkButton>
            ) : null}
            {canArchive ? (
              <ArchiveButton label={t("block.archive")} busy={busy} onConfirm={handleArchive} />
            ) : null}
          </>
        }
      />

      <Card>
        <MapPreview geometry={block.boundary} />
      </Card>

      <Card>
        <h2 className="text-lg font-semibold text-ap-ink">{t("block.currentCrop")}</h2>
        {current ? (
          <p className="mt-2 text-sm text-ap-ink">
            {current.crop_path ? (
              <span className="font-mono text-ap-primary">{current.crop_path}</span>
            ) : null}
            {current.crop_path ? " · " : ""}
            {current.season_label} ·{" "}
            {t(`status.${current.status === "growing" ? "active" : "active"}`)}
          </p>
        ) : (
          <p className="mt-2 text-sm text-ap-muted">{t("block.noCrop")}</p>
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
              cropVarietyStrainId={cropVarietyStrainId}
              onChange={(c, v, s) => {
                setCropId(c);
                setCropVarietyId(v);
                setCropVarietyStrainId(s);
              }}
              onValidityChange={setCropSelectionComplete}
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
            <Button type="submit" disabled={!cropSelectionComplete || !seasonLabel || busy}>
              {t("block.submit")}
            </Button>
          </form>
        ) : null}
      </Card>

      <Card>
        <h2 className="text-lg font-semibold text-ap-ink">{t("block.history")}</h2>
        {history.length === 0 ? (
          <p className="mt-2 text-sm text-ap-muted">{t("block.noCrop")}</p>
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
      </Card>

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

      {canReadWeather ? <WeatherForecastPanel blockId={block.id} farmId={farmId} /> : null}

      {canReadWeather ? <WeatherSubscriptionsTab blockId={block.id} farmId={farmId} /> : null}
    </Page>
  );
}
