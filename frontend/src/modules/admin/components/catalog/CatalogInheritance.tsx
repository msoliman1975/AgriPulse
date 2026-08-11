// Stage ladders and size classes, authored at whichever taxonomy level you
// are standing on.
//
// Both values resolve **deepest non-NULL wins** and are replaced *wholesale*,
// never merged (`farms/crop_thresholds.py`). Three consequences drive
// everything in this file:
//
//   * A node that merely inherits must not be editable in place. Editing an
//     inherited ladder would silently rewrite it for every other node
//     inheriting the same one — so the first click is always "Create an
//     override", never a surprise.
//   * An override starts as a *copy* of what it replaces. Starting from an
//     empty list would strip every stage the parent defines, and the author
//     would not find out until a block failed to advance in the field.
//   * Clearing an override is a real, supported action — the column goes back
//     to NULL and the node inherits again. So "revert to inherited" is a
//     button, not a delete-and-retype.

import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { PhenologyStage, SizeClass } from "@/api/crops";
import { PhenologyStagesEditor } from "@/modules/admin/components/PhenologyStagesEditor";
import { SizeClassesEditor } from "@/modules/admin/components/SizeClassesEditor";
import { apiMsg } from "@/modules/admin/lib/apiMsg";
import {
  deepestLevel,
  ownsValue,
  resolvePhenology,
  resolveSizeClasses,
  sourcePath,
  type TaxonomyChain,
  type TaxonomyLevel,
} from "@/modules/admin/lib/cropTaxonomy";
import { useUpdateCrop, useUpdateStrain, useUpdateVariety } from "@/queries/cropCatalog";

/** One save path per level, so a panel never has to branch on the level
 *  itself — it hands over a value and the writer picks the column. */
interface Writer {
  level: TaxonomyLevel;
  busy: boolean;
  error: unknown;
  savePhenology: (stages: PhenologyStage[] | null, onDone: () => void) => void;
  saveSizeClasses: (classes: SizeClass[] | null, onDone: () => void) => void;
}

function useWriter(chain: TaxonomyChain): Writer {
  const updateCrop = useUpdateCrop();
  const updateVariety = useUpdateVariety();
  const updateStrain = useUpdateStrain();
  const level = deepestLevel(chain);

  const mutation =
    level === "strain" ? updateStrain : level === "variety" ? updateVariety : updateCrop;

  const write = (
    patch: { phenology: PhenologyStage[] | null } | { classes: SizeClass[] | null },
    onDone: () => void,
  ): void => {
    const opts = { onSuccess: onDone };
    // The crop owns the value outright; a variety or strain holds an
    // *override* of it, which is a different column with a different name.
    if ("phenology" in patch) {
      const own = patch.phenology === null ? null : { stages: patch.phenology };
      if (level === "crop") {
        updateCrop.mutate({ cropId: chain.crop.id, patch: { phenology_stages: own } }, opts);
      } else if (level === "variety" && chain.variety) {
        updateVariety.mutate(
          { varietyId: chain.variety.id, patch: { phenology_stages_override: own } },
          opts,
        );
      } else if (chain.strain) {
        updateStrain.mutate(
          { strainId: chain.strain.id, patch: { phenology_stages_override: own } },
          opts,
        );
      }
      return;
    }
    const own = patch.classes === null ? null : { classes: patch.classes };
    if (level === "crop") {
      updateCrop.mutate({ cropId: chain.crop.id, patch: { size_classes: own } }, opts);
    } else if (level === "variety" && chain.variety) {
      updateVariety.mutate(
        { varietyId: chain.variety.id, patch: { size_classes_override: own } },
        opts,
      );
    } else if (chain.strain) {
      updateStrain.mutate(
        { strainId: chain.strain.id, patch: { size_classes_override: own } },
        opts,
      );
    }
  };

  return {
    level,
    busy: mutation.isPending,
    error: mutation.isError ? mutation.error : null,
    savePhenology: (stages, onDone) => write({ phenology: stages }, onDone),
    saveSizeClasses: (classes, onDone) => write({ classes }, onDone),
  };
}

// ---- Stage ladder ---------------------------------------------------------

export function StagesPanel({
  chain,
  canManage,
}: {
  chain: TaxonomyChain;
  canManage: boolean;
}): ReactNode {
  const { t } = useTranslation("admin");
  const [editing, setEditing] = useState(false);
  const writer = useWriter(chain);

  const resolved = resolvePhenology(chain);
  const owns = ownsValue(chain, resolved.source);
  const from = sourcePath(chain, resolved.source);
  const stages = resolved.value ?? [];

  if (editing) {
    return (
      <div className="space-y-2">
        {!owns ? <CopyWarning count={stages.length} from={from} /> : null}
        <PhenologyStagesEditor
          crop={chain.crop}
          // An override starts as a copy of what it replaces — never empty.
          initialStages={stages}
          heading={t("catalog.stagesHeading", { node: pathOf(chain) })}
          busy={writer.busy}
          onCancel={() => setEditing(false)}
          onSave={(next) => writer.savePhenology(next, () => setEditing(false))}
        />
        <SaveError error={writer.error} />
      </div>
    );
  }

  return (
    <Panel
      provenance={
        <Provenance
          owns={owns}
          from={from}
          level={writer.level}
          missing={resolved.source === null}
          ownLabel={t("catalog.stagesOwned")}
          inheritedLabel={t("catalog.stagesInherited", { from })}
          missingLabel={t("catalog.stagesMissing")}
        />
      }
      actions={
        canManage ? (
          <>
            <PrimaryAction onClick={() => setEditing(true)}>
              {owns
                ? t("catalog.edit")
                : resolved.source === null
                  ? t("catalog.createLadder")
                  : t("catalog.createOverride")}
            </PrimaryAction>
            {owns && writer.level !== "crop" ? (
              <GhostAction
                busy={writer.busy}
                onClick={() => writer.savePhenology(null, () => undefined)}
              >
                {t("catalog.revert")}
              </GhostAction>
            ) : null}
          </>
        ) : null
      }
      error={writer.error}
    >
      {stages.length === 0 ? (
        <Empty>{t("phenology.empty")}</Empty>
      ) : (
        <ol className="divide-y divide-ap-line rounded-md border border-ap-line">
          {stages
            .slice()
            .sort((a, b) => a.order - b.order)
            .map((s) => (
              <li key={s.code} className="flex items-baseline gap-2 px-3 py-2">
                <span className="w-5 text-xs text-ap-muted">{s.order}</span>
                <span className="text-sm text-ap-ink">{s.name_en}</span>
                <span className="text-[11px] text-ap-muted">{s.name_ar}</span>
                <span className="font-mono text-[10px] text-ap-primary">{s.code}</span>
                <span className="ms-auto text-[11px] text-ap-muted">{advanceSummary(s, t)}</span>
              </li>
            ))}
        </ol>
      )}
    </Panel>
  );
}

function advanceSummary(stage: PhenologyStage, t: (k: string) => string): string {
  const a = stage.advance;
  if (a.mode === "calendar_doy") return `${a.start_doy} → ${a.end_doy}`;
  if (a.mode === "days_from_planting") return `${a.start_day}–${a.end_day} d`;
  if (a.mode === "gdd_from_planting") return `${a.start_gdd}–${a.end_gdd} GDD`;
  return t("phenology.mode.manual");
}

// ---- Size classes ---------------------------------------------------------

export function SizeClassesPanel({
  chain,
  canManage,
}: {
  chain: TaxonomyChain;
  canManage: boolean;
}): ReactNode {
  const { t } = useTranslation("admin");
  const [editing, setEditing] = useState(false);
  const writer = useWriter(chain);

  const resolved = resolveSizeClasses(chain);
  const owns = ownsValue(chain, resolved.source);
  const from = sourcePath(chain, resolved.source);
  const classes = resolved.value ?? [];

  if (editing) {
    return (
      <div className="space-y-2">
        {!owns ? <CopyWarning count={classes.length} from={from} /> : null}
        <SizeClassesEditor
          classes={classes}
          heading={t("catalog.sizesHeading", { node: pathOf(chain) })}
          busy={writer.busy}
          onCancel={() => setEditing(false)}
          onSave={(next) => writer.saveSizeClasses(next, () => setEditing(false))}
        />
        <SaveError error={writer.error} />
      </div>
    );
  }

  return (
    <Panel
      provenance={
        <Provenance
          owns={owns}
          from={from}
          level={writer.level}
          missing={resolved.source === null}
          ownLabel={t("catalog.sizesOwned")}
          inheritedLabel={t("catalog.sizesInherited", { from })}
          missingLabel={t("catalog.sizesMissing")}
        />
      }
      actions={
        canManage ? (
          <>
            <PrimaryAction onClick={() => setEditing(true)}>
              {owns
                ? t("catalog.edit")
                : resolved.source === null
                  ? t("catalog.createSizes")
                  : t("catalog.createOverride")}
            </PrimaryAction>
            {owns && writer.level !== "crop" ? (
              <GhostAction
                busy={writer.busy}
                onClick={() => writer.saveSizeClasses(null, () => undefined)}
              >
                {t("catalog.revert")}
              </GhostAction>
            ) : null}
          </>
        ) : null
      }
      error={writer.error}
    >
      {classes.length === 0 ? (
        <Empty>{t("sizeClasses.empty")}</Empty>
      ) : (
        <ol className="divide-y divide-ap-line rounded-md border border-ap-line">
          {classes
            .slice()
            .sort((a, b) => a.order - b.order)
            .map((c) => (
              <li key={c.code} className="flex items-baseline gap-2 px-3 py-2">
                <span className="w-5 text-xs text-ap-muted">{c.order}</span>
                <span className="text-sm text-ap-ink">{c.name_en}</span>
                <span className="text-[11px] text-ap-muted">{c.name_ar}</span>
                <span className="font-mono text-[10px] text-ap-primary">{c.code}</span>
              </li>
            ))}
        </ol>
      )}
    </Panel>
  );
}

// ---- Shared chrome --------------------------------------------------------

function pathOf(chain: TaxonomyChain): string {
  return chain.strain?.path ?? chain.variety?.path ?? chain.crop.code;
}

function Panel({
  provenance,
  actions,
  error,
  children,
}: {
  provenance: ReactNode;
  actions: ReactNode;
  error: unknown;
  children: ReactNode;
}): ReactNode {
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        {provenance}
        <div className="flex flex-shrink-0 gap-2">{actions}</div>
      </div>
      {children}
      <SaveError error={error} />
    </section>
  );
}

function Provenance({
  owns,
  from,
  level,
  missing,
  ownLabel,
  inheritedLabel,
  missingLabel,
}: {
  owns: boolean;
  from: string | null;
  level: TaxonomyLevel;
  missing: boolean;
  ownLabel: string;
  inheritedLabel: string;
  missingLabel: string;
}): ReactNode {
  const { t } = useTranslation("admin");
  if (missing) {
    return (
      <p className="rounded-md border border-ap-warn/40 bg-ap-warn/5 px-3 py-2 text-[11px] text-ap-warn">
        {missingLabel}
      </p>
    );
  }
  if (owns) {
    return (
      <p className="rounded-md border border-ap-primary/30 bg-ap-primary-soft/50 px-3 py-2 text-[11px] text-ap-ink">
        <span className="font-medium">{ownLabel}</span>
        {level !== "crop" ? (
          <span className="ms-1 text-ap-muted">{t("catalog.ownExplainer")}</span>
        ) : null}
      </p>
    );
  }
  return (
    <p className="rounded-md border border-ap-line bg-ap-bg/40 px-3 py-2 text-[11px] text-ap-ink">
      <span className="font-medium">{inheritedLabel}</span>
      <span className="ms-1 text-ap-muted">{t("catalog.inheritedExplainer", { from })}</span>
    </p>
  );
}

/** Shown above an editor that is about to *create* an override, because the
 *  override replaces the parent's value wholesale rather than merging. */
function CopyWarning({ count, from }: { count: number; from: string | null }): ReactNode {
  const { t } = useTranslation("admin");
  return (
    <p className="rounded-md border border-ap-warn/40 bg-ap-warn/5 px-3 py-2 text-[11px] text-ap-warn">
      {count > 0 ? t("catalog.copyWarning", { count, from }) : t("catalog.emptyOverrideWarning")}
    </p>
  );
}

function Empty({ children }: { children: ReactNode }): ReactNode {
  return (
    <p className="rounded-md border border-dashed border-ap-line px-3 py-4 text-center text-[11px] text-ap-muted">
      {children}
    </p>
  );
}

function SaveError({ error }: { error: unknown }): ReactNode {
  if (!error) return null;
  return (
    <p role="alert" className="text-[11px] text-ap-crit">
      {apiMsg(error)}
    </p>
  );
}

function PrimaryAction({
  onClick,
  children,
}: {
  onClick: () => void;
  children: ReactNode;
}): ReactNode {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-md bg-ap-primary px-3 py-1.5 text-xs font-medium text-white hover:bg-ap-primary/90"
    >
      {children}
    </button>
  );
}

function GhostAction({
  onClick,
  busy,
  children,
}: {
  onClick: () => void;
  busy: boolean;
  children: ReactNode;
}): ReactNode {
  return (
    <button
      type="button"
      disabled={busy}
      onClick={onClick}
      className="rounded-md border border-ap-line bg-ap-panel px-3 py-1.5 text-xs text-ap-ink hover:bg-ap-line/40 disabled:opacity-60"
    >
      {children}
    </button>
  );
}
