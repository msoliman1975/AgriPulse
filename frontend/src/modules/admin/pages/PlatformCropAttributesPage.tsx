import { useMemo, useState, type ReactNode } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import type { CropAttributeDefinition } from "@/api/crops";
import { isApiError } from "@/api/errors";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { Field } from "@/components/Field";
import { EmptyState } from "@/components/EmptyState";
import { FilterChip } from "@/components/FilterChip";
import { LinkButton } from "@/components/LinkButton";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { Toolbar } from "@/components/Toolbar";
import { queryState } from "@/components/asyncState";
import { AttributeInput } from "@/modules/farms/components/CropAttributesCard";
import {
  groupDefinitions,
  isRequired,
  isVisible,
  label,
  type AttributeValues,
} from "@/modules/farms/lib/cropAttributeForm";
import {
  useAdminCropAttributes,
  useCreateCropAttribute,
  useUpdateCropAttribute,
} from "@/queries/cropAttributes";
import { useAdminCrops, useAdminStrains, useAdminVarieties } from "@/queries/cropCatalog";
import { useCapability } from "@/rbac/useCapability";

import {
  CropAttributeEditor,
  draftFrom,
  emptyDraft,
  type EditorDraft,
} from "../components/CropAttributeEditor";

function apiMsg(err: unknown): string {
  return isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err);
}

/**
 * /platform/crops/:cropId/attributes — author the typed fields that appear on
 * a crop → block assignment.
 *
 * Definitions attach at any level of the taxonomy (crop / variety / strain)
 * and resolve deepest-wins, so the list is grouped by the path each one
 * attaches to. The right-hand pane renders the *actual* assignment form the
 * definitions produce, driven by real form state — an author can flip the
 * gating field and watch the gated ones appear before committing anything.
 */
export function PlatformCropAttributesPage(): ReactNode {
  const { cropId } = useParams<{ cropId: string }>();
  const { t } = useTranslation("admin");
  const canManage = useCapability("platform.manage_crops");
  const [includeInactive, setIncludeInactive] = useState(false);
  const [editing, setEditing] = useState<{ id: string | null; draft: EditorDraft } | null>(null);
  const [varietyForStrains, setVarietyForStrains] = useState<string | null>(null);

  const crops = useAdminCrops(true);
  const crop = crops.data?.find((c) => c.id === cropId) ?? null;
  const definitionsQ = useAdminCropAttributes(cropId ?? null, includeInactive);
  const varieties = useAdminVarieties(cropId ?? null, false, true);
  const strains = useAdminStrains(varietyForStrains, false, Boolean(varietyForStrains));

  const create = useCreateCropAttribute(cropId ?? "");
  const update = useUpdateCropAttribute();
  const saving = create.isPending || update.isPending;
  const saveError = create.isError
    ? apiMsg(create.error)
    : update.isError
      ? apiMsg(update.error)
      : null;

  const definitions = useMemo(() => definitionsQ.data ?? [], [definitionsQ.data]);

  // Group by the taxonomy node each definition attaches to, deepest last —
  // that is the order they resolve in, so the list reads the way the
  // resolution does.
  const byPath = useMemo(() => {
    const map = new Map<string, CropAttributeDefinition[]>();
    for (const d of definitions) {
      map.set(d.path, [...(map.get(d.path) ?? []), d]);
    }
    return [...map.entries()].sort(
      (a, b) => a[0].split(".").length - b[0].split(".").length || a[0].localeCompare(b[0]),
    );
  }, [definitions]);

  const submit = (): void => {
    if (!editing) return;
    const { options, ...rest } = editing.draft;
    const payload = {
      ...rest,
      options: options.length ? options.map((o, i) => ({ ...o, sort_order: i })) : null,
    };
    if (editing.id) {
      // code + attachment are immutable server-side; the PATCH schema forbids
      // extra keys, so sending them back is a 422 rather than a no-op.
      const updatable = { ...payload };
      delete (updatable as { code?: string }).code;
      delete (updatable as { crop_variety_id?: string | null }).crop_variety_id;
      delete (updatable as { crop_variety_strain_id?: string | null }).crop_variety_strain_id;
      update.mutate(
        { definitionId: editing.id, payload: updatable },
        { onSuccess: () => setEditing(null) },
      );
    } else {
      create.mutate(payload, { onSuccess: () => setEditing(null) });
    }
  };

  return (
    <Page>
      <PageHeader
        title={t("cropAttrs.title", { crop: crop?.name_en ?? "" })}
        subtitle={t("cropAttrs.subtitle")}
        actions={
          <LinkButton to="/platform/crops" variant="secondary">
            {t("cropAttrs.backToCatalog")}
          </LinkButton>
        }
      />

      <Toolbar
        chips={
          <FilterChip active={includeInactive} onToggle={() => setIncludeInactive((v) => !v)}>
            {t("cropAttrs.showRetired")}
          </FilterChip>
        }
        right={
          canManage && !editing ? (
            <Button
              type="button"
              onClick={() => {
                setVarietyForStrains(null);
                setEditing({ id: null, draft: emptyDraft() });
              }}
            >
              {t("cropAttrs.add")}
            </Button>
          ) : null
        }
      />

      {editing ? (
        <Card>
          <h3 className="border-b border-ap-line px-4 py-3 text-sm font-bold text-ap-ink">
            {editing.id ? t("cropAttrs.editHeading") : t("cropAttrs.addHeading")}
          </h3>
          <CropAttributeEditor
            draft={editing.draft}
            onChange={(draft) => setEditing((e) => (e ? { ...e, draft } : e))}
            isEdit={editing.id != null}
            siblings={definitions}
            varieties={varieties.data ?? []}
            strains={strains.data ?? []}
            onVarietyChange={setVarietyForStrains}
            saving={saving}
            error={saveError}
            onSubmit={submit}
            onCancel={() => setEditing(null)}
          />
        </Card>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <AsyncBoundary state={queryState(definitionsQ)} isEmpty={() => false} empty={null}>
          {() => (
            <Card>
              <h3 className="border-b border-ap-line px-4 py-3 text-sm font-bold text-ap-ink">
                {t("cropAttrs.definitions")}
              </h3>
              {definitions.length === 0 ? (
                <EmptyState message={t("cropAttrs.empty")} />
              ) : (
                <div className="flex flex-col">
                  {byPath.map(([path, rows]) => (
                    <section key={path} className="border-b border-ap-line last:border-b-0">
                      <div className="bg-ap-bg/50 px-4 py-1.5 text-xs font-semibold text-ap-muted">
                        {path}
                      </div>
                      <ul>
                        {rows.map((definition) => (
                          <li
                            key={definition.id}
                            className="flex flex-wrap items-center gap-2 px-4 py-2.5"
                          >
                            <span className="font-medium text-ap-ink">{definition.name_en}</span>
                            <code className="text-xs text-ap-muted">{definition.code}</code>
                            <Pill>{t(`cropAttrs.type.${definition.value_type}`)}</Pill>
                            {definition.show_when ? (
                              <Pill kind="info">
                                {t("cropAttrs.gatedOn", { code: definition.show_when.code })}
                              </Pill>
                            ) : null}
                            {definition.is_required ? (
                              <Pill kind="warn">{t("cropAttrs.required")}</Pill>
                            ) : null}
                            {!definition.is_active ? (
                              <Pill kind="neutral">{t("cropAttrs.retired")}</Pill>
                            ) : null}
                            {canManage ? (
                              <span className="ms-auto flex gap-2">
                                <Button
                                  variant="secondary"
                                  type="button"
                                  onClick={() => {
                                    setVarietyForStrains(definition.crop_variety_id);
                                    setEditing({ id: definition.id, draft: draftFrom(definition) });
                                  }}
                                >
                                  {t("cropAttrs.edit")}
                                </Button>
                                <Button
                                  variant="secondary"
                                  type="button"
                                  onClick={() =>
                                    update.mutate({
                                      definitionId: definition.id,
                                      payload: { is_active: !definition.is_active },
                                    })
                                  }
                                >
                                  {definition.is_active
                                    ? t("cropAttrs.retire")
                                    : t("cropAttrs.restore")}
                                </Button>
                              </span>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    </section>
                  ))}
                </div>
              )}
            </Card>
          )}
        </AsyncBoundary>

        <FormPreview definitions={definitions.filter((d) => d.is_active)} />
      </div>
    </Page>
  );
}

/**
 * The assignment form these definitions produce, live.
 *
 * Real form state, real gate evaluation, the same widget component the Farm
 * Console renders — so "does my show_when actually fire?" is answered by
 * trying it here rather than by saving and going to look at a block.
 */
function FormPreview({ definitions }: { definitions: CropAttributeDefinition[] }): ReactNode {
  const { t, i18n } = useTranslation("admin");
  const [values, setValues] = useState<AttributeValues>({});
  const groups = groupDefinitions(definitions.filter((d) => isVisible(d, values)));

  return (
    <Card>
      <h3 className="border-b border-ap-line px-4 py-3 text-sm font-bold text-ap-ink">
        {t("cropAttrs.preview")}
      </h3>
      {definitions.length === 0 ? (
        <EmptyState message={t("cropAttrs.previewEmpty")} />
      ) : (
        <div className="flex flex-col gap-5 p-4">
          <p className="text-xs text-ap-muted">{t("cropAttrs.previewHint")}</p>
          {groups.map((group) => (
            <section key={group.code || "__ungrouped__"} className="flex flex-col gap-3">
              {group.code ? (
                <h4 className="text-xs font-bold uppercase tracking-wide text-ap-muted">
                  {group.nameEn ?? group.code}
                </h4>
              ) : null}
              {group.defs.map((definition) => (
                <Field
                  key={definition.id}
                  label={label(definition, i18n.language)}
                  required={isRequired(definition, values)}
                  help={
                    definition.unit_en || definition.unit_ar
                      ? (definition.unit_en ?? definition.unit_ar)
                      : undefined
                  }
                >
                  {(a11y) => (
                    <AttributeInput
                      def={definition}
                      value={values[definition.code]}
                      readOnly={false}
                      lang={i18n.language}
                      onChange={(v) => setValues((prev) => ({ ...prev, [definition.code]: v }))}
                      a11y={a11y}
                    />
                  )}
                </Field>
              ))}
            </section>
          ))}
        </div>
      )}
    </Card>
  );
}
