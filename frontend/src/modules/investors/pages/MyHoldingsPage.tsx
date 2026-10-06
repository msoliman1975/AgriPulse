import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { getInvestorMe, listMyHoldings, type InvestorAppHolding } from "@/api/investors";
import { isApiError } from "@/api/errors";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { bboxOfGeometry } from "@/lib/geometry";
import { localizedName } from "@/lib/localizedField";
import { AreaDisplay } from "@/modules/farms/components/AreaDisplay";

const RASTER_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors",
    },
  },
  layers: [{ id: "osm", type: "raster", source: "osm" }],
};

/** The holding over its block outline. Nothing else of the farm is drawn. */
function HoldingMap({ holding }: { holding: InvestorAppHolding }): JSX.Element {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!ref.current) return;
    const [minX, minY, maxX, maxY] = bboxOfGeometry(holding.block_boundary);
    const map = new maplibregl.Map({
      container: ref.current,
      style: RASTER_STYLE,
      bounds: [
        [minX, minY],
        [maxX, maxY],
      ],
      fitBoundsOptions: { padding: 30 },
    });
    const resize = new ResizeObserver(() => map.resize());
    resize.observe(ref.current);
    map.on("load", () => {
      map.resize();
      map.fitBounds(
        [
          [minX, minY],
          [maxX, maxY],
        ],
        { padding: 30, duration: 0 },
      );
      map.addSource("block", {
        type: "geojson",
        data: { type: "Feature", properties: {}, geometry: holding.block_boundary },
      });
      map.addLayer({
        id: "block-line",
        type: "line",
        source: "block",
        paint: { "line-color": "#16a34a", "line-width": 2, "line-dasharray": ["literal", [2, 1]] },
      });
      map.addSource("holding", {
        type: "geojson",
        data: { type: "Feature", properties: {}, geometry: holding.boundary },
      });
      map.addLayer({
        id: "holding-fill",
        type: "fill",
        source: "holding",
        paint: { "fill-color": "#facc15", "fill-opacity": 0.45 },
      });
      map.addLayer({
        id: "holding-line",
        type: "line",
        source: "holding",
        paint: { "line-color": "#a16207", "line-width": 2 },
      });
    });
    return () => {
      resize.disconnect();
      map.remove();
    };
  }, [holding]);
  return (
    <div
      ref={ref}
      data-testid="my-holding-map"
      className="h-80 w-full overflow-hidden rounded-md border border-ap-line"
    />
  );
}

/** /my-holdings — what an Investor user sees in the web app. Read-only. */
export function MyHoldingsPage(): JSX.Element {
  const { t, i18n } = useTranslation("investors");
  const lang = i18n.language;
  const meQ = useQuery({ queryKey: ["investor-app", "me"], queryFn: getInvestorMe });
  const listQ = useQuery({ queryKey: ["investor-app", "holdings"], queryFn: listMyHoldings });
  const [selectedId, setSelectedId] = useState<string | null>(null);

  if (meQ.isError || listQ.isError) {
    const err = meQ.error ?? listQ.error;
    const notLinked = isApiError(err) && err.status === 404;
    return <ErrorState message={notLinked ? t("my.notLinked") : t("my.loadFailed")} />;
  }
  if (!meQ.data || !listQ.data) return <Skeleton className="m-6 h-64 rounded-xl" />;

  const me = meQ.data;
  const rows = listQ.data;
  const selected = rows.find((r) => r.holding_id === selectedId) ?? rows[0] ?? null;
  const company = me.company_name ?? "";
  const crop = (h: InvestorAppHolding): string | null => {
    const c = localizedName(lang, h.crop_name_en ?? "", h.crop_name_ar);
    const v = h.variety_name_en ? localizedName(lang, h.variety_name_en, h.variety_name_ar) : null;
    return c ? (v ? `${c} · ${v}` : c) : null;
  };
  const fact = (label: string, value: React.ReactNode) => (
    <div className="flex flex-col">
      <dt className="text-xs text-ap-muted">{label}</dt>
      <dd className="text-sm text-ap-ink">{value ?? "—"}</dd>
    </div>
  );

  return (
    <Page>
      <PageHeader
        title={t("my.title")}
        subtitle={`${localizedName(lang, me.full_name, me.full_name_ar)} · ${me.code}${
          company ? ` · ${company}` : ""
        }`}
      />
      {rows.length === 0 ? (
        <EmptyState message={t("my.empty")} action={null} />
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <ul className="flex flex-col gap-2">
            {rows.map((h) => {
              const active = selected?.holding_id === h.holding_id;
              return (
                <li key={`${h.holding_id}-${h.start_date}`}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(h.holding_id)}
                    className={
                      "w-full rounded-md border px-3 py-2 text-start text-sm transition-colors " +
                      (active
                        ? "border-ap-primary bg-ap-primary-soft"
                        : "border-ap-line bg-ap-panel hover:bg-ap-line/40")
                    }
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="font-medium text-ap-ink">
                        {localizedName(lang, h.name, h.name_ar)}
                      </span>
                      <Pill kind={h.period === "current" ? "ok" : "neutral"}>
                        {t(`my.${h.period}`)}
                      </Pill>
                    </span>
                    <span className="block text-xs text-ap-muted">
                      {localizedName(lang, h.farm_name ?? "", h.farm_name_ar)} ·{" "}
                      {h.block_code ?? ""} ·{" "}
                      <AreaDisplay areaM2={Number(h.area_m2)} fractionDigits={2} />
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          {selected ? (
            <div className="flex flex-col gap-4 lg:col-span-2">
              <Card>
                <HoldingMap holding={selected} />
                <p className="mt-2 text-xs text-ap-muted">{t("my.mapLegend")}</p>
              </Card>
              <Card
                title={`${selected.code} · ${localizedName(lang, selected.name, selected.name_ar)}`}
              >
                <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  {fact(
                    t("my.farm"),
                    localizedName(lang, selected.farm_name ?? "", selected.farm_name_ar),
                  )}
                  {fact(
                    t("my.block"),
                    // A block named after its own code would read "009 · 009".
                    [
                      ...new Set([
                        selected.block_code,
                        selected.block_name
                          ? localizedName(lang, selected.block_name, selected.block_name_ar)
                          : null,
                      ]),
                    ]
                      .filter(Boolean)
                      .join(" · "),
                  )}
                  {fact(
                    t("my.area"),
                    <AreaDisplay areaM2={Number(selected.area_m2)} fractionDigits={2} />,
                  )}
                  {fact(t("my.trees"), selected.tree_count)}
                  {fact(t("my.crop"), crop(selected))}
                  {fact(t("my.planted"), selected.planting_date)}
                  {fact(t("my.ownedSince"), selected.start_date)}
                  {selected.end_date ? fact(t("my.ownedUntil"), selected.end_date) : null}
                </dl>
                {company ? (
                  <p className="mt-3 text-xs text-ap-muted">{t("my.note", { company })}</p>
                ) : null}
              </Card>
            </div>
          ) : null}
        </div>
      )}
    </Page>
  );
}
