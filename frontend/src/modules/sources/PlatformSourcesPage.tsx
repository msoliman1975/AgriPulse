// /platform/sources — the sources library (decision D27).
//
// One row per publication, imported from the Medjool documents' reference
// lists and deduplicated, with each document's own "[n]" kept as an alias.
// Selecting a source shows how each document numbers it and what in the
// platform cites it ("used by"), each with its own confidence.
//
// Everyone signed in can read; editing and linking need platform.manage_crops.
// There is no delete: a wrong source is retired, so a link that cited it
// still says what it cited.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
  CONFIDENCES,
  SOURCE_KINDS,
  createSource,
  getSource,
  linkSource,
  listSourceDocuments,
  listSources,
  unlinkSource,
  updateSource,
  type Confidence,
  type Source,
  type SourceDetail,
  type SourceEntityType,
  type SourceFields,
  type SourceKind,
} from "@/api/sources";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { DataTable } from "@/components/DataTable";
import { FIELD_CONTROL_CLASS, Field } from "@/components/Field";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { StatusBanner } from "@/components/StatusBanner";
import { queryState } from "@/components/asyncState";
import { useCapability } from "@/rbac/useCapability";

import { CONFIDENCE_PILL, aliasLabel, documentLabel, sourceHref } from "./sourceLabels";

const ENTITY_TYPES: readonly SourceEntityType[] = [
  "finding",
  "decision_tree",
  "tree_parameter",
  "signal",
  "plan_template_activity",
  "reference_value",
  "input",
  "crop_attribute",
];

const KEY = ["sources"] as const;

export function PlatformSourcesPage(): ReactNode {
  const { t } = useTranslation("sources");
  const canManage = useCapability("platform.manage_crops");
  const [q, setQ] = useState("");
  const [doc, setDoc] = useState("");
  const [includeInactive, setIncludeInactive] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [editing, setEditing] = useState<SourceDetail | "new" | null>(null);

  const documents = useQuery({ queryKey: [...KEY, "documents"], queryFn: listSourceDocuments });
  const sources = useQuery({
    queryKey: [...KEY, "list", q, doc, includeInactive] as const,
    queryFn: () => listSources({ q, document: doc, includeInactive }),
  });

  return (
    <Page>
      <PageHeader
        title={t("title")}
        subtitle={t("subtitle")}
        actions={
          canManage ? <Button onClick={() => setEditing("new")}>{t("new")}</Button> : undefined
        }
      />

      <div className="flex flex-wrap items-end gap-3">
        <Field label={t("search")} className="min-w-[16rem] flex-1">
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
        <Field label={t("document")}>
          {(p) => (
            <select
              {...p}
              className={FIELD_CONTROL_CLASS}
              value={doc}
              onChange={(e) => setDoc(e.target.value)}
            >
              <option value="">{t("allDocuments")}</option>
              {(documents.data ?? []).map((d) => (
                <option key={d.document_code} value={d.document_code}>
                  {documentLabel(d.document_code)} ({d.entries})
                </option>
              ))}
            </select>
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

      {editing ? (
        <SourceForm
          source={editing === "new" ? null : editing}
          onDone={(saved) => {
            setEditing(null);
            if (saved) setSelected(saved.id);
          }}
        />
      ) : null}

      {selected ? (
        <SourcePanel
          id={selected}
          canManage={canManage}
          onEdit={(s) => setEditing(s)}
          onClose={() => setSelected(null)}
        />
      ) : null}

      <DataTable<Source>
        columns={[
          {
            key: "citation",
            header: t("colCitation"),
            cell: (s) => (
              <div className="flex flex-col gap-0.5">
                <span className="text-sm text-ap-ink">{s.citation}</span>
                {s.doi ? (
                  <code className="font-mono text-[11px] text-ap-muted">doi:{s.doi}</code>
                ) : null}
              </div>
            ),
          },
          { key: "year", header: t("colYear"), className: "text-xs", cell: (s) => s.year ?? "—" },
          {
            key: "kind",
            header: t("colKind"),
            className: "text-xs",
            cell: (s) => t(`kind.${s.kind}`),
          },
          {
            key: "aliases",
            header: t("colCitedAs"),
            className: "text-[11px] text-ap-muted",
            cell: (s) => aliasLabel(s.aliases) || "—",
          },
          {
            key: "used",
            header: t("colUsedBy"),
            className: "text-xs",
            cell: (s) => (s.is_active ? s.link_count : <Pill kind="warn">{t("retired")}</Pill>),
          },
        ]}
        rowKey={(s) => s.id}
        onRowClick={(s) => setSelected(s.id)}
        state={queryState(sources)}
        caption={t("tableCaption")}
        errorMessage={t("loadFailed")}
        empty={t("empty")}
      />
    </Page>
  );
}

function SourcePanel({
  id,
  canManage,
  onEdit,
  onClose,
}: {
  id: string;
  canManage: boolean;
  onEdit: (s: SourceDetail) => void;
  onClose: () => void;
}): ReactNode {
  const { t } = useTranslation("sources");
  const client = useQueryClient();
  const detail = useQuery({
    queryKey: [...KEY, "detail", id] as const,
    queryFn: () => getSource(id),
  });
  const refresh = () => void client.invalidateQueries({ queryKey: KEY });
  const unlink = useMutation({ mutationFn: unlinkSource, onSuccess: refresh });

  if (detail.isLoading) return <p className="text-sm text-ap-muted">{t("loading")}</p>;
  if (detail.isError || !detail.data) {
    return <StatusBanner kind="crit">{t("loadFailed")}</StatusBanner>;
  }
  const s = detail.data;
  const href = sourceHref(s);

  return (
    <Card
      title={t("detailTitle")}
      footer={
        <div className="flex gap-2">
          {canManage ? (
            <Button variant="secondary" size="sm" onClick={() => onEdit(s)}>
              {t("edit")}
            </Button>
          ) : null}
          <Button variant="ghost" size="sm" onClick={onClose}>
            {t("close")}
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-3 text-sm">
        <p className="text-ap-ink">{s.citation}</p>
        {href ? (
          <a
            className="break-all text-xs text-ap-accent underline"
            href={href}
            target="_blank"
            rel="noreferrer"
          >
            {href}
          </a>
        ) : null}
        <p className="text-xs text-ap-muted">
          {t(`kind.${s.kind}`)}
          {s.year ? ` · ${s.year}` : ""}
          {s.is_active ? "" : ` · ${t("retired")}`}
        </p>
        {s.notes ? <p className="text-xs text-ap-muted">{s.notes}</p> : null}

        <div>
          <h3 className="text-xs font-medium text-ap-ink">{t("citedAs")}</h3>
          <ul className="text-xs text-ap-muted">
            {s.aliases.map((a) => (
              <li key={`${a.document_code}-${a.ref_number}`}>
                {documentLabel(a.document_code)} [{a.ref_number}]
              </li>
            ))}
            {s.aliases.length === 0 ? <li>—</li> : null}
          </ul>
        </div>

        <div>
          <h3 className="text-xs font-medium text-ap-ink">
            {t("usedBy", { count: s.links.length })}
          </h3>
          {s.links.length === 0 ? (
            <p className="text-xs text-ap-muted">{t("notUsed")}</p>
          ) : (
            <ul className="divide-y divide-ap-line rounded-md border border-ap-line">
              {s.links.map((l) => (
                <li key={l.id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-xs">
                  <Pill kind={CONFIDENCE_PILL[l.confidence] ?? "neutral"}>
                    {t(`confidence.${l.confidence}`)}
                  </Pill>
                  <span className="text-ap-muted">{t(`entity.${l.entity_type}`)}</span>
                  <code className="font-mono text-[11px]">
                    {l.entity_key}
                    {l.detail ? ` · ${l.detail}` : ""}
                  </code>
                  {l.note ? <span className="text-ap-muted">{l.note}</span> : null}
                  {canManage ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="ms-auto"
                      disabled={unlink.isPending}
                      onClick={() => unlink.mutate(l.id)}
                    >
                      {t("unlink")}
                    </Button>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </div>

        {canManage ? <LinkForm sourceId={s.id} onLinked={refresh} /> : null}
      </div>
    </Card>
  );
}

function LinkForm({ sourceId, onLinked }: { sourceId: string; onLinked: () => void }): ReactNode {
  const { t } = useTranslation("sources");
  const [entityType, setEntityType] = useState<SourceEntityType>("finding");
  const [entityKey, setEntityKey] = useState("");
  const [detail, setDetail] = useState("");
  const [confidence, setConfidence] = useState<Confidence>("medium");
  const link = useMutation({
    mutationFn: () =>
      linkSource(sourceId, {
        entity_type: entityType,
        entity_key: entityKey.trim(),
        detail: detail.trim(),
        confidence,
      }),
    onSuccess: () => {
      setEntityKey("");
      setDetail("");
      onLinked();
    },
  });

  const submit = (e: FormEvent): void => {
    e.preventDefault();
    if (entityKey.trim()) link.mutate();
  };

  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-2" aria-label={t("linkTitle")}>
      <Field label={t("linkEntity")}>
        {(p) => (
          <select
            {...p}
            className={FIELD_CONTROL_CLASS}
            value={entityType}
            onChange={(e) => setEntityType(e.target.value as SourceEntityType)}
          >
            {ENTITY_TYPES.map((et) => (
              <option key={et} value={et}>
                {t(`entity.${et}`)}
              </option>
            ))}
          </select>
        )}
      </Field>
      <Field label={t("linkKey")}>
        {(p) => (
          <input
            {...p}
            className={FIELD_CONTROL_CLASS}
            value={entityKey}
            onChange={(e) => setEntityKey(e.target.value)}
          />
        )}
      </Field>
      <Field label={t("linkDetail")}>
        {(p) => (
          <input
            {...p}
            className={FIELD_CONTROL_CLASS}
            value={detail}
            onChange={(e) => setDetail(e.target.value)}
          />
        )}
      </Field>
      <Field label={t("linkConfidence")}>
        {(p) => (
          <select
            {...p}
            className={FIELD_CONTROL_CLASS}
            value={confidence}
            onChange={(e) => setConfidence(e.target.value as Confidence)}
          >
            {CONFIDENCES.map((c) => (
              <option key={c} value={c}>
                {t(`confidence.${c}`)}
              </option>
            ))}
          </select>
        )}
      </Field>
      <Button type="submit" size="sm" disabled={link.isPending || !entityKey.trim()}>
        {t("link")}
      </Button>
      {link.isError ? <StatusBanner kind="crit">{t("saveFailed")}</StatusBanner> : null}
    </form>
  );
}

function SourceForm({
  source,
  onDone,
}: {
  source: SourceDetail | null;
  onDone: (saved: SourceDetail | null) => void;
}): ReactNode {
  const { t } = useTranslation("sources");
  const client = useQueryClient();
  const [citation, setCitation] = useState(source?.citation ?? "");
  const [kind, setKind] = useState<SourceKind>(source?.kind ?? "article");
  const [year, setYear] = useState(source?.year ? String(source.year) : "");
  const [doi, setDoi] = useState(source?.doi ?? "");
  const [url, setUrl] = useState(source?.url ?? "");
  const [notes, setNotes] = useState(source?.notes ?? "");
  const [active, setActive] = useState(source?.is_active ?? true);

  const save = useMutation({
    mutationFn: () => {
      const fields: SourceFields = {
        citation: citation.trim(),
        kind,
        year: year ? Number(year) : null,
        doi: doi.trim() || null,
        url: url.trim() || null,
        notes: notes.trim() || null,
      };
      return source
        ? updateSource(source.id, { ...fields, is_active: active })
        : createSource({ ...fields, citation: citation.trim() });
    },
    onSuccess: (saved) => {
      void client.invalidateQueries({ queryKey: KEY });
      onDone(saved);
    },
  });

  return (
    <Card title={source ? t("editTitle") : t("newTitle")}>
      <form
        className="grid gap-3 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (citation.trim()) save.mutate();
        }}
      >
        <Field label={t("colCitation")} required className="sm:col-span-2">
          {(p) => (
            <textarea
              {...p}
              required
              rows={3}
              className={FIELD_CONTROL_CLASS}
              value={citation}
              onChange={(e) => setCitation(e.target.value)}
            />
          )}
        </Field>
        <Field label={t("colKind")}>
          {(p) => (
            <select
              {...p}
              className={FIELD_CONTROL_CLASS}
              value={kind}
              onChange={(e) => setKind(e.target.value as SourceKind)}
            >
              {SOURCE_KINDS.map((k) => (
                <option key={k} value={k}>
                  {t(`kind.${k}`)}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label={t("colYear")}>
          {(p) => (
            <input
              {...p}
              inputMode="numeric"
              className={FIELD_CONTROL_CLASS}
              value={year}
              onChange={(e) => setYear(e.target.value.replace(/\D/g, "").slice(0, 4))}
            />
          )}
        </Field>
        <Field label="DOI">
          {(p) => (
            <input
              {...p}
              className={FIELD_CONTROL_CLASS}
              value={doi}
              onChange={(e) => setDoi(e.target.value)}
            />
          )}
        </Field>
        <Field label="URL">
          {(p) => (
            <input
              {...p}
              type="url"
              className={FIELD_CONTROL_CLASS}
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
          )}
        </Field>
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
        {source ? (
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
          <Button type="submit" disabled={save.isPending || !citation.trim()}>
            {t("save")}
          </Button>
          <Button type="button" variant="ghost" onClick={() => onDone(null)}>
            {t("cancel")}
          </Button>
        </div>
      </form>
    </Card>
  );
}
