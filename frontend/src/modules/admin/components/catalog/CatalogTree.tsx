// The catalog console's left rail.
//
// The old screen let three forms erupt inside the tree at once, each shoving
// the rows below it down the page. Here the tree only ever selects: it is a
// permanent rail, and everything it can tell you about a node is told in the
// inspector beside it.
//
// The open path *is* the selected path — an accordion, not free-form
// expansion. That keeps the rail short, and it makes the selection a pure
// function of the URL, so a node can be linked to and restored on reload.

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { Crop, CropVariety, CropVarietyStrain } from "@/api/crops";

interface Props {
  crops: Crop[];
  /** Dotted path of the selected node, "" when nothing is selected. */
  selectedPath: string;
  /** Varieties of the crop on the selected path, when it has any. */
  varieties: CropVariety[];
  varietiesLoading: boolean;
  /** Strains of the variety on the selected path, when it has any. */
  strains: CropVarietyStrain[];
  strainsLoading: boolean;
  search: string;
  onSelect: (path: string) => void;
}

export function CatalogTree({
  crops,
  selectedPath,
  varieties,
  varietiesLoading,
  strains,
  strainsLoading,
  search,
  onSelect,
}: Props): ReactNode {
  const { t } = useTranslation("admin");
  const [cropCode = "", varietyCode = ""] = selectedPath.split(".");
  const needle = search.trim().toLowerCase();

  const matches = (...fields: (string | null | undefined)[]): boolean =>
    !needle || fields.some((f) => (f ?? "").toLowerCase().includes(needle));

  // A crop stays visible when it matches itself — searching narrows the rail
  // to crops, then the open crop's children are narrowed in turn. Anything
  // else would hide the node you are standing on while you type.
  const visibleCrops = crops.filter((c) => matches(c.name_en, c.name_ar, c.code));

  return (
    <nav aria-label={t("catalog.treeLabel")} className="flex flex-col">
      {visibleCrops.length === 0 ? (
        <p className="px-3 py-4 text-xs text-ap-muted">{t("catalog.noMatches")}</p>
      ) : null}
      {visibleCrops.map((crop) => {
        const open = crop.code === cropCode;
        const hasChildren = crop.classification_depth !== "crop_only";
        return (
          <div key={crop.id}>
            <TreeRow
              level={0}
              label={crop.name_en}
              secondary={crop.name_ar}
              code={crop.code}
              selected={selectedPath === crop.code}
              retired={!crop.is_active}
              caret={hasChildren ? (open ? "▾" : "▸") : ""}
              onSelect={() => onSelect(crop.code)}
              badge={
                (crop.phenology_stages?.stages?.length ?? 0) > 0 ? undefined : (
                  <span className="rounded bg-ap-warn/15 px-1.5 py-0.5 text-[10px] text-ap-warn">
                    {t("phenology.noCalendar")}
                  </span>
                )
              }
            />

            {open && hasChildren ? (
              <div>
                {varietiesLoading ? (
                  <p className="px-3 py-1.5 ps-9 text-[11px] text-ap-muted">{t("crops.loading")}</p>
                ) : varieties.length === 0 ? (
                  <p className="px-3 py-1.5 ps-9 text-[11px] text-ap-muted">
                    {t("crops.noVarieties")}
                  </p>
                ) : null}

                {varieties
                  .filter((v) => matches(v.name_en, v.name_ar, v.code))
                  .map((variety) => {
                    const vOpen = variety.code === varietyCode;
                    const vHasChildren = crop.classification_depth === "variety_strain";
                    return (
                      <div key={variety.id}>
                        <TreeRow
                          level={1}
                          label={variety.name_en}
                          secondary={variety.name_ar}
                          code={variety.path}
                          selected={selectedPath === variety.path}
                          retired={!variety.is_active}
                          caret={vHasChildren ? (vOpen ? "▾" : "▸") : ""}
                          onSelect={() => onSelect(variety.path)}
                          badge={
                            variety.phenology_stages_override ? (
                              <OwnBadge label={t("catalog.ownLadder")} />
                            ) : undefined
                          }
                        />
                        {vOpen && vHasChildren ? (
                          <div>
                            {strainsLoading ? (
                              <p className="px-3 py-1.5 ps-14 text-[11px] text-ap-muted">
                                {t("crops.loading")}
                              </p>
                            ) : strains.length === 0 ? (
                              <p className="px-3 py-1.5 ps-14 text-[11px] text-ap-muted">
                                {t("crops.noStrains")}
                              </p>
                            ) : null}
                            {strains
                              .filter((s) => matches(s.name_en, s.name_ar, s.code))
                              .map((strain) => (
                                <TreeRow
                                  key={strain.id}
                                  level={2}
                                  label={strain.name_en}
                                  secondary={strain.name_ar}
                                  code={strain.path}
                                  selected={selectedPath === strain.path}
                                  retired={!strain.is_active}
                                  caret=""
                                  onSelect={() => onSelect(strain.path)}
                                  badge={
                                    strain.phenology_stages_override ? (
                                      <OwnBadge label={t("catalog.ownLadder")} />
                                    ) : undefined
                                  }
                                />
                              ))}
                          </div>
                        ) : null}
                      </div>
                    );
                  })}
              </div>
            ) : null}
          </div>
        );
      })}
    </nav>
  );
}

function OwnBadge({ label }: { label: string }): ReactNode {
  return (
    <span className="rounded bg-ap-primary-soft px-1.5 py-0.5 text-[10px] text-ap-primary">
      {label}
    </span>
  );
}

const INDENT = ["ps-3", "ps-9", "ps-14"];

function TreeRow({
  level,
  label,
  secondary,
  code,
  selected,
  retired,
  caret,
  badge,
  onSelect,
}: {
  level: 0 | 1 | 2;
  label: string;
  secondary?: string | null;
  code: string;
  selected: boolean;
  retired: boolean;
  caret: string;
  badge?: ReactNode;
  onSelect: () => void;
}): ReactNode {
  return (
    <button
      type="button"
      aria-current={selected ? "true" : undefined}
      onClick={onSelect}
      className={`flex w-full items-center gap-2 border-s-2 py-1.5 pe-2 text-start ${INDENT[level]} ${
        selected
          ? "border-s-ap-primary bg-ap-primary-soft/60"
          : "border-s-transparent hover:bg-ap-line/30"
      } ${retired ? "opacity-60" : ""}`}
    >
      <span className="w-3 flex-shrink-0 text-[10px] text-ap-muted">{caret}</span>
      <span className="min-w-0 flex-1">
        <span className={level === 0 ? "text-sm font-medium text-ap-ink" : "text-sm text-ap-ink"}>
          {label}
        </span>
        {secondary ? <span className="ms-2 text-[11px] text-ap-muted">{secondary}</span> : null}
        <span className="block font-mono text-[10px] text-ap-muted">{code}</span>
      </span>
      {badge}
    </button>
  );
}
