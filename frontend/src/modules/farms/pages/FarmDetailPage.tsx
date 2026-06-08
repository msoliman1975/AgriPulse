import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { archiveFarm, getFarm, type FarmDetail } from "@/api/farms";
import { listBlocks, type Block } from "@/api/blocks";
import { isApiError } from "@/api/errors";
import { Card } from "@/components/Card";
import { ErrorState } from "@/components/ErrorState";
import { PageHeader } from "@/components/PageHeader";
import { useCapability } from "@/rbac/useCapability";
import { WeatherForecastPanel } from "@/modules/weather/components/WeatherForecastPanel";
import { AreaDisplay } from "../components/AreaDisplay";
import { ArchiveButton } from "../components/ArchiveButton";
import { AttachmentsTab } from "../components/AttachmentsTab";
import { MapPreview } from "../components/MapPreview";

export function FarmDetailPage(): JSX.Element {
  const { farmId = "" } = useParams<{ farmId: string }>();
  const { t } = useTranslation("farms");
  const navigate = useNavigate();
  const canEdit = useCapability("farm.update", { farmId });
  const canArchive = useCapability("farm.delete", { farmId });
  const canCreateBlock = useCapability("block.create", { farmId });
  const canReadWeather = useCapability("weather.read", { farmId });

  const [farm, setFarm] = useState<FarmDetail | null>(null);
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    Promise.all([getFarm(farmId), listBlocks(farmId)])
      .then(([f, page]) => {
        if (cancelled) return;
        setFarm(f);
        setBlocks(page.items);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [farmId]);

  const handleArchive = async (): Promise<void> => {
    setBusy(true);
    try {
      await archiveFarm(farmId);
      navigate("/farms");
    } catch (err) {
      setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (error) {
    return <ErrorState message={error} />;
  }
  if (!farm) {
    return (
      <p role="status" className="text-sm text-ap-muted">
        {t("detail.loading")}
      </p>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        above={
          <Link
            to="/farms"
            className="text-sm font-medium text-ap-primary hover:underline"
          >
            ← {t("detail.back")}
          </Link>
        }
        title={farm.name}
        subtitle={
          <>
            {farm.code} · {farm.governorate ?? "—"} · <AreaDisplay areaM2={Number(farm.area_m2)} />
          </>
        }
        actions={
          <>
            {canEdit ? (
              <Link to={`/farms/${farm.id}/edit`} className="btn btn-ghost">
                {t("detail.edit")}
              </Link>
            ) : null}
            {canArchive ? (
              <ArchiveButton label={t("detail.archive")} busy={busy} onConfirm={handleArchive} />
            ) : null}
          </>
        }
      />

      <Card>
        <MapPreview geometry={farm.boundary} />
      </Card>

      {canReadWeather && blocks.length > 0 ? (
        <WeatherForecastPanel blockId={blocks[0].id} farmId={farm.id} farmName={farm.name} />
      ) : null}

      <Card>
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-ap-ink">{t("detail.blocksTab")}</h2>
          {canCreateBlock ? (
            <span className="flex gap-2">
              <Link to={`/farms/${farm.id}/blocks/new`} className="btn btn-primary">
                {t("detail.addBlock")}
              </Link>
              <Link to={`/farms/${farm.id}/blocks/auto-grid`} className="btn btn-ghost">
                {t("detail.autoGrid")}
              </Link>
            </span>
          ) : null}
        </div>
        {blocks.length === 0 ? (
          <p className="mt-3 text-sm text-ap-muted">{t("detail.noBlocks")}</p>
        ) : (
          <ul className="mt-3 space-y-2">
            {blocks.map((b) => (
              <li key={b.id} className="flex items-center justify-between text-sm">
                <Link to={`/farms/${farm.id}/blocks/${b.id}`} className="text-ap-primary underline">
                  {b.code} {b.name ? `— ${b.name}` : null}
                </Link>
                <AreaDisplay areaM2={Number(b.area_m2)} />
              </li>
            ))}
          </ul>
        )}
      </Card>

      <AttachmentsTab ownerKind="farm" ownerId={farm.id} farmId={farm.id} />

      <Card>
        <Link to={`/farms/${farm.id}/members`} className="text-ap-primary underline">
          {t("detail.membersTab")}
        </Link>
      </Card>
    </div>
  );
}
