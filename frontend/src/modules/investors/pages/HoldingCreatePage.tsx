import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import type { Polygon } from "geojson";

import { createHolding, getBlockHoldings, type HoldingWritableStatus } from "@/api/investors";
import { Breadcrumb } from "@/components/Breadcrumb";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { ErrorState } from "@/components/ErrorState";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Skeleton } from "@/components/Skeleton";
import { geometryAreaM2 } from "@/lib/geometry";
import { AreaDisplay } from "@/modules/farms/components/AreaDisplay";
import { MapDraw, type MapDrawReference } from "@/modules/farms/components/MapDraw";
import { HoldingFields, type HoldingFieldValues } from "../components/HoldingFields";
import { blockHoldingsKey, errorText, formatPct } from "../lib";

/** /investments/holdings/:farmId/blocks/:blockId/new — draw one holding in a block. */
export function HoldingCreatePage(): JSX.Element {
  const { farmId = "", blockId = "" } = useParams<{ farmId: string; blockId: string }>();
  const { t, i18n } = useTranslation("investors");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [polygon, setPolygon] = useState<Polygon | null>(null);
  const [values, setValues] = useState<HoldingFieldValues>({
    code: "",
    name: "",
    name_ar: "",
    tree_count: "",
    status: "draft" as HoldingWritableStatus,
    notes_internal: "",
  });
  const [error, setError] = useState<string | null>(null);

  const ctx = useQuery({
    queryKey: blockHoldingsKey(farmId, blockId),
    queryFn: () => getBlockHoldings(farmId, blockId),
  });

  const references = useMemo<MapDrawReference[]>(() => {
    if (!ctx.data) return [];
    return [
      { geometry: ctx.data.boundary, kind: "frame" },
      ...ctx.data.holdings.map((h) => ({ geometry: h.boundary, kind: "neighbour" as const })),
    ];
  }, [ctx.data]);

  const create = useMutation({
    mutationFn: () => {
      if (!polygon) throw new Error(t("holding.noShape"));
      return createHolding(farmId, blockId, {
        code: values.code.trim() || null,
        name: values.name.trim(),
        name_ar: values.name_ar.trim() || null,
        boundary: polygon,
        tree_count: values.tree_count === "" ? null : Number(values.tree_count),
        status: values.status,
        notes_internal: values.notes_internal.trim() || null,
      });
    },
    onSuccess: async (holding) => {
      await queryClient.invalidateQueries({ queryKey: ["holdings"] });
      navigate(`/investments/holdings/${farmId}/${holding.id}`);
    },
    onError: (err) => setError(errorText(err)),
  });

  if (ctx.isError) return <ErrorState message={errorText(ctx.error)} />;
  if (!ctx.data) return <Skeleton className="h-64 w-full rounded-xl" />;

  const blockLabel = ctx.data.block_code ?? "";
  const drawnArea = polygon ? geometryAreaM2(polygon) : null;
  const blockArea = Number(ctx.data.block_area_m2);

  return (
    <Page>
      <div className="flex max-w-4xl flex-col gap-4">
        <PageHeader
          above={
            <Breadcrumb
              items={[
                { label: t("nav.holdings"), to: `/investments/holdings/${farmId}` },
                { label: blockLabel },
                { label: t("block.add") },
              ]}
            />
          }
          title={t("holding.createTitle", { block: blockLabel })}
        />
        {!ctx.data.eligible ? (
          <ErrorState message={ctx.data.ineligible_reason ?? ""} />
        ) : (
          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              setError(null);
              if (!polygon) {
                setError(t("holding.noShape"));
                return;
              }
              create.mutate();
            }}
          >
            <Card>
              <p className="mb-2 text-sm text-ap-muted">{t("holding.drawHelp")}</p>
              <MapDraw references={references} onChange={setPolygon} />
              <p className="mt-2 text-sm text-ap-ink" data-testid="live-area">
                {drawnArea !== null ? (
                  <>
                    <AreaDisplay areaM2={drawnArea} fractionDigits={2} />
                    {" · "}
                    {formatPct(blockArea > 0 ? (drawnArea * 100) / blockArea : 0, i18n.language)}%
                  </>
                ) : (
                  t("holding.noShape")
                )}
              </p>
            </Card>
            <Card>
              <HoldingFields values={values} onChange={setValues} showCode />
            </Card>
            {error ? (
              <p role="alert" className="text-sm text-ap-crit">
                {error}
              </p>
            ) : null}
            <div className="flex gap-2">
              <Button type="submit" disabled={create.isPending || !values.name.trim()}>
                {t("holding.create")}
              </Button>
              <Button
                type="button"
                variant="ghost"
                onClick={() => navigate(`/investments/holdings/${farmId}`)}
              >
                {t("holding.cancel")}
              </Button>
            </div>
          </form>
        )}
      </div>
    </Page>
  );
}
