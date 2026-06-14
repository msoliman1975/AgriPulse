// Farm Console — redesigned Farm Management surface (/labs/map-next).
//
// A progressive-disclosure re-take of /labs/map: slim view bar + units
// rail + a two-tier inspector (monitor by default, manage one click away),
// with farm-level config behind a settings drawer. Built as a NEW page so
// it can be iterated and A/B'd before replacing /labs/map. Reuses the
// existing data loaders (loadMapSummary / loadUnitDetail) and MapCanvas.
// See docs/proposals/farm-management-redesign.md.
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { listFarms } from "@/api/farms";
import type { Block } from "@/api/blocks";
import { loadMapSummary, loadUnitDetail } from "../map/api";
import { MapCanvas } from "../map/MapCanvas";
import type { IndexCode } from "../map/types";
import { Inspector } from "./Inspector";
import { UnitsRail } from "./UnitsRail";
import { ViewBar, type LayerState } from "./ViewBar";

const LAST_FARM_KEY = "labs/map/lastFarm";

export function FarmConsolePage(): ReactNode {
  const { farmId } = useParams<{ farmId?: string }>();
  if (!farmId) return <FarmRedirect />;
  return <Console farmId={farmId} />;
}

function FarmRedirect(): ReactNode {
  const navigate = useNavigate();
  const { t } = useTranslation("farmConsole");
  const farmsQ = useQuery({
    queryKey: ["labs/mapnext/farmsList"],
    queryFn: () => listFarms({ limit: 50 }),
    staleTime: 30_000,
  });
  useEffect(() => {
    if (!farmsQ.data) return;
    const last = typeof window !== "undefined" ? window.localStorage.getItem(LAST_FARM_KEY) : null;
    const target = farmsQ.data.items.find((f) => f.id === last) ?? farmsQ.data.items[0];
    if (target) navigate(`/labs/map-next/${target.id}`, { replace: true });
  }, [farmsQ.data, navigate]);

  return (
    <div className="grid h-full place-items-center text-sm text-ap-muted">
      {farmsQ.isLoading
        ? t("page.loadingFarms")
        : farmsQ.data && farmsQ.data.items.length === 0
          ? t("page.noFarm")
          : t("page.redirecting")}
    </div>
  );
}

function Console({ farmId }: { farmId: string }): ReactNode {
  const { t } = useTranslation("farmConsole");
  const navigate = useNavigate();
  const [search, setSearch] = useSearchParams();
  const selectedId = search.get("unit");

  const [activeIndex, setActiveIndex] = useState<IndexCode>("ndvi");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [layers, setLayers] = useState<LayerState>({
    aoi: true,
    blocks: true,
    borders: true,
    labels: true,
    borderOpacity: 0.6,
    fillOpacity: 1,
  });

  useEffect(() => {
    if (typeof window !== "undefined") window.localStorage.setItem(LAST_FARM_KEY, farmId);
  }, [farmId]);

  const summaryQ = useQuery({
    queryKey: ["labs/mapnext/summary", farmId],
    queryFn: () => loadMapSummary(farmId),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  const farmsQ = useQuery({
    queryKey: ["labs/mapnext/farmsList"],
    queryFn: () => listFarms({ limit: 50 }),
    staleTime: 60_000,
  });

  const blocksById = useMemo(() => {
    const m = new Map<string, Block>();
    for (const b of summaryQ.data?.blocks ?? []) m.set(b.id, b);
    return m;
  }, [summaryQ.data]);

  const detailQ = useQuery({
    queryKey: ["labs/mapnext/detail", farmId, selectedId],
    queryFn: () =>
      loadUnitDetail({
        farmId,
        blockId: selectedId as string,
        blocksById,
        activePlan: summaryQ.data?.activePlan,
        blockHealth: selectedId ? summaryQ.data?.blockHealth[selectedId] : null,
      }),
    enabled: Boolean(selectedId && blocksById.size > 0),
    staleTime: 30_000,
  });

  const select = (id: string) => {
    const next = new URLSearchParams(search);
    next.set("unit", id);
    setSearch(next, { replace: false });
  };
  const deselect = () => {
    const next = new URLSearchParams(search);
    next.delete("unit");
    setSearch(next, { replace: false });
  };

  const flash = (msg: string) => {
    setToast(msg);
    window.setTimeout(() => setToast((m) => (m === msg ? null : m)), 2600);
  };

  if (summaryQ.isLoading) {
    return <div className="grid h-full place-items-center text-sm text-ap-muted">{t("page.loading")}</div>;
  }
  if (summaryQ.isError || !summaryQ.data) {
    return (
      <div className="grid h-full place-items-center gap-3 text-center text-sm text-ap-muted">
        <p>{t("page.loadError")}</p>
        <button
          type="button"
          onClick={() => summaryQ.refetch()}
          className="rounded-md bg-ap-primary px-3 py-1.5 text-white"
        >
          {t("page.retry")}
        </button>
      </div>
    );
  }

  const summary = summaryQ.data;
  const farmName = summary.farm.name;
  const farms = (farmsQ.data?.items ?? [{ id: farmId, name: farmName }]).map((f) => ({ id: f.id, name: f.name }));

  return (
    <div className="flex h-full flex-col">
      <ViewBar
        farms={farms}
        farmId={farmId}
        farmName={farmName}
        onSwitchFarm={(id) => {
          deselect();
          navigate(`/labs/map-next/${id}`);
        }}
        activeIndex={activeIndex}
        onIndexChange={setActiveIndex}
        layers={layers}
        onLayersChange={(patch) => setLayers((l) => ({ ...l, ...patch }))}
        onOpenSettings={() => setSettingsOpen(true)}
      />

      <div className="flex min-h-0 flex-1">
        <UnitsRail
          blocks={summary.blocks}
          summaries={summary.summaries}
          selectedId={selectedId}
          onSelect={select}
        />

        <main className="relative min-w-0 flex-1">
          <MapCanvas
            geojson={summary.geojson}
            farmBoundary={summary.farm.boundary}
            selectedId={selectedId}
            onSelect={select}
            fitBoundsKey={farmId}
            showAoi={layers.aoi}
            showBlocks={layers.blocks}
            showBlockBorders={layers.borders}
            showBlockLabels={layers.labels}
            borderOpacity={layers.borderOpacity}
            blockFillOpacity={layers.fillOpacity}
          />
          {toast ? (
            <div className="pointer-events-none absolute left-1/2 top-3.5 z-20 -translate-x-1/2 rounded-full bg-ap-ink/85 px-3.5 py-1.5 text-[12.5px] text-white shadow-card">
              {toast}
            </div>
          ) : null}
        </main>

        {selectedId ? (
          <aside className="w-[372px] flex-none border-s border-ap-line">
            <Inspector
              detail={detailQ.data}
              loading={detailQ.isLoading}
              error={detailQ.isError}
              activeIndex={activeIndex}
              onActiveIndexChange={setActiveIndex}
              onClose={deselect}
              farmId={farmId}
              onScout={() => flash(t("page.scoutToast"))}
            />
          </aside>
        ) : null}
      </div>

      {settingsOpen ? (
        <SettingsDrawer farmId={farmId} farmName={farmName} onClose={() => setSettingsOpen(false)} />
      ) : null}
    </div>
  );
}

// Farm-level config (rare, manager-only) — for v1 this drawer deep-links
// into the existing, fully-built config pages rather than re-implementing
// them. The redesign value is the IA: one quiet entry point off the daily
// surface. Native panels can replace these links in a later iteration.
function SettingsDrawer({
  farmId,
  farmName,
  onClose,
}: {
  farmId: string;
  farmName: string;
  onClose: () => void;
}): ReactNode {
  const { t } = useTranslation("farmConsole");
  const navigate = useNavigate();
  const go = (path: string) => {
    onClose();
    navigate(path);
  };
  const Item = ({ icon, title, desc, path }: { icon: string; title: string; desc: string; path: string }) => (
    <button
      type="button"
      onClick={() => go(path)}
      className="flex w-full items-start gap-3 rounded-xl border border-ap-line bg-ap-panel p-3.5 text-start hover:bg-ap-primary-soft"
    >
      <span className="text-lg leading-none">{icon}</span>
      <span className="flex-1">
        <span className="block text-[14px] font-semibold text-ap-ink">{title}</span>
        <span className="block text-[12px] text-ap-muted">{desc}</span>
      </span>
      <span className="text-ap-muted">›</span>
    </button>
  );
  return (
    <>
      <button
        type="button"
        aria-label="Close settings"
        className="fixed inset-0 z-[90] bg-ap-ink/30"
        onClick={onClose}
      />
      <aside className="fixed inset-y-0 end-0 z-[100] flex w-[480px] max-w-[92vw] flex-col bg-ap-panel shadow-2xl">
        <div className="flex items-center gap-3 border-b border-ap-line px-5 py-4">
          <span className="text-xl">⚙</span>
          <div>
            <h2 className="text-lg font-bold text-ap-ink">{t("settings.title")}</h2>
            <div className="text-[12px] text-ap-muted">{farmName}</div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="ms-auto grid h-8 w-8 place-items-center rounded-lg text-ap-muted hover:bg-ap-line/50"
            aria-label="Close"
          >
            ✕
          </button>
        </div>
        <div className="flex-1 space-y-3 overflow-auto p-5">
          <div className="rounded-xl border border-ap-primary-soft bg-ap-primary-soft/40 p-3 text-[12.5px] text-ap-primary">
            {t("settings.note")}
          </div>
          <Item icon="🛰️" title={t("settings.defaults")} desc={t("settings.defaultsDesc")} path={`/config/imagery/${farmId}`} />
          <Item icon="👥" title={t("settings.members")} desc={t("settings.membersDesc")} path={`/farms/${farmId}/members`} />
          <Item icon="🌾" title={t("settings.farm")} desc={t("settings.farmDesc")} path={`/farms/${farmId}/edit`} />
        </div>
      </aside>
    </>
  );
}
