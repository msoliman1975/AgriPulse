// The inputs catalogue (decision D20): manures, biologicals, treatments,
// foliar nutrients, traps and bags, with their recommended doses and organic
// status. Mounted twice:
//
//   /platform/inputs   platform curators edit the platform catalogue
//   /settings/inputs   a tenant sees the platform rows plus its own, and its
//                      admins add and edit only their own
//
// The API enforces the same split. There is no delete: an input is retired,
// so a plan that used it still says what it used.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
  DOSE_UNITS,
  INPUT_CATEGORIES,
  INPUT_METHODS,
  ORGANIC_STATUSES,
  createInput,
  formatDose,
  listInputs,
  replaceInputDoses,
  updateInput,
  type DoseUnit,
  type Input,
  type InputCategory,
  type InputDose,
  type InputMethod,
  type OrganicStatus,
} from "@/api/inputs";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { DataTable } from "@/components/DataTable";
import { FIELD_CONTROL_CLASS, Field } from "@/components/Field";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill, type PillKind } from "@/components/Pill";
import { StatusBanner } from "@/components/StatusBanner";
import { queryState } from "@/components/asyncState";
import { useCapability } from "@/rbac/useCapability";
import { SourcesMarker } from "@/modules/sources/SourcesMarker";

const KEY = ["inputs"] as const;

const ORGANIC_PILL: Record<OrganicStatus, PillKind> = {
  permitted: "ok",
  restricted: "warn",
  not_permitted: "crit",
  unverified: "neutral",
};

export function InputsCataloguePage({ scope }: { scope: "platform" | "tenant" }): ReactNode {
  const { t, i18n } = useTranslation("inputs");
  const canWrite = useCapability(
    scope === "platform" ? "platform.manage_crops" : "tenant.manage_settings",
  );
  const ar = i18n.language.startsWith("ar");
  const [q, setQ] = useState("");
  const [category, setCategory] = useState<InputCategory | "">("");
  const [cropPath, setCropPath] = useState("");
  const [includeInactive, setIncludeInactive] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const inputs = useQuery({
    queryKey: [...KEY, q, category, cropPath, includeInactive] as const,
    queryFn: () => listInputs({ q, category, cropPath, includeInactive }),
  });
  const chosen = (inputs.data ?? []).find((i) => i.id === selected) ?? null;
  const owns = (i: Input): boolean => canWrite && i.scope === scope;

  const body = (
    <>
      <div className="flex flex-wrap items-end gap-3">
        <Field label={t("search")} className="min-w-[14rem] flex-1">
          {(p) => (
            <input
              {...p}
              type="search"
              className={FIELD_CONTROL_CLASS}
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          )}
        </Field>
        <Field label={t("category")}>
          {(p) => (
            <select
              {...p}
              className={FIELD_CONTROL_CLASS}
              value={category}
              onChange={(e) => setCategory(e.target.value as InputCategory | "")}
            >
              <option value="">{t("allCategories")}</option>
              {INPUT_CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {t(`categories.${c}`)}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label={t("cropPath")}>
          {(p) => (
            <input
              {...p}
              className={FIELD_CONTROL_CLASS}
              placeholder="date_palm.medjool"
              value={cropPath}
              onChange={(e) => setCropPath(e.target.value.trim())}
            />
          )}
        </Field>
        <label className="flex items-center gap-2 text-xs text-ap-ink">
          <input
            type="checkbox"
            checked={includeInactive}
            onChange={(e) => setIncludeInactive(e.target.checked)}
          />
          {t("includeRetired")}
        </label>
      </div>

      <StatusBanner kind="info">{t("organicNotice")}</StatusBanner>

      {creating ? <InputForm input={null} scope={scope} onDone={() => setCreating(false)} /> : null}
      {chosen ? (
        <InputDetail input={chosen} canEdit={owns(chosen)} onClose={() => setSelected(null)} />
      ) : null}

      <DataTable<Input>
        columns={[
          {
            key: "name",
            header: t("colName"),
            cell: (i) => (
              <div className="flex flex-col gap-0.5">
                <span className="text-sm text-ap-ink">
                  {ar ? (i.name_ar ?? i.name_en) : i.name_en}
                </span>
                {i.active_ingredient ? (
                  <span className="text-[11px] text-ap-muted">{i.active_ingredient}</span>
                ) : null}
              </div>
            ),
          },
          {
            key: "category",
            header: t("category"),
            className: "text-xs",
            cell: (i) => t(`categories.${i.category}`),
          },
          {
            key: "methods",
            header: t("colMethods"),
            className: "text-xs text-ap-muted",
            cell: (i) => i.methods.map((m) => t(`methods.${m}`)).join(", ") || "—",
          },
          {
            key: "doses",
            header: t("colDoses"),
            className: "text-xs",
            cell: (i) => (i.doses.length ? i.doses.map(formatDose).join("; ") : "—"),
          },
          {
            key: "organic",
            header: t("colOrganic"),
            cell: (i) => (
              <Pill kind={ORGANIC_PILL[i.organic_status]}>{t(`organic.${i.organic_status}`)}</Pill>
            ),
          },
          {
            key: "scope",
            header: t("colScope"),
            className: "text-xs",
            cell: (i) =>
              !i.is_active ? (
                <Pill kind="warn">{t("retired")}</Pill>
              ) : (
                t(i.scope === "platform" ? "scopePlatform" : "scopeTenant")
              ),
          },
        ]}
        rowKey={(i) => i.id}
        onRowClick={(i) => setSelected(i.id)}
        state={queryState(inputs)}
        caption={t("caption")}
        errorMessage={t("loadFailed")}
        empty={t("empty")}
      />
    </>
  );

  const action = canWrite ? (
    <Button onClick={() => setCreating(true)}>{t("new")}</Button>
  ) : undefined;
  if (scope === "tenant") {
    // Settings renders its child routes inside its own <Page>.
    return (
      <section className="flex flex-col gap-4">
        <PageHeader title={t("title")} subtitle={t("subtitleTenant")} actions={action} />
        {body}
      </section>
    );
  }
  return (
    <Page>
      <PageHeader title={t("title")} subtitle={t("subtitlePlatform")} actions={action} />
      {body}
    </Page>
  );
}

function InputDetail({
  input,
  canEdit,
  onClose,
}: {
  input: Input;
  canEdit: boolean;
  onClose: () => void;
}): ReactNode {
  const { t } = useTranslation("inputs");
  const [editing, setEditing] = useState(false);
  if (editing)
    return <InputForm input={input} scope={input.scope} onDone={() => setEditing(false)} />;
  return (
    <Card
      title={input.name_en}
      footer={
        <div className="flex gap-2">
          {canEdit ? (
            <Button variant="secondary" size="sm" onClick={() => setEditing(true)}>
              {t("edit")}
            </Button>
          ) : null}
          <Button variant="ghost" size="sm" onClick={onClose}>
            {t("close")}
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-2 text-sm">
        {input.name_ar ? (
          <p dir="rtl" lang="ar">
            {input.name_ar}
          </p>
        ) : null}
        <p className="text-xs text-ap-muted">
          <code className="font-mono">{input.code}</code> · {t(`categories.${input.category}`)}
          {input.crop_paths.length ? ` · ${input.crop_paths.join(", ")}` : ` · ${t("allCrops")}`}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <Pill kind={ORGANIC_PILL[input.organic_status]}>
            {t(`organic.${input.organic_status}`)}
          </Pill>
          {input.organic_list ? (
            <span className="text-[11px] text-ap-muted">{input.organic_list}</span>
          ) : null}
          <SourcesMarker entityType="input" entityKey={input.code} />
        </div>
        {input.phi_days != null || input.rei_hours != null ? (
          <p className="text-xs text-ap-muted">
            {input.phi_days != null ? t("phi", { days: input.phi_days }) : ""}{" "}
            {input.rei_hours != null ? t("rei", { hours: input.rei_hours }) : ""}
          </p>
        ) : null}
        <h3 className="text-xs font-medium text-ap-ink">{t("doses")}</h3>
        {input.doses.length === 0 ? (
          <p className="text-xs text-ap-muted">{t("noDoses")}</p>
        ) : (
          <ul className="flex flex-col gap-1 text-xs">
            {input.doses.map((d, k) => (
              <li key={k}>
                <span className="font-medium">{formatDose(d)}</span>
                {d.crop_path ? <span className="text-ap-muted"> · {d.crop_path}</span> : null}
                {d.context ? <span className="text-ap-muted"> · {d.context}</span> : null}
                {d.reference ? <span className="text-ap-muted"> · {d.reference}</span> : null}
              </li>
            ))}
          </ul>
        )}
        {input.notes ? <p className="text-xs text-ap-muted">{input.notes}</p> : null}
      </div>
    </Card>
  );
}

const EMPTY_DOSE: InputDose = {
  crop_path: null,
  value: null,
  value_min: null,
  value_max: null,
  unit: "kg/plant",
  unit_note: null,
  context: null,
  reference: null,
};

function InputForm({
  input,
  scope,
  onDone,
}: {
  input: Input | null;
  scope: "platform" | "tenant";
  onDone: () => void;
}): ReactNode {
  const { t } = useTranslation("inputs");
  const client = useQueryClient();
  const [code, setCode] = useState(input?.code ?? "");
  const [nameEn, setNameEn] = useState(input?.name_en ?? "");
  const [nameAr, setNameAr] = useState(input?.name_ar ?? "");
  const [category, setCategory] = useState<InputCategory>(input?.category ?? "organic_fertiliser");
  const [ai, setAi] = useState(input?.active_ingredient ?? "");
  const [methods, setMethods] = useState<InputMethod[]>(input?.methods ?? []);
  const [organic, setOrganic] = useState<OrganicStatus>(input?.organic_status ?? "unverified");
  const [organicList, setOrganicList] = useState(input?.organic_list ?? "");
  const [cropPaths, setCropPaths] = useState((input?.crop_paths ?? []).join(", "));
  const [notes, setNotes] = useState(input?.notes ?? "");
  const [active, setActive] = useState(input?.is_active ?? true);
  const [doses, setDoses] = useState<InputDose[]>(input?.doses ?? []);

  const save = useMutation({
    mutationFn: async () => {
      const fields = {
        name_en: nameEn.trim(),
        name_ar: nameAr.trim() || null,
        category,
        active_ingredient: ai.trim() || null,
        methods,
        organic_status: organic,
        organic_list: organicList.trim() || null,
        crop_paths: cropPaths
          .split(",")
          .map((p) => p.trim())
          .filter(Boolean),
        notes: notes.trim() || null,
      };
      const saved = input
        ? await updateInput(input.id, { ...fields, is_active: active })
        : await createInput({ ...fields, code: code.trim() });
      return replaceInputDoses(saved.id, doses);
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: KEY });
      onDone();
    },
  });

  const toNum = (s: string): number | null => (s.trim() === "" ? null : Number(s));
  const setDose = (k: number, patch: Partial<InputDose>): void =>
    setDoses((all) => all.map((d, i) => (i === k ? { ...d, ...patch } : d)));

  return (
    <Card title={input ? t("editTitle") : t(scope === "platform" ? "newPlatform" : "newTenant")}>
      <form
        className="grid gap-3 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        {!input ? (
          <Field label={t("code")} required help={t("codeHelp")}>
            {(p) => (
              <input
                {...p}
                required
                pattern="[a-z0-9_]+"
                className={FIELD_CONTROL_CLASS}
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
            )}
          </Field>
        ) : null}
        <Field label={t("nameEn")} required>
          {(p) => (
            <input
              {...p}
              required
              className={FIELD_CONTROL_CLASS}
              value={nameEn}
              onChange={(e) => setNameEn(e.target.value)}
            />
          )}
        </Field>
        <Field label={t("nameAr")}>
          {(p) => (
            <input
              {...p}
              dir="rtl"
              className={FIELD_CONTROL_CLASS}
              value={nameAr}
              onChange={(e) => setNameAr(e.target.value)}
            />
          )}
        </Field>
        <Field label={t("category")}>
          {(p) => (
            <select
              {...p}
              className={FIELD_CONTROL_CLASS}
              value={category}
              onChange={(e) => setCategory(e.target.value as InputCategory)}
            >
              {INPUT_CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {t(`categories.${c}`)}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label={t("activeIngredient")}>
          {(p) => (
            <input
              {...p}
              className={FIELD_CONTROL_CLASS}
              value={ai}
              onChange={(e) => setAi(e.target.value)}
            />
          )}
        </Field>
        <Field label={t("organicStatus")}>
          {(p) => (
            <select
              {...p}
              className={FIELD_CONTROL_CLASS}
              value={organic}
              onChange={(e) => setOrganic(e.target.value as OrganicStatus)}
            >
              {ORGANIC_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {t(`organic.${s}`)}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label={t("organicList")}>
          {(p) => (
            <input
              {...p}
              className={FIELD_CONTROL_CLASS}
              value={organicList}
              onChange={(e) => setOrganicList(e.target.value)}
            />
          )}
        </Field>
        <Field label={t("cropPaths")} help={t("cropPathsHelp")}>
          {(p) => (
            <input
              {...p}
              className={FIELD_CONTROL_CLASS}
              value={cropPaths}
              onChange={(e) => setCropPaths(e.target.value)}
            />
          )}
        </Field>
        <fieldset className="sm:col-span-2">
          <legend className="text-xs font-medium text-ap-ink">{t("colMethods")}</legend>
          <div className="mt-1 flex flex-wrap gap-3">
            {INPUT_METHODS.map((m) => (
              <label key={m} className="flex items-center gap-1 text-xs">
                <input
                  type="checkbox"
                  checked={methods.includes(m)}
                  onChange={(e) =>
                    setMethods((all) =>
                      e.target.checked ? [...all, m] : all.filter((x) => x !== m),
                    )
                  }
                />
                {t(`methods.${m}`)}
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset className="flex flex-col gap-2 sm:col-span-2">
          <legend className="text-xs font-medium text-ap-ink">{t("doses")}</legend>
          {doses.map((d, k) => (
            <div
              key={k}
              className="flex flex-wrap items-end gap-2 rounded-md border border-ap-line p-2"
            >
              {(["value", "value_min", "value_max"] as const).map((f) => (
                <label key={f} className="flex flex-col gap-1 text-[11px] text-ap-muted">
                  {t(`dose.${f}`)}
                  <input
                    inputMode="decimal"
                    className={`${FIELD_CONTROL_CLASS} w-20`}
                    value={d[f] == null ? "" : String(d[f])}
                    onChange={(e) => setDose(k, { [f]: toNum(e.target.value) })}
                  />
                </label>
              ))}
              <label className="flex flex-col gap-1 text-[11px] text-ap-muted">
                {t("dose.unit")}
                <select
                  className={FIELD_CONTROL_CLASS}
                  value={d.unit}
                  onChange={(e) => setDose(k, { unit: e.target.value as DoseUnit })}
                >
                  {DOSE_UNITS.map((u) => (
                    <option key={u} value={u}>
                      {u}
                    </option>
                  ))}
                </select>
              </label>
              {d.unit === "other" ? (
                <label className="flex flex-col gap-1 text-[11px] text-ap-muted">
                  {t("dose.unitNote")}
                  <input
                    className={FIELD_CONTROL_CLASS}
                    value={d.unit_note ?? ""}
                    onChange={(e) => setDose(k, { unit_note: e.target.value || null })}
                  />
                </label>
              ) : null}
              <label className="flex min-w-[10rem] flex-1 flex-col gap-1 text-[11px] text-ap-muted">
                {t("dose.context")}
                <input
                  className={FIELD_CONTROL_CLASS}
                  value={d.context ?? ""}
                  onChange={(e) => setDose(k, { context: e.target.value || null })}
                />
              </label>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setDoses((all) => all.filter((_, i) => i !== k))}
              >
                {t("dose.remove")}
              </Button>
            </div>
          ))}
          <Button
            type="button"
            variant="secondary"
            size="sm"
            className="self-start"
            onClick={() => setDoses((all) => [...all, EMPTY_DOSE])}
          >
            {t("dose.add")}
          </Button>
        </fieldset>
        <Field label={t("notes")} className="sm:col-span-2">
          {(p) => (
            <textarea
              {...p}
              rows={2}
              className={FIELD_CONTROL_CLASS}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          )}
        </Field>
        {input ? (
          <label className="flex items-center gap-2 text-xs">
            <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
            {t("active")}
          </label>
        ) : null}
        {save.isError ? (
          <StatusBanner kind="crit" className="sm:col-span-2">
            {t("saveFailed")}
          </StatusBanner>
        ) : null}
        <div className="flex gap-2 sm:col-span-2">
          <Button
            type="submit"
            disabled={save.isPending || !nameEn.trim() || (!input && !code.trim())}
          >
            {t("save")}
          </Button>
          <Button type="button" variant="ghost" onClick={onDone}>
            {t("cancel")}
          </Button>
        </div>
      </form>
    </Card>
  );
}
