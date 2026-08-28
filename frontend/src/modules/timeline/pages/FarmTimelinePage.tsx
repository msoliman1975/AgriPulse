// Farm Timeline — replay a farm, or one block, day by day.
//
// One screen, not tabs: the map on the left, the day's datapoints on the
// right, and the scrubber under both. The two halves read the same frame,
// so what is drawn and what is listed can never disagree.

import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate } from "react-router-dom";
import type { FeatureCollection, Polygon } from "geojson";

import type { AnyIndexCode } from "@/api/indices";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { EmptyState } from "@/components/EmptyState";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { queryState } from "@/components/asyncState";
import { useActiveFarmId } from "@/hooks/useActiveFarm";
import { localizedName } from "@/lib/localizedField";
import { useCapability } from "@/rbac/useCapability";
import { EventRail } from "../components/EventRail";
import { ImageDateCaption } from "../components/ImageDateCaption";
import { Scrubber } from "../components/Scrubber";
import { TimelineControls } from "../components/TimelineControls";
import { TimelineLayerBar } from "../components/TimelineLayerBar";
import { TimelineLegend } from "../components/TimelineLegend";
import { TimelineMap, type BlockFeatureProps } from "../components/TimelineMap";
import {
  BASE_FPS,
  DEFAULT_TIMELINE_INDEX,
  DEFAULT_WINDOW_DAYS,
  MAX_WINDOW_DAYS,
} from "../constants";
import { daysBetween, toDayKey } from "../lib/frames";
import { defaultLayerState, LAYER_KINDS, type TimelineLayerState } from "../lib/layerState";
import { useFarmTimeline } from "../useFarmTimeline";

function defaultWindow(): { from: string; to: string } {
  const now = new Date();
  const to = toDayKey(now);
  const from = toDayKey(new Date(now.getTime() - DEFAULT_WINDOW_DAYS * 86_400_000));
  return { from, to };
}

export function FarmTimelinePage(): ReactNode {
  const farmId = useActiveFarmId();
  const { t, i18n } = useTranslation("timeline");
  // `farm.read` is what the endpoint itself is gated on. The seven kinds
  // behind it are checked per kind by the API, which drops the ones this
  // reader cannot see and names them — so there is one check here, not
  // seven.
  const canRead = useCapability("farm.read", { farmId });

  const initial = useMemo(defaultWindow, []);
  const [blockId, setBlockId] = useState<string | null>(null);
  const [from, setFrom] = useState(initial.from);
  const [to, setTo] = useState(initial.to);
  const [index, setIndex] = useState<AnyIndexCode>(DEFAULT_TIMELINE_INDEX);
  const [layers, setLayers] = useState<TimelineLayerState>(defaultLayerState);

  // The set the hook filters on. Derived from the checkboxes rather than
  // held beside them, so there is one source of truth for "is this kind
  // on" and the map, the rail and the bar cannot drift apart.
  const visibleKinds = useMemo(
    () => new Set(LAYER_KINDS.filter((k) => layers.kinds[k])),
    [layers.kinds],
  );

  const span = daysBetween(from, to) + 1;
  const windowError =
    from > to
      ? t("controls.errorReversed")
      : span > MAX_WINDOW_DAYS
        ? t("controls.errorTooWide", { days: MAX_WINDOW_DAYS })
        : null;

  const tl = useFarmTimeline({
    farmId: farmId ?? "",
    blockId,
    // A window the API would reject is never requested. Sending it anyway
    // would replace the screen with a 422 while the reader is still
    // dragging the second date field.
    from: windowError ? initial.from : from,
    to: windowError ? initial.to : to,
    index,
    visibleKinds,
  });

  const formatDay = useMemo(() => {
    const fmt = new Intl.DateTimeFormat(i18n.language, {
      day: "numeric",
      month: "short",
      year: "numeric",
      timeZone: "UTC",
    });
    // UTC, matching the day the server bucketed on. Formatting in local
    // time would print "2 June" over a frame the whole system calls 3 June
    // for every reader east of Greenwich.
    return (day: string): string => fmt.format(new Date(`${day}T00:00:00Z`));
  }, [i18n.language]);

  const formatTime = useMemo(() => {
    const fmt = new Intl.DateTimeFormat(i18n.language, {
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "UTC",
    });
    return (iso: string): string => `${fmt.format(new Date(iso))} UTC`;
  }, [i18n.language]);

  const blockOptions = useMemo(
    () => tl.blocks.map((b) => ({ id: b.id, label: b.name?.trim() || b.code })),
    [tl.blocks],
  );

  const blockGeojson = useMemo<FeatureCollection<Polygon, BlockFeatureProps>>(() => {
    const scoped = blockId ? tl.blocks.filter((b) => b.id === blockId) : tl.blocks;
    return {
      type: "FeatureCollection",
      features: scoped
        .filter((b) => b.boundary)
        .map((b) => ({
          type: "Feature" as const,
          id: b.id,
          geometry: b.boundary as Polygon,
          properties: {
            block_id: b.id,
            block_name: localizedName(i18n.language, b.name?.trim() || b.code, b.name_ar),
            highlight: tl.highlights.get(b.id) ?? 0,
          },
        })),
    };
  }, [tl.blocks, tl.highlights, blockId, i18n.language]);

  if (!farmId) return <Navigate to="/farms" replace />;
  if (!canRead) {
    return (
      <Page>
        <PageHeader title={t("title")} />
        <p className="text-sm text-ap-muted">{t("noAccess")}</p>
      </Page>
    );
  }

  const state = queryState(tl.eventsQ);

  return (
    <Page width="bleed" className="h-full gap-0">
      <div className="flex flex-col gap-3 border-b border-ap-line bg-ap-panel px-4 py-3">
        {/* No badge. The picture's date lives on the map itself, in
            `ImageDateCaption`, where it sits next to the pixels it
            describes and where it can be read without leaving the map. */}
        <PageHeader title={t("title")} subtitle={t("subtitle")} />
        <TimelineControls
          blocks={blockOptions}
          blockId={blockId}
          onBlockChange={setBlockId}
          from={from}
          to={to}
          onWindowChange={(nextFrom, nextTo) => {
            setFrom(nextFrom);
            setTo(nextTo);
          }}
          index={index}
          onIndexChange={setIndex}
          windowError={windowError}
        />
        <TimelineLayerBar layers={layers} onChange={setLayers} omittedKinds={tl.omittedKinds} />
      </div>

      <div className="flex min-h-0 flex-1 gap-3 p-3">
        <div className="relative min-w-0 flex-1 overflow-hidden rounded-card border border-ap-line">
          <TimelineMap
            blocks={blockGeojson}
            farmBoundary={tl.farmQ.data?.boundary ?? null}
            rasterFrames={tl.rasterFrames}
            activeRasterKey={tl.activeRasterKey}
            marks={tl.marks}
            showBlocks={layers.blocks}
            showFarmBoundary={layers.farmBoundary}
            showPixels={layers.pixels}
            // Half a frame, capped at 250 ms. At 1x a frame lasts 500 ms
            // and can afford the full 250; at the 4x top speed it lasts
            // 125, and a 250 ms fade would still be running a frame later,
            // which reads as the map lagging the scrubber — the thing this
            // whole change is here to remove.
            fadeMs={Math.round(Math.min(250, 1000 / (BASE_FPS * tl.speed) / 2))}
            fitKey={`${farmId}:${blockId ?? "farm"}`}
            onMarkClick={tl.setFocusedEventId}
          />
          <ImageDateCaption imageDay={tl.imageDay} formatDay={formatDay} />

          {/* The colour key, under the date caption and sharing its
              column so the two cannot overlap at any map height.

              Physically end-side and top, matching the caption: MapLibre's
              own furniture does not mirror, and top-left is the zoom
              buttons in both directions.

              Only when the pixels are on. The replay paints no block fill
              by class, so with the layer off this panel would describe
              nothing that is on the map. */}
          {layers.pixels ? (
            <div className="pointer-events-none absolute bottom-10 right-3 top-14 z-10 flex flex-col items-end">
              <TimelineLegend
                code={index}
                className="pointer-events-auto min-h-0 w-[248px] flex-shrink overflow-y-auto bg-ap-panel/95"
              />
            </div>
          ) : null}
        </div>

        <div className="hidden min-h-0 w-96 shrink-0 lg:block">
          <AsyncBoundary
            state={state}
            skeleton="lines"
            skeletonLines={6}
            // "Nothing in the whole window" is a different sentence from
            // "nothing on this day", which the rail says for itself. Without
            // this predicate the response object is never null-ish and the
            // first case could not be told.
            isEmpty={(d) => d.events.length === 0}
            empty={<EmptyState message={t("rail.emptyWindow")} />}
          >
            {() => (
              <EventRail
                frameDay={tl.frameDay}
                visible={tl.visible}
                omittedKinds={tl.omittedKinds}
                truncated={tl.truncated}
                focusedEventId={tl.focusedEventId}
                onFocusEvent={tl.setFocusedEventId}
                formatDay={formatDay}
                formatTime={formatTime}
              />
            )}
          </AsyncBoundary>
        </div>
      </div>

      <div className="px-3 pb-3">
        <Scrubber
          frames={tl.frames}
          index={tl.frameIndex}
          onIndexChange={tl.seek}
          days={tl.days}
          passDays={tl.passDays}
          trend={tl.trend}
          playing={tl.playing}
          preparing={tl.preparing}
          onTogglePlay={tl.togglePlay}
          speed={tl.speed}
          onSpeedChange={tl.setSpeed}
          formatDay={formatDay}
        />
      </div>
    </Page>
  );
}
