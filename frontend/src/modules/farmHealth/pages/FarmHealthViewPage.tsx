// Farm Health View — a farm coloured by what one decision tree says.
//
// This is the shell: the tree picker, the block rail, and a summary of
// whichever block is selected. The map, the areas, the reasoning panel and
// the date replay land on top of it in later changes; the rail and the
// picker come first, because everything else reads its selection from them.
//
// See docs/proposals/farm-health-view-screen.md.

import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Navigate } from "react-router-dom";

import { listBlocks, type BlockListItem } from "@/api/blocks";
import { getFarmGridCells, type FarmGridCellsResponse } from "@/api/grid";
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
import type { AsyncState } from "@/components/asyncState";
import type { Polygon } from "geojson";
import { useActiveFarmId } from "@/hooks/useActiveFarm";
import { useCapability } from "@/rbac/useCapability";
import { BlockList } from "../components/BlockList";
import { AreaChips, AreaDetail, BlockSummary } from "../components/AreaPanel";
import { HealthMap, type MapBlock, type MapCell } from "../components/HealthMap";
import { buildAreas, pickArea, type AreaCell } from "../lib/areas";
import { buildBlockRows, treeOptions, type BlockMeta } from "../lib/blockRows";

interface HealthData {
  blocks: BlockListItem[];
  statuses: StatusDefinition[];
  verdicts: FarmVerdicts;
  /** Null when the farm has no grid. The map then draws blocks only. */
  grid: FarmGridCellsResponse | null;
}

export function FarmHealthViewPage(): ReactNode {
  const { t } = useTranslation(["farmHealth", "common"]);
  const farmId = useActiveFarmId();
  const canRead = useCapability("recommendation.read", { farmId });
  const [treeCode, setTreeCode] = useState<string | null>(null);
  const [blockId, setBlockId] = useState<string | null>(null);
  const [areaKey, setAreaKey] = useState<string | null>(null);
  const [hoveredKey, setHoveredKey] = useState<string | null>(null);
  // One flag for the screen, not per area: opening the reasoning is a mode a
  // reader stays in while stepping through areas.
  const [reasoningOpen, setReasoningOpen] = useState(false);

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
  // Cell geometry. It is the same on every replay frame and for every tree,
  // so it is fetched once per farm and joined on cell_id, rather than
  // travelling with each verdict.
  const gridQuery = useQuery({
    queryKey: ["farm-grid-cells", farmId],
    queryFn: () => getFarmGridCells(farmId as string, "ndvi"),
    enabled: Boolean(farmId),
    staleTime: 60 * 60 * 1000,
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

  // Three reads, one ladder. `queryState` takes a single query, so the
  // combination is written out: the first failure wins, and nothing renders
  // until all three have data — a rail built from blocks without verdicts
  // would show every block as "tree did not run".
  const state: AsyncState<HealthData> = useMemo(() => {
    for (const query of [blocksQuery, statusesQuery, verdictsQuery]) {
      if (query.isError) {
        return { status: "error", error: query.error, retry: () => void query.refetch() };
      }
    }
    if (!blocksQuery.data || !statusesQuery.data || !verdictsQuery.data) {
      return { status: "loading" };
    }
    // The grid is allowed to be absent — an ungridded farm still has blocks
    // and block-scoped verdicts — but not still loading, or the map would
    // draw once without cells and again with them.
    if (gridQuery.isPending) return { status: "loading" };
    return {
      status: "success",
      data: {
        blocks: blocksQuery.data.items,
        statuses: statusesQuery.data,
        verdicts: verdictsQuery.data,
        grid: gridQuery.data ?? null,
      },
    };
  }, [blocksQuery, statusesQuery, verdictsQuery, gridQuery]);

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
            const trees = treeOptions(data.verdicts.blocks);
            // The picker defaults to the first tree that has said anything
            // here. A tree with no verdict on this farm paints an entirely
            // blank screen, which a reader cannot tell from a broken one.
            const activeTree = treeCode ?? trees[0]?.code ?? null;
            const blocks: BlockMeta[] = data.blocks.map((block) => ({
              id: block.id,
              code: block.code,
              name: block.name ?? block.code,
            }));
            const rows = buildBlockRows(blocks, data.verdicts.blocks, activeTree, data.statuses);
            const selectedBlockId = blockId ?? rows[0]?.blockId ?? null;
            const selected = rows.find((row) => row.blockId === selectedBlockId) ?? null;

            const colorFor = new Map(data.statuses.map((s) => [s.code, s.color]));
            const colorOf = (status: StatusCode): string =>
              colorFor.get(status) ?? "#9AA0A6";

            const mapBlocks: MapBlock[] = data.blocks
              .filter((block): block is BlockListItem & { boundary: Polygon } =>
                Boolean(block.boundary),
              )
              .map((block) => ({
                blockId: block.id,
                code: block.code,
                boundary: block.boundary,
                selected: block.id === selectedBlockId,
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
            const areas = buildAreas(areaCells, gridRows, gridCols);
            const activeArea = pickArea(areas, areaKey);
            // Hover wins over selection, so pointing at a chip previews it on
            // the map without committing to it.
            const shownArea = hoveredKey
              ? (areas.find((area) => area.key === hoveredKey) ?? activeArea)
              : activeArea;
            const highlighted = new Set((shownArea?.cells ?? []).map((cell) => cell.cellId));

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
                      className="rounded border border-ap-line bg-ap-panel px-2 py-1.5 text-sm"
                    >
                      {trees.map((tree) => (
                        <option key={tree.code} value={tree.code}>
                          {tree.code}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>

                <div className="grid min-h-0 flex-1 grid-cols-[308px_minmax(0,1fr)]">
                  <aside className="min-h-0 overflow-y-auto border-e border-ap-line bg-ap-panel">
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
                      }}
                    />
                  </aside>

                  <section className="grid min-h-0 grid-rows-[minmax(240px,46%)_minmax(0,1fr)]">
                    <div className="min-h-0 border-b border-ap-line">
                      <HealthMap
                        blocks={mapBlocks}
                        cells={mapCells}
                        highlighted={highlighted}
                        colorOf={colorOf}
                        onSelectBlock={(id) => {
                          setBlockId(id);
                          setAreaKey(null);
                        }}
                        onSelectCell={(cellId) => {
                          const found = areas.find((area) =>
                            area.cells.some((cell) => cell.cellId === cellId),
                          );
                          if (found) setAreaKey(found.key);
                        }}
                        fitKey={selectedBlockId ?? ""}
                      />
                    </div>
                    <div className="grid min-h-0 gap-4 overflow-y-auto p-4">
                      {selected === null ? (
                        <p className="text-sm text-ap-muted">{t("farmHealth:empty.noBlock")}</p>
                      ) : (
                        <>
                          <BlockSummary
                            row={selected}
                            statuses={data.statuses}
                            rows={gridRows}
                            cols={gridCols}
                            treeCode={activeTree}
                          />

                          {areas.length === 0 ? (
                            // The summary above already says it when the tree
                            // did not run; saying it twice reads as two
                            // different facts.
                            selected.didNotRun ? null : (
                              <p className="text-sm text-ap-muted">
                                {t("farmHealth:area.none")}
                              </p>
                            )
                          ) : (
                            <div className="grid gap-2">
                              <div className="flex flex-wrap items-baseline gap-3">
                                <span className="text-meta font-semibold uppercase tracking-wide text-ap-muted">
                                  {t("farmHealth:area.heading")}
                                </span>
                                <span className="text-meta text-ap-muted">
                                  {t("farmHealth:area.hint", { count: areas.length })}
                                </span>
                              </div>
                              <AreaChips
                                areas={areas}
                                statuses={data.statuses}
                                selectedKey={activeArea?.key ?? null}
                                onSelect={setAreaKey}
                                onHover={setHoveredKey}
                              />
                              {activeArea ? (
                                <AreaDetail
                                  area={activeArea}
                                  farmId={farmId}
                                  blockId={selected.blockId}
                                  open={reasoningOpen}
                                  onToggle={() => setReasoningOpen((was) => !was)}
                                />
                              ) : null}
                            </div>
                          )}
                        </>
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
