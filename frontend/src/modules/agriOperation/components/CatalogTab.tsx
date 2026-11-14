// Catalog tab: pick a crop and an operation manual, read it. Read-only for
// farms: manuals are written by the platform team (decision A3: users see
// "operation manual"; the code says plan template).

import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { listCrops } from "@/api/crops";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { Pill } from "@/components/Pill";
import { queryState } from "@/components/asyncState";
import { localizedField, localizedName } from "@/lib/localizedField";
import { useFarmManual, useManualCatalog } from "@/queries/agriOperation";
import { seasonLayout } from "../lib/weeks";
import { ManualView } from "./ManualView";

interface CatalogTabProps {
  farmId: string;
  /** Selected manual, lifted so the Plan tab can start from it. */
  manualId: string | null;
  onManualChange: (id: string | null) => void;
}

export function CatalogTab({ farmId, manualId, onManualChange }: CatalogTabProps): ReactNode {
  const { t, i18n } = useTranslation("agriOperation");
  const lang = i18n.language;
  const catalog = useManualCatalog(farmId);
  const crops = useQuery({
    queryKey: ["crops", "all"],
    queryFn: () => listCrops(),
    staleTime: 300_000,
  });

  const cropCodes = useMemo(
    () => [...new Set((catalog.data ?? []).map((m) => m.crop_path.split(".")[0] ?? ""))],
    [catalog.data],
  );
  const cropName = (code: string): string => {
    const c = crops.data?.find((x) => x.code === code);
    return c ? localizedName(lang, c.name_en, c.name_ar) : code;
  };

  const selected = catalog.data?.find((m) => m.id === manualId) ?? null;
  const [crop, setCrop] = useState<string | null>(null);
  const activeCrop = selected?.crop_path.split(".")[0] ?? crop ?? cropCodes[0] ?? null;
  const manuals = (catalog.data ?? []).filter((m) => m.crop_path.split(".")[0] === activeCrop);

  // Default to the first manual of the crop once the catalog loads.
  useEffect(() => {
    if (!selected && manuals[0]) onManualChange(manuals[0].id);
  }, [selected, manuals, onManualChange]);

  return (
    <AsyncBoundary state={queryState(catalog)} empty={<EmptyState message={t("catalog.empty")} />}>
      {() => (
        <div className="flex flex-col gap-4">
          <Card className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-xs font-semibold text-ap-muted">
              {t("catalog.crop")}
              <select
                className="min-w-40 rounded-md border border-ap-line bg-ap-panel px-2 py-1.5 text-sm text-ap-ink"
                value={activeCrop ?? ""}
                onChange={(e) => {
                  setCrop(e.target.value);
                  const first = (catalog.data ?? []).find(
                    (m) => m.crop_path.split(".")[0] === e.target.value,
                  );
                  onManualChange(first?.id ?? null);
                }}
              >
                {cropCodes.map((c) => (
                  <option key={c} value={c}>
                    {cropName(c)}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs font-semibold text-ap-muted">
              {t("catalog.manual")}
              <select
                className="min-w-64 rounded-md border border-ap-line bg-ap-panel px-2 py-1.5 text-sm text-ap-ink"
                value={selected?.id ?? ""}
                onChange={(e) => onManualChange(e.target.value || null)}
              >
                {manuals.map((m) => (
                  <option key={m.id} value={m.id}>
                    {localizedName(lang, m.name, m.name_ar)}
                  </option>
                ))}
              </select>
            </label>
          </Card>
          {selected ? <ManualDetail farmId={farmId} manualId={selected.id} /> : null}
        </div>
      )}
    </AsyncBoundary>
  );
}

function ManualDetail({ farmId, manualId }: { farmId: string; manualId: string }): ReactNode {
  const { t, i18n } = useTranslation("agriOperation");
  const lang = i18n.language;
  const manual = useFarmManual(farmId, manualId);
  const [varietyPath, setVarietyPath] = useState<string | null>(null);
  const data = manual.data;
  const variety = data?.varieties.find((v) => v.path === varietyPath) ?? data?.varieties[0] ?? null;
  const weeks = data
    ? seasonLayout(variety?.stages ?? data.stages, variety?.is_perennial ?? data.is_perennial)
        .totalWeeks
    : 0;

  return (
    <AsyncBoundary
      state={queryState(manual)}
      isEmpty={() => false}
      empty={<EmptyState message={t("catalog.empty")} />}
    >
      {(data) => (
        <div className="flex flex-col gap-4">
          <Card as="section">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-section-title font-semibold text-ap-ink">
                {localizedName(lang, data.name, data.name_ar)}
              </h2>
              <Pill kind="ok">{t("catalog.published")}</Pill>
            </div>
            <p className="mt-1 text-xs text-ap-muted">
              {[
                t("catalog.cycle", { weeks }),
                data.country || data.region
                  ? [data.region, data.country].filter(Boolean).join(", ")
                  : null,
                t("catalog.activities", { count: data.activities.length }),
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
            {localizedField(lang, data.description, data.description_ar) ? (
              <p className="mt-2 max-w-prose text-sm text-ap-ink">
                {localizedField(lang, data.description, data.description_ar)}
              </p>
            ) : null}
            <p className="mt-3 text-xs text-ap-muted">{t("catalog.readOnly")}</p>
          </Card>

          {data.varieties.length > 1 ? (
            <label className="flex w-fit flex-col gap-1 text-xs font-semibold text-ap-muted">
              {t("catalog.variety")}
              <select
                className="min-w-48 rounded-md border border-ap-line bg-ap-panel px-2 py-1.5 text-sm text-ap-ink"
                value={variety?.path ?? ""}
                onChange={(e) => setVarietyPath(e.target.value)}
              >
                {data.varieties.map((v) => (
                  <option key={v.path} value={v.path}>
                    {v.name_en
                      ? localizedName(lang, v.name_en, v.name_ar)
                      : t("catalog.cropCalendar")}
                  </option>
                ))}
              </select>
            </label>
          ) : null}

          <ManualView manual={data} varietyPath={variety?.path ?? null} />
        </div>
      )}
    </AsyncBoundary>
  );
}
