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
import { getFarm } from "@/api/farms";
import {
  getFarmVerdicts,
  getVerdictStatuses,
  type FarmVerdicts,
  type StatusDefinition,
} from "@/api/farmHealth";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import type { AsyncState } from "@/components/asyncState";
import { useActiveFarmId } from "@/hooks/useActiveFarm";
import { useCapability } from "@/rbac/useCapability";
import { BlockList } from "../components/BlockList";
import { buildBlockRows, treeOptions, type BlockMeta } from "../lib/blockRows";

interface HealthData {
  blocks: BlockListItem[];
  statuses: StatusDefinition[];
  verdicts: FarmVerdicts;
}

export function FarmHealthViewPage(): ReactNode {
  const { t } = useTranslation(["farmHealth", "common"]);
  const farmId = useActiveFarmId();
  const canRead = useCapability("recommendation.read", { farmId });
  const [treeCode, setTreeCode] = useState<string | null>(null);
  const [blockId, setBlockId] = useState<string | null>(null);

  const farmQuery = useQuery({
    queryKey: ["farm", farmId],
    queryFn: () => getFarm(farmId as string),
    enabled: Boolean(farmId),
  });
  const blocksQuery = useQuery({
    queryKey: ["blocks", farmId],
    queryFn: () => listBlocks(farmId as string),
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
    return {
      status: "success",
      data: {
        blocks: blocksQuery.data.items,
        statuses: statusesQuery.data,
        verdicts: verdictsQuery.data,
      },
    };
  }, [blocksQuery, statusesQuery, verdictsQuery]);

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
                        // from the old one may no longer be near the top.
                        setBlockId(null);
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
                      onSelect={setBlockId}
                    />
                  </aside>

                  <section className="min-h-0 overflow-y-auto p-4">
                    {selected === null ? (
                      <p className="text-sm text-ap-muted">{t("farmHealth:empty.noBlock")}</p>
                    ) : (
                      <Card>
                        <h2 className="text-section-title font-semibold text-ap-ink">
                          {selected.code}
                        </h2>
                        <p className="mt-1 text-sm text-ap-muted">
                          {selected.didNotRun
                            ? t("farmHealth:block.didNotRun", { tree: activeTree })
                            : t("farmHealth:block.verdictSummary", {
                                count: selected.verdicts.length,
                                tree: activeTree,
                              })}
                        </p>
                        {/* The map, the areas and the reasoning arrive here. */}
                      </Card>
                    )}
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
