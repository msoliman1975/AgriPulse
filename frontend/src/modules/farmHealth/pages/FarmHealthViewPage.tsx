// Farm Health View — a farm coloured by what one decision tree says.
//
// The shell: a tree picker, a block rail, a map, the replay under it, and a
// panel that says what the tree concluded about the selected block.
//
// Two rules govern how it loads, both from Mohamed's 2026-09-10 pass:
//
//   * Nothing is blocked on a read it does not need. The blocks, the legend
//     and the current verdicts are the screen; the grid's cell geometry and
//     the replay's history are extras that arrive later and light up the
//     parts that need them. Waiting for all five was most of the wait, and
//     on the reference farm — every verdict block-scoped — the grid read was
//     paid for and never used.
//   * The map opens already framed on the farm. See `HealthMap`.
//
// See docs/proposals/farm-health-view-screen.md.

import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Navigate } from "react-router-dom";

import { listBlocks, type BlockListItem } from "@/api/blocks";
import { getFarmGridCells, type FarmGridCellsResponse } from "@/api/grid";
import { getFarmVerdictHistory } from "@/api/farmHealth";
import { getFarm } from "@/api/farms";
import {
  getFarmVerdicts,
  getVerdictStatuses,
  type FarmVerdicts,
  type StatusCode,
  type StatusDefinition,
} from "@/api/farmHealth";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { EmptyState } from "@/components/EmptyState";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Resizer } from "@/components/Resizer";
import type { AsyncState } from "@/components/asyncState";
import type { Polygon } from "geojson";
import { useActiveFarmId } from "@/hooks/useActiveFarm";
import { useCapability } from "@/rbac/useCapability";
import { BlockList } from "../components/BlockList";
import {
  AreaChips,
  AreaDetail,
  BlockSummary,
  BlockVerdictDetail,
  PanelSections,
} from "../components/AreaPanel";
import { HealthMap, type FitMode, type MapBlock, type MapCell } from "../components/HealthMap";
import { MapDate } from "../components/MapDate";
import { Transport } from "../components/Transport";
import { buildAreas, pickArea, type AreaCell } from "../lib/areas";
import { usePanelSize } from "../lib/panelSize";
import {
  DEFAULT_RANGE,
  byBlock,
  customWindow,
  dateOf,
  dayOf,
  isoOf,
  rangeWindow,
  verdictsOn,
  windowLength,
  type DayWindow,
  type RangeId,
} from "../lib/window";
import { buildBlockRows, treeOptions, type BlockMeta } from "../lib/blockRows";

interface HealthData {
  blocks: BlockListItem[];
  statuses: StatusDefinition[];
  verdicts: FarmVerdicts;
  /** Null until the grid read lands, and for ever on an ungridded farm. */
  grid: FarmGridCellsResponse | null;
  /** True while a needed grid read is still in flight. */
  gridPending: boolean;
  /** Every verdict that stood at any point in the window, as intervals. */
  history: FarmVerdicts["blocks"][number]["verdicts"];
  /** False while the history is still being read. The replay waits on it. */
  historyReady: boolean;
  /** True when the history read failed. The replay says so and stays off. */
  historyFailed: boolean;
  truncated: boolean;
}

/** The rail's width and the map's height, in pixels, before anyone drags. */
const RAIL_DEFAULT = 308;
const RAIL_MIN = 200;
const RAIL_MAX = 560;
const MAP_DEFAULT = 380;
const MAP_MIN = 180;
const MAP_MAX = 900;

export function FarmHealthViewPage(): ReactNode {
  const { t, i18n } = useTranslation(["farmHealth", "common"]);
  const arabic = i18n.language.startsWith("ar");
  const farmId = useActiveFarmId();
  const canRead = useCapability("recommendation.read", { farmId });
  const [treeCode, setTreeCode] = useState<string | null>(null);
  const [blockId, setBlockId] = useState<string | null>(null);
  const [areaKey, setAreaKey] = useState<string | null>(null);
  const [hoveredKey, setHoveredKey] = useState<string | null>(null);
  // One flag for the screen, not per area: opening the reasoning is a mode a
  // reader stays in while stepping through areas.
  const [reasoningOpen, setReasoningOpen] = useState(false);
  // Which whole-block verdict has its reasoning open. An id rather than a
  // boolean because a block can hold one verdict per tree, and two cards open
  // at once would push the map off screen.
  const [openVerdictId, setOpenVerdictId] = useState<string | null>(null);
  const [fitMode, setFitMode] = useState<FitMode>("block");

  // The panels a reader can resize. Remembered per browser, because the
  // reason someone widened the rail — long block names — is still true on
  // their next visit.
  const [railWidth, setRailWidth] = usePanelSize("rail", RAIL_DEFAULT);
  const [mapHeight, setMapHeight] = usePanelSize("map", MAP_DEFAULT);

  // The clock is read once per mount. Reading it per render would move the
  // window under a replay that is running across midnight.
  const [today] = useState(() => dayOf(new Date()));
  const [rangeId, setRangeId] = useState<RangeId>(DEFAULT_RANGE);
  const [win, setWin] = useState<DayWindow>(() => rangeWindow("30", today));
  const [dayIndex, setDayIndex] = useState(() => windowLength(rangeWindow("30", today)) - 1);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);

  const days = windowLength(win);
  const atLatest = dayIndex >= days - 1;

  const farmQuery = useQuery({
    queryKey: ["farm", farmId],
    queryFn: () => getFarm(farmId as string),
    enabled: Boolean(farmId),
  });
  const blocksQuery = useQuery({
    // The map needs every polygon, and the list endpoint will hand them all
    // over in one call rather than a GET per block.
    queryKey: ["blocks", farmId, "with-boundary"],
    queryFn: () => listBlocks(farmId as string, { include_boundary: true }),
    enabled: Boolean(farmId),
  });
  // The legend. Served rather than shipped in the bundle, so the colours the
  // map paints and the ranks the backend sorts by cannot drift apart.
  const statusesQuery = useQuery({
    queryKey: ["verdict-statuses"],
    queryFn: getVerdictStatuses,
    staleTime: 60 * 60 * 1000,
  });
  const verdictsQuery = useQuery({
    queryKey: ["farm-verdicts", farmId],
    queryFn: () => getFarmVerdicts(farmId as string),
    enabled: Boolean(farmId),
  });

  // Does any tree on this farm answer per cell? Only then is the grid worth
  // reading. It is the heaviest call on the screen — every cell of every
  // block, with geometry — and on a farm whose trees are all block-scoped it
  // was fetched, waited for, and then thrown away.
  const needsCells = useMemo(
    () =>
      (verdictsQuery.data?.blocks ?? []).some((block) =>
        block.verdicts.some((verdict) => verdict.cell_id !== null),
      ),
    [verdictsQuery.data],
  );
  // Cell geometry. It is the same on every replay frame and for every tree,
  // so it is fetched once per farm and joined on cell_id, rather than
  // travelling with each verdict.
  const gridQuery = useQuery({
    queryKey: ["farm-grid-cells", farmId],
    queryFn: () => getFarmGridCells(farmId as string, "ndvi"),
    enabled: Boolean(farmId) && needsCells,
    staleTime: 60 * 60 * 1000,
  });
  // The whole window in one read. Asking per day would be 365 requests for a
  // farm whose answers change a handful of times, and the client rebuilds
  // each frame from the intervals with the same test the SQL uses.
  const historyQuery = useQuery({
    queryKey: ["farm-verdict-history", farmId, win.fromDay, win.toDay],
    queryFn: () =>
      getFarmVerdictHistory(farmId as string, isoOf(win.fromDay), isoOf(win.toDay + 1)),
    enabled: Boolean(farmId),
    staleTime: 5 * 60 * 1000,
  });

  // Three reads, one ladder, and only three. `queryState` takes a single
  // query, so the combination is written out: the first failure wins, and
  // nothing renders until all three have data — a rail built from blocks
  // without verdicts would show every block as "tree did not run".
  //
  // The grid and the history are NOT in the ladder. Neither is needed to
  // draw the newest day, which is the day the screen opens on, and blocking
  // on them made the wait the slowest of five reads instead of the slowest
  // of three. What each one gates instead:
  //   * the grid — the cell layer and the area list, which have nothing to
  //     draw until it lands anyway;
  //   * the history — the replay controls, which are disabled and say so
  //     rather than drawing today's verdicts under an older date.
  const state: AsyncState<HealthData> = useMemo(() => {
    for (const query of [blocksQuery, statusesQuery, verdictsQuery]) {
      if (query.isError) {
        return { status: "error", error: query.error, retry: () => void query.refetch() };
      }
    }
    if (!blocksQuery.data || !statusesQuery.data || !verdictsQuery.data) {
      return { status: "loading" };
    }
    return {
      status: "success",
      data: {
        blocks: blocksQuery.data.items,
        statuses: statusesQuery.data,
        verdicts: verdictsQuery.data,
        grid: gridQuery.data ?? null,
        // `isPending`, not `!data`: `getFarmGridCells` resolves to NULL on a
        // 404, so a farm with no grid would sit under "reading the cell
        // grid" for ever. A disabled query is also pending, which is why
        // `needsCells` gates it.
        gridPending: needsCells && gridQuery.isPending,
        history: historyQuery.data?.verdicts ?? [],
        // An errored history is NOT ready. It resolves to an empty list, and
        // a replay drawn from that paints every block "tree did not run" on
        // every past day — a wrong map with no sign that anything failed.
        historyReady: !historyQuery.isPending && !historyQuery.isError,
        historyFailed: historyQuery.isError,
        truncated: historyQuery.data?.truncated ?? false,
      },
    };
  }, [blocksQuery, statusesQuery, verdictsQuery, gridQuery, historyQuery, needsCells]);

  if (!farmId) return <Navigate to="/farms" replace />;
  if (!canRead) return <Navigate to="/" replace />;

  return (
    <Page width="bleed">
      <div className="flex h-full flex-col">
        <div className="border-b border-ap-line bg-ap-panel px-4 py-3">
          <PageHeader title={t("farmHealth:title")} subtitle={farmQuery.data?.name ?? undefined} />
        </div>

        <AsyncBoundary
          state={state}
          empty={<EmptyState message={t("farmHealth:empty.noTrees")} />}
          isEmpty={(data) => data.verdicts.blocks.length === 0}
        >
          {(data) => {
            // On the newest day the live read is the truth; on any earlier
            // day the frame is rebuilt from the intervals. Both produce the
            // same shape, so nothing below knows which it is looking at.
            const frameBlocks = atLatest
              ? data.verdicts.blocks
              : [...byBlock(verdictsOn(data.history, win.fromDay + dayIndex))].map(
                  ([blockId, verdicts]) => ({
                    block_id: blockId,
                    as_of: null,
                    worst_status: null,
                    last_evaluated_at: null,
                    verdicts,
                  }),
                );
            // The picker is built from the live read PLUS the whole window's
            // history, never from the frame on show.
            //
            // Built from the frame it rewrote itself during a replay: a tree
            // that said nothing on 12 August vanished from the list on that
            // frame and came back on the next one. Built from the live read
            // alone it loses a tree that ran earlier in the window and has
            // since stopped — which is exactly the tree someone opens a
            // replay to look at. The history covers the window, so this list
            // is the same on every frame of it.
            const trees = treeOptions(
              [
                ...data.verdicts.blocks,
                {
                  block_id: "__history",
                  as_of: null,
                  worst_status: null,
                  last_evaluated_at: null,
                  verdicts: data.history,
                },
              ],
              arabic,
            );
            // The picker defaults to the first tree that has said anything
            // here. A tree with no verdict on this farm paints an entirely
            // blank screen, which a reader cannot tell from a broken one.
            const activeTree = treeCode ?? trees[0]?.code ?? null;
            const activeTreeName =
              trees.find((tree) => tree.code === activeTree)?.label ?? activeTree;
            const blocks: BlockMeta[] = data.blocks.map((block) => ({
              id: block.id,
              code: block.code,
              name: block.name ?? block.code,
            }));
            const rows = buildBlockRows(blocks, frameBlocks, activeTree, data.statuses);
            const selectedBlockId = blockId ?? rows[0]?.blockId ?? null;
            const selected = rows.find((row) => row.blockId === selectedBlockId) ?? null;

            const colorFor = new Map(data.statuses.map((s) => [s.code, s.color]));
            const colorOf = (status: StatusCode): string => colorFor.get(status) ?? "#9AA0A6";

            // Every block's worst verdict for the chosen tree, which is what
            // the map paints. `rows` already holds it, and a block-scoped
            // tree has no cells, so this is the only colour it can show.
            const worstByBlock = new Map(rows.map((row) => [row.blockId, row.worst]));
            const mapBlocks: MapBlock[] = data.blocks
              .filter((block): block is BlockListItem & { boundary: Polygon } =>
                Boolean(block.boundary),
              )
              .map((block) => ({
                blockId: block.id,
                code: block.code,
                boundary: block.boundary,
                selected: block.id === selectedBlockId,
                status: worstByBlock.get(block.id) ?? null,
              }));

            // Geometry from the grid read, verdict from the farm read, joined
            // on cell_id. A cell with geometry and no verdict is left out:
            // the tree did not reach it, and painting it any colour would say
            // otherwise.
            const gridBlock = data.grid?.blocks.find((b) => b.block_id === selectedBlockId);
            const statusByCell = new Map<string, StatusCode>();
            if (selected) {
              for (const verdict of selected.verdicts) {
                if (verdict.cell_id) statusByCell.set(verdict.cell_id, verdict.status_code);
              }
            }
            const mapCells: MapCell[] = (gridBlock?.cells ?? [])
              .filter((cell) => statusByCell.has(cell.cell_id))
              .map((cell) => ({
                cellId: cell.cell_id,
                row: cell.row_idx,
                col: cell.col_idx,
                ring: (cell.geometry.coordinates[0] ?? []) as [number, number][],
                status: statusByCell.get(cell.cell_id) as StatusCode,
              }));
            const geometryByCell = new Map(
              (gridBlock?.cells ?? []).map((cell) => [cell.cell_id, cell]),
            );
            const areaCells: AreaCell[] = [];
            if (selected) {
              for (const verdict of selected.verdicts) {
                const geometry = verdict.cell_id ? geometryByCell.get(verdict.cell_id) : undefined;
                if (!verdict.cell_id || !geometry) continue;
                areaCells.push({
                  cellId: verdict.cell_id,
                  row: geometry.row_idx,
                  col: geometry.col_idx,
                  status: verdict.status_code,
                  leafNodeId: verdict.leaf_node_id,
                  verdict,
                });
              }
            }
            const gridRows =
              areaCells.length > 0 ? Math.max(...areaCells.map((c) => c.row)) + 1 : 0;
            const gridCols =
              areaCells.length > 0 ? Math.max(...areaCells.map((c) => c.col)) + 1 : 0;
            // Whole-block verdicts: the ones with no cell. A block tree
            // writes exactly one, and it is the only thing on this screen
            // that can say what the tree concluded about the block itself.
            const blockVerdicts = (selected?.verdicts ?? []).filter(
              (verdict) => verdict.cell_id === null,
            );
            const areas = buildAreas(areaCells, gridRows, gridCols);
            const activeArea = pickArea(areas, areaKey);
            // Hover wins over selection, so pointing at a chip previews it on
            // the map without committing to it.
            const shownArea = hoveredKey
              ? (areas.find((area) => area.key === hoveredKey) ?? activeArea)
              : activeArea;
            const highlighted = new Set((shownArea?.cells ?? []).map((cell) => cell.cellId));

            // The block holds cell verdicts and the geometry that turns them
            // into areas is still in flight. Saying "no cell verdicts" here
            // would be false, and saying nothing reads as a broken panel.
            //
            // Gated on the READ, not on the result: a grid that has landed
            // and holds nothing for this block is an answer, and the sentence
            // for it is the one below.
            const cellsPending = data.gridPending && statusByCell.size > 0;

            const currentDay = win.fromDay + dayIndex;
            const dateText = new Intl.DateTimeFormat(i18n.language, {
              weekday: "short",
              day: "numeric",
              month: "short",
              year: "numeric",
              timeZone: "UTC",
            }).format(dateOf(currentDay));

            return (
              <div className="flex min-h-0 flex-1 flex-col">
                <div className="flex items-end gap-3 border-b border-ap-line bg-ap-panel px-4 py-2">
                  <label className="flex flex-col gap-1">
                    <span className="text-meta font-semibold uppercase tracking-wide text-ap-muted">
                      {t("farmHealth:treePicker.label")}
                    </span>
                    <select
                      aria-label={t("farmHealth:treePicker.label")}
                      value={activeTree ?? ""}
                      onChange={(event) => {
                        setTreeCode(event.target.value);
                        // The rail re-sorts for the new tree, so a block held
                        // from the old one may no longer be near the top, and
                        // its areas belong to a different tree entirely.
                        setBlockId(null);
                        setAreaKey(null);
                      }}
                      className="min-w-[16rem] rounded border border-ap-line bg-ap-panel px-2 py-1.5 text-sm"
                    >
                      {/* The tree's name, in the reader's language. The value
                          stays the code, because that is what a verdict row
                          carries and what the rail filters on. */}
                      {trees.map((tree) => (
                        <option key={tree.code} value={tree.code}>
                          {tree.label}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>

                {data.truncated ? (
                  <p className="border-b border-ap-line bg-ap-warn-soft px-4 py-2 text-sm text-ap-warn">
                    {t("farmHealth:range.truncated")}
                  </p>
                ) : null}

                <div className="flex min-h-0 flex-1">
                  <aside
                    className="flex min-h-0 shrink-0 flex-col overflow-y-auto bg-ap-panel"
                    style={{ width: `${railWidth}px` }}
                  >
                    <div className="border-b border-ap-line px-3 py-2.5">
                      <span className="text-meta font-semibold uppercase tracking-wide text-ap-muted">
                        {t("farmHealth:rail.heading")}
                      </span>
                    </div>
                    <BlockList
                      rows={rows}
                      statuses={data.statuses}
                      selectedBlockId={selectedBlockId}
                      onSelect={(id) => {
                        setBlockId(id);
                        setAreaKey(null);
                        setFitMode("block");
                      }}
                    />
                  </aside>

                  <Resizer
                    orientation="vertical"
                    value={railWidth}
                    min={RAIL_MIN}
                    max={RAIL_MAX}
                    onChange={setRailWidth}
                    label={t("farmHealth:resize.rail")}
                    // Under RTL the rail sits on the right, so the drag that
                    // widens it is the one going left.
                    reversed={arabic}
                  />

                  <section className="flex min-h-0 min-w-0 flex-1 flex-col">
                    <div
                      className="relative shrink-0 border-b border-ap-line"
                      style={{ height: `${mapHeight}px` }}
                    >
                      <div className="absolute inset-inline-start-3 top-3 z-10 flex flex-col items-start gap-1.5">
                        {(
                          [
                            ["block", "farmHealth:map.fitBlock"],
                            ["area", "farmHealth:map.fitArea"],
                            ["farm", "farmHealth:map.fitFarm"],
                          ] as [FitMode, string][]
                        ).map(([mode, key]) => (
                          <button
                            key={mode}
                            type="button"
                            aria-pressed={fitMode === mode}
                            onClick={() => setFitMode(mode)}
                            className={[
                              "rounded border px-2.5 py-1 text-meta shadow-sm",
                              fitMode === mode
                                ? "border-ap-primary bg-ap-primary text-white"
                                : "border-ap-line bg-ap-panel text-ap-ink",
                            ].join(" ")}
                          >
                            {t(key)}
                          </button>
                        ))}
                      </div>
                      <MapDate text={dateText} dayKey={currentDay} />
                      <HealthMap
                        blocks={mapBlocks}
                        cells={mapCells}
                        highlighted={highlighted}
                        colorOf={colorOf}
                        onSelectBlock={(id) => {
                          setBlockId(id);
                          setAreaKey(null);
                          // Clicking a block in the whole-farm view is a
                          // request to look at that block.
                          setFitMode("block");
                        }}
                        onSelectCell={(cellId) => {
                          const found = areas.find((area) =>
                            area.cells.some((cell) => cell.cellId === cellId),
                          );
                          if (found) setAreaKey(found.key);
                        }}
                        fitMode={fitMode}
                        fitKey={`${selectedBlockId ?? ""}|${activeArea?.key ?? ""}`}
                      />
                    </div>

                    {/* Directly under the map, so the control and the picture
                        it moves are next to each other. */}
                    <Transport
                      win={win}
                      dayIndex={dayIndex}
                      rangeId={rangeId}
                      today={today}
                      playing={playing}
                      speed={speed}
                      ready={data.historyReady}
                      failed={data.historyFailed}
                      onDayIndex={setDayIndex}
                      onRange={(next) => {
                        setPlaying(false);
                        setRangeId(next);
                        if (next !== "custom") {
                          const w = rangeWindow(next, today);
                          setWin(w);
                          // A new window always opens on its newest day.
                          setDayIndex(windowLength(w) - 1);
                        }
                      }}
                      onCustom={(fromIso, toIso) => {
                        const w = customWindow(fromIso, toIso, today);
                        if (!w) return;
                        setPlaying(false);
                        setRangeId("custom");
                        setWin(w);
                        setDayIndex(windowLength(w) - 1);
                      }}
                      onPlay={() => setPlaying(true)}
                      onStop={() => setPlaying(false)}
                      onSpeed={setSpeed}
                    />

                    <Resizer
                      orientation="horizontal"
                      value={mapHeight}
                      min={MAP_MIN}
                      max={MAP_MAX}
                      onChange={setMapHeight}
                      label={t("farmHealth:resize.map")}
                    />

                    <div className="min-h-0 flex-1 overflow-y-auto p-4">
                      {selected === null ? (
                        <p className="text-sm text-ap-muted">{t("farmHealth:empty.noBlock")}</p>
                      ) : (
                        // One frame around the whole answer: what the block
                        // reads as, what the tree said about it, and the area
                        // in focus. They were three cards until 2026-09-10.
                        <PanelSections>
                          <BlockSummary
                            row={selected}
                            statuses={data.statuses}
                            rows={gridRows}
                            cols={gridCols}
                            treeName={activeTreeName}
                          />

                          {/* A block tree writes one verdict with no cell, so
                              it makes no areas. Without this the panel showed
                              a colour and a count and never the sentence the
                              tree wrote, on the screen whose whole job is to
                              say why. */}
                          {blockVerdicts.map((verdict) => (
                            <BlockVerdictDetail
                              key={verdict.id}
                              verdict={verdict}
                              statuses={data.statuses}
                              farmId={farmId}
                              blockId={selected.blockId}
                              open={openVerdictId === verdict.id}
                              onToggle={() =>
                                setOpenVerdictId((was) => (was === verdict.id ? null : verdict.id))
                              }
                            />
                          ))}

                          {areas.length === 0 ? (
                            cellsPending ? (
                              <section>
                                <p className="text-sm text-ap-muted">
                                  {t("farmHealth:area.loading")}
                                </p>
                              </section>
                            ) : // The summary above already says it when the
                            // tree did not run; saying it twice reads as two
                            // different facts.
                            selected.didNotRun ? null : (
                              <section>
                                <p className="text-sm text-ap-muted">{t("farmHealth:area.none")}</p>
                              </section>
                            )
                          ) : (
                            <section>
                              <div className="flex flex-wrap items-baseline gap-3">
                                <span className="text-meta font-semibold uppercase tracking-wide text-ap-muted">
                                  {t("farmHealth:area.heading")}
                                </span>
                                <span className="text-meta text-ap-muted">
                                  {t("farmHealth:area.hint", { count: areas.length })}
                                </span>
                              </div>
                              <div className="mt-2">
                                <AreaChips
                                  areas={areas}
                                  statuses={data.statuses}
                                  selectedKey={activeArea?.key ?? null}
                                  onSelect={setAreaKey}
                                  onHover={setHoveredKey}
                                />
                              </div>
                              {activeArea ? (
                                <AreaDetail
                                  area={activeArea}
                                  statuses={data.statuses}
                                  farmId={farmId}
                                  blockId={selected.blockId}
                                  open={reasoningOpen}
                                  onToggle={() => setReasoningOpen((was) => !was)}
                                />
                              ) : null}
                            </section>
                          )}
                        </PanelSections>
                      )}
                    </div>
                  </section>
                </div>
              </div>
            );
          }}
        </AsyncBoundary>
      </div>
    </Page>
  );
}
