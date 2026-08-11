// /platform/catalog — the crop catalog console.
//
// A second, additive surface beside /platform/crops, which keeps working
// unchanged. Two things brought it about:
//
//   * Density. The old screen lets a crop form, a variety form and a strain
//     form erupt inside the same tree at once, each shoving the rows below it
//     down the page. Here the tree only selects; a stable inspector describes
//     whatever is selected, and no form ever moves the rail.
//
//   * Reach. Most of the crop catalog had no UI at all. Stage ladders, canopy
//     size classes and the GDD temperatures are first-class catalog data that
//     the admin API accepts on every taxonomy level and that no screen could
//     write — so they were set in migrations, or not at all, and every
//     stage-gated decision tree was silently unfireable for the crops that
//     lacked them. Per-variety and per-strain overrides in particular were
//     impossible: the API has taken them since the taxonomy landed.
//
// Selection is the URL (`?node=mango.alphonso&tab=stages`), which makes the
// tree an accordion — the open path *is* the selected path — and makes any
// node linkable and restorable on reload without a scrap of local state.

import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";

import type { Crop, CropVariety, CropVarietyStrain } from "@/api/crops";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { FilterChip } from "@/components/FilterChip";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { SegmentedControl } from "@/components/SegmentedControl";
import { Toolbar } from "@/components/Toolbar";
import { queryState } from "@/components/asyncState";
import { AttributesPanel } from "@/modules/admin/components/catalog/CatalogAttributes";
import { CreateCropForm, CreateNodeForm } from "@/modules/admin/components/catalog/CatalogCreate";
import {
  CropDetailsForm,
  NodeDetailsForm,
} from "@/modules/admin/components/catalog/CatalogDetails";
import {
  SizeClassesPanel,
  StagesPanel,
} from "@/modules/admin/components/catalog/CatalogInheritance";
import { CatalogTree } from "@/modules/admin/components/catalog/CatalogTree";
import { deepestLevel, type TaxonomyChain } from "@/modules/admin/lib/cropTaxonomy";
import { useCapability } from "@/rbac/useCapability";
import { useAdminCropAttributes } from "@/queries/cropAttributes";
import {
  useAdminCrops,
  useAdminStrains,
  useAdminVarieties,
  useUpdateCrop,
  useUpdateStrain,
  useUpdateVariety,
} from "@/queries/cropCatalog";

const TABS = ["details", "stages", "sizes", "attributes"] as const;
type Tab = (typeof TABS)[number];

export function PlatformCatalogPage(): ReactNode {
  const { t } = useTranslation("admin");
  const canManage = useCapability("platform.manage_crops");
  const [params, setParams] = useSearchParams();

  const nodePath = params.get("node") ?? "";
  const search = params.get("q") ?? "";
  const includeInactive = params.get("retired") === "1";
  const rawTab = params.get("tab");
  const tab: Tab = TABS.includes(rawTab as Tab) ? (rawTab as Tab) : "details";

  const setParam = (key: string, value: string | null): void =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (value === null || value === "") next.delete(key);
        else next.set(key, value);
        return next;
      },
      { replace: true },
    );

  // The selected chain is derived from the path, one level at a time — each
  // query only runs once its parent has resolved, which is also what makes
  // the rail lazy.
  const [cropCode = "", varietyCode = "", strainCode = ""] = nodePath.split(".");
  const crops = useAdminCrops(includeInactive);
  const crop: Crop | null = crops.data?.find((c) => c.code === cropCode) ?? null;

  const cropHasVarieties = crop != null && crop.classification_depth !== "crop_only";
  const varieties = useAdminVarieties(crop?.id ?? null, includeInactive, cropHasVarieties);
  const variety: CropVariety | null = varietyCode
    ? (varieties.data?.find((v) => v.code === varietyCode) ?? null)
    : null;

  const varietyHasStrains = variety != null && crop?.classification_depth === "variety_strain";
  const strains = useAdminStrains(variety?.id ?? null, includeInactive, varietyHasStrains);
  const strain: CropVarietyStrain | null = strainCode
    ? (strains.data?.find((s) => s.code === strainCode) ?? null)
    : null;

  // Attribute definitions come per crop and cover every level beneath it, so
  // one fetch serves whichever node is selected.
  const attributes = useAdminCropAttributes(crop?.id ?? null, includeInactive);

  const chain: TaxonomyChain | null = crop ? { crop, variety, strain } : null;
  const [addingCrop, setAddingCrop] = useState(false);

  return (
    <Page>
      <PageHeader
        title={t("catalog.title")}
        subtitle={t("catalog.subtitle")}
        badge={!canManage ? <Pill kind="warn">{t("crops.readonlyHint")}</Pill> : undefined}
        actions={
          canManage ? (
            <Button onClick={() => setAddingCrop((v) => !v)}>{t("crops.addCrop")}</Button>
          ) : null
        }
      />

      <Toolbar
        search={{
          value: search,
          onChange: (value) => setParam("q", value),
          placeholder: t("catalog.searchPlaceholder"),
        }}
        chips={
          <FilterChip
            active={includeInactive}
            onToggle={() => setParam("retired", includeInactive ? null : "1")}
          >
            {t("crops.showRetired")}
          </FilterChip>
        }
      />

      {addingCrop && canManage ? (
        <CreateCropForm
          onClose={() => setAddingCrop(false)}
          onCreated={(code) => {
            setAddingCrop(false);
            setParam("node", code);
          }}
        />
      ) : null}

      <AsyncBoundary
        state={queryState(crops)}
        filtered={includeInactive || Boolean(search)}
        errorMessage={t("crops.loadFailed")}
        empty={
          <Card noPadding>
            <EmptyState message={t("crops.empty")} />
          </Card>
        }
      >
        {(rows) => (
          <div className="grid gap-4 lg:grid-cols-[minmax(15rem,20rem)_1fr] lg:items-start">
            <Card
              noPadding
              className="lg:sticky lg:top-4 lg:max-h-[calc(100vh-8rem)] lg:overflow-y-auto"
            >
              <CatalogTree
                crops={rows}
                selectedPath={nodePath}
                varieties={varieties.data ?? []}
                varietiesLoading={cropHasVarieties && varieties.isLoading}
                strains={strains.data ?? []}
                strainsLoading={Boolean(varietyHasStrains) && strains.isLoading}
                search={search}
                onSelect={(path) => setParam("node", path)}
              />
            </Card>

            <Card>
              {chain === null ? (
                <EmptyState message={t("catalog.pickNode")} />
              ) : (
                <Inspector
                  chain={chain}
                  tab={tab}
                  onTab={(next) => setParam("tab", next)}
                  onSelect={(path) => setParam("node", path)}
                  canManage={canManage}
                  attributes={attributes.data ?? []}
                  attributesLoading={attributes.isLoading}
                />
              )}
            </Card>
          </div>
        )}
      </AsyncBoundary>
    </Page>
  );
}

// ---- Inspector ------------------------------------------------------------

function Inspector({
  chain,
  tab,
  onTab,
  onSelect,
  canManage,
  attributes,
  attributesLoading,
}: {
  chain: TaxonomyChain;
  tab: Tab;
  onTab: (tab: Tab) => void;
  onSelect: (path: string) => void;
  canManage: boolean;
  attributes: Parameters<typeof AttributesPanel>[0]["definitions"];
  attributesLoading: boolean;
}): ReactNode {
  const { t } = useTranslation("admin");
  const [adding, setAdding] = useState(false);
  const level = deepestLevel(chain);
  const node = chain.strain ?? chain.variety ?? chain.crop;
  const path = chain.strain?.path ?? chain.variety?.path ?? chain.crop.code;

  // A child can only be added where the crop's classification depth allows
  // one — offering "Add strain" under a variety-depth crop would produce a
  // node no block assignment can ever reference.
  const childLevel: "variety" | "strain" | null =
    level === "crop" && chain.crop.classification_depth !== "crop_only"
      ? "variety"
      : level === "variety" && chain.crop.classification_depth === "variety_strain"
        ? "strain"
        : null;

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-2 border-b border-ap-line pb-3">
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-ap-ink">{node.name_en}</h2>
          <p className="font-mono text-[11px] text-ap-primary">{path}</p>
        </div>
        <div className="flex items-center gap-2">
          <Pill kind="neutral">{t(`catalog.level.${level}`)}</Pill>
          {!node.is_active ? <Pill kind="crit">{t("crops.retired")}</Pill> : null}
          {canManage && childLevel ? (
            <button
              type="button"
              onClick={() => setAdding((v) => !v)}
              className="rounded-md border border-dashed border-ap-primary px-3 py-1 text-xs text-ap-primary hover:bg-ap-primary-soft"
            >
              {t(childLevel === "variety" ? "crops.addVariety" : "crops.addStrain")}
            </button>
          ) : null}
          {canManage ? <RetireButton chain={chain} /> : null}
        </div>
      </header>

      {adding && childLevel ? (
        <CreateNodeForm
          level={childLevel}
          parentId={childLevel === "variety" ? chain.crop.id : (chain.variety?.id ?? "")}
          parentPath={path}
          onClose={() => setAdding(false)}
          onCreated={(created) => {
            setAdding(false);
            onSelect(created);
          }}
        />
      ) : null}

      <SegmentedControl
        ariaLabel={t("catalog.tabsLabel")}
        value={tab}
        onChange={onTab}
        items={TABS.map((v) => ({ value: v, label: t(`catalog.tab.${v}`) }))}
      />

      {/* Keyed on the node so switching selection resets the tab's own form
          state instead of carrying one node's half-typed edits to another. */}
      <div key={path}>
        {tab === "details" ? (
          chain.strain ? (
            <NodeDetailsForm node={chain.strain} level="strain" canManage={canManage} />
          ) : chain.variety ? (
            <NodeDetailsForm node={chain.variety} level="variety" canManage={canManage} />
          ) : (
            <CropDetailsForm crop={chain.crop} canManage={canManage} />
          )
        ) : null}
        {tab === "stages" ? <StagesPanel chain={chain} canManage={canManage} /> : null}
        {tab === "sizes" ? <SizeClassesPanel chain={chain} canManage={canManage} /> : null}
        {tab === "attributes" ? (
          <AttributesPanel chain={chain} definitions={attributes} loading={attributesLoading} />
        ) : null}
      </div>
    </div>
  );
}

function RetireButton({ chain }: { chain: TaxonomyChain }): ReactNode {
  const { t } = useTranslation("admin");
  const updateCrop = useUpdateCrop();
  const updateVariety = useUpdateVariety();
  const updateStrain = useUpdateStrain();
  const node = chain.strain ?? chain.variety ?? chain.crop;
  const busy = updateCrop.isPending || updateVariety.isPending || updateStrain.isPending;

  const toggle = (): void => {
    const patch = { is_active: !node.is_active };
    if (chain.strain) updateStrain.mutate({ strainId: chain.strain.id, patch });
    else if (chain.variety) updateVariety.mutate({ varietyId: chain.variety.id, patch });
    else updateCrop.mutate({ cropId: chain.crop.id, patch });
  };

  return (
    <button
      type="button"
      disabled={busy}
      onClick={toggle}
      className="rounded-md border border-ap-line bg-ap-panel px-3 py-1 text-xs text-ap-ink hover:bg-ap-line/40 disabled:opacity-60"
    >
      {node.is_active ? t("crops.retire") : t("crops.restore")}
    </button>
  );
}
