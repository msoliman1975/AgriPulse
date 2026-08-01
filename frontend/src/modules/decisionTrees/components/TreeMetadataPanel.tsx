// Editable tree-level metadata for the decision-tree workspace
// (experience redesign — PR-5).
//
// Two kinds of fields, both always reflecting the current working state:
//   * name / description — bound to the draft YAML's top-level keys
//     (via the parent's readTreeMeta / applyTreeMetaToYaml), so the
//     panel and the raw YAML text stay in sync bidirectionally.
//   * crop / country / soil / scope targeting — bound to a buffer
//     hydrated from the persisted tree row; persisted via PATCH on Save
//     (the saved YAML doesn't reliably carry these).
//
// Rendered as a collapsible section so it doesn't crowd the canvas.

import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { TreeMetaFields } from "../lib/metadataEdit";
import { TreeTargetingPicker } from "./TreeTargetingPicker";
import { Card } from "@/components/Card";

interface TreeMetadataPanelProps {
  meta: TreeMetaFields;
  onMetaChange: (patch: Partial<TreeMetaFields>) => void;
  cropPaths: string[];
  countryCodes: string[];
  soilTextures: string[];
  scope: "block" | "cell";
  onCropPathsChange: (next: string[]) => void;
  onCountryCodesChange: (next: string[]) => void;
  onSoilTexturesChange: (next: string[]) => void;
  onScopeChange: (next: "block" | "cell") => void;
  canEdit: boolean;
}

export function TreeMetadataPanel({
  meta,
  onMetaChange,
  cropPaths,
  countryCodes,
  soilTextures,
  scope,
  onCropPathsChange,
  onCountryCodesChange,
  onSoilTexturesChange,
  onScopeChange,
  canEdit,
}: TreeMetadataPanelProps): ReactNode {
  const { t } = useTranslation("decisionTrees");
  const [open, setOpen] = useState(true);

  return (
    <Card noPadding>
      <header className="flex items-center justify-between border-b border-ap-line px-4 py-3">
        <h2 className="text-sm font-semibold text-ap-ink">{t("workspace.metadata.heading")}</h2>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="text-xs font-medium text-ap-primary hover:underline"
          aria-expanded={open}
        >
          {open ? t("workspace.metadata.collapse") : t("workspace.metadata.expand")}
        </button>
      </header>
      {open ? (
        <div className="grid grid-cols-1 gap-4 p-4 lg:grid-cols-2">
          {/* Names + descriptions — synced with the YAML body. */}
          <div className="flex flex-col gap-3">
            <TextField
              label={t("workspace.metadata.nameEn")}
              value={meta.name_en}
              required
              readOnly={!canEdit}
              onChange={(v) => onMetaChange({ name_en: v })}
            />
            <TextField
              label={t("workspace.metadata.nameAr")}
              value={meta.name_ar}
              dir="rtl"
              readOnly={!canEdit}
              onChange={(v) => onMetaChange({ name_ar: v })}
            />
            <TextField
              label={t("workspace.metadata.descriptionEn")}
              value={meta.description_en}
              multiline
              readOnly={!canEdit}
              onChange={(v) => onMetaChange({ description_en: v })}
            />
            <TextField
              label={t("workspace.metadata.descriptionAr")}
              value={meta.description_ar}
              dir="rtl"
              multiline
              readOnly={!canEdit}
              onChange={(v) => onMetaChange({ description_ar: v })}
            />
            {canEdit && meta.name_en.trim() === "" ? (
              <p className="text-[11px] text-ap-crit">{t("workspace.metadata.nameRequired")}</p>
            ) : null}
            <p className="text-[11px] text-ap-muted">{t("workspace.metadata.namesSyncNote")}</p>
          </div>

          {/* Targeting — persisted via PATCH on Save. */}
          <div className="flex flex-col gap-3">
            {canEdit ? (
              <>
                <TreeTargetingPicker
                  cropPaths={cropPaths}
                  countryCodes={countryCodes}
                  soilTextures={soilTextures}
                  onCropPathsChange={onCropPathsChange}
                  onCountryCodesChange={onCountryCodesChange}
                  onSoilTexturesChange={onSoilTexturesChange}
                />
                <div className="flex flex-col gap-1.5 border-t border-ap-line pt-3">
                  <span className="text-xs font-medium text-ap-muted">{t("targeting.scope")}</span>
                  <div className="flex flex-wrap gap-x-4 gap-y-1">
                    {(["block", "cell"] as const).map((s) => (
                      <label key={s} className="flex items-center gap-1.5 text-xs text-ap-ink">
                        <input
                          type="radio"
                          name="workspace-tree-scope"
                          value={s}
                          checked={scope === s}
                          onChange={() => onScopeChange(s)}
                        />
                        {t(`targeting.scopeValues.${s}`)}
                      </label>
                    ))}
                  </div>
                  <span className="text-[11px] text-ap-muted">{t("targeting.scopeHint")}</span>
                </div>
              </>
            ) : (
              <ReadonlyTargeting
                cropPaths={cropPaths}
                countryCodes={countryCodes}
                soilTextures={soilTextures}
                scope={scope}
              />
            )}
          </div>
        </div>
      ) : null}
    </Card>
  );
}

function ReadonlyTargeting({
  cropPaths,
  countryCodes,
  soilTextures,
  scope,
}: {
  cropPaths: string[];
  countryCodes: string[];
  soilTextures: string[];
  scope: "block" | "cell";
}): ReactNode {
  const { t } = useTranslation("decisionTrees");
  const Row = ({
    label,
    values,
    fallback,
  }: {
    label: string;
    values: string[];
    fallback: string;
  }) => (
    <div className="flex flex-col gap-1">
      <span className="text-xs font-medium text-ap-muted">{label}</span>
      {values.length > 0 ? (
        <div className="flex flex-wrap gap-1">
          {values.map((v) => (
            <span
              key={v}
              className="rounded bg-ap-primary/10 px-1.5 py-0.5 font-mono text-[11px] text-ap-primary"
            >
              {v}
            </span>
          ))}
        </div>
      ) : (
        <span className="text-xs text-ap-muted">{fallback}</span>
      )}
    </div>
  );
  return (
    <div className="flex flex-col gap-3">
      <Row label={t("targeting.crop")} values={cropPaths} fallback={t("list.table.anyCrop")} />
      <Row
        label={t("targeting.country")}
        values={countryCodes}
        fallback={t("list.table.anyLocation")}
      />
      <Row label={t("targeting.soil")} values={soilTextures} fallback={t("list.table.anySoil")} />
      <div className="flex flex-col gap-1">
        <span className="text-xs font-medium text-ap-muted">{t("targeting.scope")}</span>
        <span className="text-xs text-ap-ink">{t(`targeting.scopeValues.${scope}`)}</span>
      </div>
    </div>
  );
}

function TextField({
  label,
  value,
  onChange,
  multiline,
  dir,
  required,
  readOnly,
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  multiline?: boolean;
  dir?: "rtl";
  required?: boolean;
  readOnly?: boolean;
}): ReactNode {
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="text-ap-muted">
        {label}
        {required ? <span className="text-ap-crit"> *</span> : null}
      </span>
      {multiline ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          dir={dir}
          rows={2}
          readOnly={readOnly}
          className="rounded-md border border-ap-line bg-ap-bg/40 px-2 py-1 text-sm text-ap-ink read-only:opacity-70"
        />
      ) : (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          dir={dir}
          readOnly={readOnly}
          className="rounded-md border border-ap-line bg-ap-bg/40 px-2 py-1 text-sm text-ap-ink read-only:opacity-70"
        />
      )}
    </label>
  );
}
