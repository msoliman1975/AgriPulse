/**
 * The finding catalogue admin screen.
 *
 * Two tables, one per source. Section 6.2: the fold resolves the platform
 * table first, then the tenant one, and a tenant row whose code exists on the
 * platform side is never read. That row is marked shadowed here — it is the
 * only place an author can find out, because nothing else on the product
 * shows a row that is silently ignored.
 *
 * The catalogue owns the code, the clause and the default status. The tree
 * owns which findings it registers and at what severity, so severity is not
 * on this screen.
 */

import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { Field } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { StatusBanner } from "@/components/StatusBanner";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import { Tooltip } from "@/components/Tooltip";
import { queryState, resolveErrorMessage } from "@/components/asyncState";
import { localizedField } from "@/lib/localizedField";
import { useCapability } from "@/rbac/useCapability";
import {
  useCreateFinding,
  useDeactivateFinding,
  useFindingCatalogue,
  useUpdateFinding,
} from "@/queries/decisionTreesBeta";
import type { Finding, FindingSource, FindingWritePayload } from "@/api/decisionTreesBeta";

import { useAuthoringScope } from "../../lib/authoringScope";
import { FINDING_STATUSES, type FindingStatus } from "../lib/betaConstants";
import { useFindingStatusLabel } from "../lib/useStatusLabel";

const INPUT_CLASS = "w-full rounded-lg border border-ap-line px-2.5 py-1.5 text-sm text-ap-ink";

interface EditorState {
  source: FindingSource;
  /** Null for a new row. */
  existing: Finding | null;
}

export function FindingCataloguePage(): ReactNode {
  const { t, i18n } = useTranslation("decisionTreesBeta");
  const scope = useAuthoringScope();
  const canManage = useCapability("decision_tree.manage");
  const query = useFindingCatalogue(scope);
  const create = useCreateFinding();
  const update = useUpdateFinding();
  const deactivate = useDeactivateFinding();

  const [search, setSearch] = useState("");
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const state = queryState(query);

  return (
    <Page>
      <PageHeader
        title={t("catalogue.title")}
        badge={<Pill kind="info">{t("beta.badge")}</Pill>}
        subtitle={t("catalogue.subtitle")}
        actions={
          canManage ? (
            <Button
              onClick={() =>
                setEditor({
                  // A platform admin writes platform rows; a tenant admin
                  // writes their own. Neither can write the other's, and the
                  // API refuses it either way.
                  source: scope === "platform" ? "platform" : "tenant",
                  existing: null,
                })
              }
            >
              {scope === "platform" ? t("catalogue.addPlatform") : t("catalogue.addTenant")}
            </Button>
          ) : null
        }
      />

      {actionError ? <StatusBanner kind="crit">{actionError}</StatusBanner> : null}

      <input
        type="search"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder={t("catalogue.search")}
        aria-label={t("catalogue.search")}
        className="max-w-sm rounded-lg border border-ap-line px-2.5 py-1.5 text-sm"
      />

      <AsyncBoundary
        state={state}
        skeleton="lines"
        skeletonLines={4}
        errorMessage={t("catalogue.loadFailed")}
        filtered={search.trim() !== ""}
        empty={<EmptyState message={t("catalogue.empty")} />}
        noResults={<EmptyState message={t("catalogue.noMatch")} />}
      >
        {(findings) => {
          const shown = filterFindings(findings, search, i18n.language);
          return (
            <div className="flex flex-col gap-4">
              <CatalogueSection
                source="platform"
                rows={shown.filter((f) => f.source === "platform")}
                editable={canManage && scope === "platform"}
                onEdit={(f) => setEditor({ source: "platform", existing: f })}
                onDeactivate={(f) => {
                  if (!window.confirm(t("catalogue.deactivateConfirm", { code: f.code }))) return;
                  setActionError(null);
                  deactivate.mutate(
                    { source: "platform", code: f.code },
                    {
                      onError: (err) =>
                        setActionError(resolveErrorMessage(err, t("catalogue.form.saveFailed"))),
                    },
                  );
                }}
              />
              <CatalogueSection
                source="tenant"
                rows={shown.filter((f) => f.source === "tenant")}
                editable={canManage && scope === "tenant"}
                onEdit={(f) => setEditor({ source: "tenant", existing: f })}
                onDeactivate={(f) => {
                  if (!window.confirm(t("catalogue.deactivateConfirm", { code: f.code }))) return;
                  setActionError(null);
                  deactivate.mutate(
                    { source: "tenant", code: f.code },
                    {
                      onError: (err) =>
                        setActionError(resolveErrorMessage(err, t("catalogue.form.saveFailed"))),
                    },
                  );
                }}
              />
            </div>
          );
        }}
      </AsyncBoundary>

      {editor ? (
        <FindingForm
          source={editor.source}
          existing={editor.existing}
          takenCodes={(query.data ?? [])
            .filter((f) => f.source === editor.source)
            .map((f) => f.code)}
          saving={create.isPending || update.isPending}
          onCancel={() => setEditor(null)}
          onSave={(code, payload) => {
            setActionError(null);
            const onError = (err: unknown): void =>
              setActionError(resolveErrorMessage(err, t("catalogue.form.saveFailed")));
            if (editor.existing) {
              update.mutate(
                { source: editor.source, code, payload },
                { onSuccess: () => setEditor(null), onError },
              );
            } else {
              create.mutate(
                { source: editor.source, code, payload },
                { onSuccess: () => setEditor(null), onError },
              );
            }
          }}
        />
      ) : null}
    </Page>
  );
}

function filterFindings(findings: readonly Finding[], search: string, lang: string): Finding[] {
  const q = search.trim().toLowerCase();
  if (q === "") return [...findings];
  return findings.filter(
    (f) =>
      f.code.toLowerCase().includes(q) ||
      f.name_en.toLowerCase().includes(q) ||
      f.name_ar.includes(search.trim()) ||
      (localizedField(lang, f.clause_en, f.clause_ar) ?? "").toLowerCase().includes(q),
  );
}

function CatalogueSection({
  source,
  rows,
  editable,
  onEdit,
  onDeactivate,
}: {
  source: FindingSource;
  rows: readonly Finding[];
  editable: boolean;
  onEdit: (f: Finding) => void;
  onDeactivate: (f: Finding) => void;
}): ReactNode {
  const { t, i18n } = useTranslation("decisionTreesBeta");
  const statusLabel = useFindingStatusLabel();
  return (
    <Card title={t(`catalogue.${source}Section`)} bodyClassName="flex flex-col gap-2">
      <p className="text-meta text-ap-muted">{t(`catalogue.${source}Help`)}</p>
      {rows.length === 0 ? (
        <p className="text-sm text-ap-muted">{t("catalogue.empty")}</p>
      ) : (
        <Table>
          <caption className="sr-only">{t(`catalogue.${source}Section`)}</caption>
          <Thead>
            <Tr className="border-b border-ap-line text-meta uppercase text-ap-muted">
              <Th className="px-2 py-2 text-start">{t("catalogue.columns.code")}</Th>
              <Th className="px-2 py-2 text-start">{t("catalogue.columns.name")}</Th>
              <Th className="px-2 py-2 text-start">{t("catalogue.columns.clause")}</Th>
              <Th className="px-2 py-2 text-start">{t("catalogue.columns.status")}</Th>
              <Th className="px-2 py-2" />
            </Tr>
          </Thead>
          <Tbody>
            {rows.map((f) => (
              <Tr key={`${f.source}:${f.code}`} className="align-top">
                <Td className="px-2 py-2">
                  <span dir="ltr" className="font-mono text-xs font-semibold">
                    {f.code}
                  </span>
                </Td>
                <Td className="px-2 py-2">
                  <span className="flex flex-wrap items-center gap-1.5">
                    {localizedField(i18n.language, f.name_en, f.name_ar)}
                    {f.shadowed ? (
                      // The one thing this screen exists to say.
                      <Tooltip content={t("catalogue.shadowedHelp")}>
                        <Pill kind="warn">{t("catalogue.shadowed")}</Pill>
                      </Tooltip>
                    ) : null}
                    {!f.is_active ? <Pill kind="neutral">{t("catalogue.inactive")}</Pill> : null}
                  </span>
                </Td>
                <Td className="px-2 py-2 text-ap-muted">
                  {localizedField(i18n.language, f.clause_en, f.clause_ar)}
                </Td>
                <Td className="px-2 py-2">{statusLabel(f.default_status)}</Td>
                <Td className="px-2 py-2 text-end">
                  {editable ? (
                    <span className="flex justify-end gap-2">
                      <Button
                        variant="secondary"
                        size="sm"
                        aria-label={t("catalogue.edit", { code: f.code })}
                        onClick={() => onEdit(f)}
                      >
                        {t("catalogue.editAction")}
                      </Button>
                      <Button
                        variant="secondary"
                        size="sm"
                        aria-label={t("catalogue.deactivate", { code: f.code })}
                        onClick={() => onDeactivate(f)}
                      >
                        {t("catalogue.deactivateAction")}
                      </Button>
                    </span>
                  ) : null}
                </Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      )}
    </Card>
  );
}

// ---- The form ---------------------------------------------------------

/** Same expression as `FINDING_CODE_PATTERN` and the CHECK in both migrations. */
const CODE_PATTERN = /^[a-z][a-z0-9_]*$/;

/** Backend field limits, from `_FindingFields` in `recommendations/schemas.py`. */
const CLAUSE_MAX = 200;
const NAME_MAX = 80;

/**
 * The ASCII comma and the Arabic one (U+060C).
 *
 * A clause is one fragment the fold joins to others with commas. A clause
 * carrying its own comma makes the composed sentence unreadable, and the fold
 * cannot tell one kind of comma from the other. Both migrations CHECK this.
 */
const CLAUSE_COMMAS = [",", "،"];

type Translate = (key: string, options?: Record<string, unknown>) => string;

function clauseError(value: string, t: Translate): string | null {
  if (value.trim() === "") return t("catalogue.form.required");
  if (value.length > CLAUSE_MAX) return t("catalogue.form.tooLong", { max: CLAUSE_MAX });
  if (CLAUSE_COMMAS.some((comma) => value.includes(comma))) {
    return t("catalogue.form.clauseNoComma");
  }
  return null;
}

function nameError(value: string, t: Translate): string | null {
  if (value.trim() === "") return t("catalogue.form.required");
  if (value.length > NAME_MAX) return t("catalogue.form.tooLong", { max: NAME_MAX });
  return null;
}

function FindingForm({
  source,
  existing,
  takenCodes,
  saving,
  onCancel,
  onSave,
}: {
  source: FindingSource;
  existing: Finding | null;
  takenCodes: readonly string[];
  saving: boolean;
  onCancel: () => void;
  onSave: (code: string, payload: FindingWritePayload) => void;
}): ReactNode {
  const { t } = useTranslation("decisionTreesBeta");
  const statusLabel = useFindingStatusLabel();
  const [code, setCode] = useState(existing?.code ?? "");
  const [nameEn, setNameEn] = useState(existing?.name_en ?? "");
  const [nameAr, setNameAr] = useState(existing?.name_ar ?? "");
  const [clauseEn, setClauseEn] = useState(existing?.clause_en ?? "");
  const [clauseAr, setClauseAr] = useState(existing?.clause_ar ?? "");
  const [descriptionEn, setDescriptionEn] = useState(existing?.description_en ?? "");
  const [descriptionAr, setDescriptionAr] = useState(existing?.description_ar ?? "");
  const [status, setStatus] = useState<FindingStatus>(existing?.default_status ?? "issue");

  const codeError = useMemo(() => {
    if (existing) return null;
    if (code.trim() === "") return t("catalogue.form.required");
    if (!CODE_PATTERN.test(code)) return t("catalogue.form.badCode");
    if (takenCodes.includes(code)) return t("catalogue.form.duplicate");
    return null;
  }, [code, existing, takenCodes, t]);

  // The rules the backend CHECKs and the Pydantic validator enforces. Told
  // here, at the field, rather than as a 422 naming a constraint.
  const clauseEnError = useMemo(() => clauseError(clauseEn, t), [clauseEn, t]);
  const clauseArError = useMemo(() => clauseError(clauseAr, t), [clauseAr, t]);
  const nameEnError = useMemo(() => nameError(nameEn, t), [nameEn, t]);
  const nameArError = useMemo(() => nameError(nameAr, t), [nameAr, t]);

  const invalid =
    Boolean(codeError) ||
    Boolean(clauseEnError) ||
    Boolean(clauseArError) ||
    Boolean(nameEnError) ||
    Boolean(nameArError) ||
    saving;

  return (
    <Modal open onClose={onCancel} labelledBy="beta-finding-form-title" className="max-w-2xl">
      <div className="flex flex-col gap-4 p-4">
        <h2 id="beta-finding-form-title" className="text-card-title font-semibold text-ap-ink">
          {existing ? t("catalogue.form.editTitle") : t("catalogue.form.createTitle")}
          {" · "}
          {t(`findingPicker.${source}`)}
        </h2>

        <Field
          label={t("catalogue.form.code")}
          help={t("catalogue.form.codeHelp")}
          error={codeError}
          required
        >
          {(props) => (
            <input
              {...props}
              dir="ltr"
              disabled={Boolean(existing)}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              className={INPUT_CLASS}
            />
          )}
        </Field>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field
            label={t("catalogue.form.nameEn")}
            help={t("catalogue.form.nameHelp")}
            error={nameEnError}
            required
          >
            {(props) => (
              <input
                {...props}
                dir="ltr"
                value={nameEn}
                onChange={(e) => setNameEn(e.target.value)}
                className={INPUT_CLASS}
              />
            )}
          </Field>
          <Field label={t("catalogue.form.nameAr")} error={nameArError} required>
            {(props) => (
              <input
                {...props}
                dir="rtl"
                value={nameAr}
                onChange={(e) => setNameAr(e.target.value)}
                className={INPUT_CLASS}
              />
            )}
          </Field>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field
            label={t("catalogue.form.clauseEn")}
            help={t("catalogue.form.clauseHelp")}
            error={clauseEnError}
            required
          >
            {(props) => (
              <input
                {...props}
                dir="ltr"
                value={clauseEn}
                onChange={(e) => setClauseEn(e.target.value)}
                className={INPUT_CLASS}
              />
            )}
          </Field>
          <Field label={t("catalogue.form.clauseAr")} error={clauseArError} required>
            {(props) => (
              <input
                {...props}
                dir="rtl"
                value={clauseAr}
                onChange={(e) => setClauseAr(e.target.value)}
                className={INPUT_CLASS}
              />
            )}
          </Field>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("catalogue.form.descriptionEn")}>
            {(props) => (
              <textarea
                {...props}
                dir="ltr"
                rows={2}
                value={descriptionEn}
                onChange={(e) => setDescriptionEn(e.target.value)}
                className={INPUT_CLASS}
              />
            )}
          </Field>
          <Field label={t("catalogue.form.descriptionAr")}>
            {(props) => (
              <textarea
                {...props}
                dir="rtl"
                rows={2}
                value={descriptionAr}
                onChange={(e) => setDescriptionAr(e.target.value)}
                className={INPUT_CLASS}
              />
            )}
          </Field>
        </div>

        <Field
          label={t("catalogue.form.defaultStatus")}
          help={t("catalogue.form.defaultStatusHelp")}
        >
          {(props) => (
            <select
              {...props}
              value={status}
              onChange={(e) => setStatus(e.target.value as FindingStatus)}
              className={INPUT_CLASS}
            >
              {FINDING_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {statusLabel(s)}
                </option>
              ))}
            </select>
          )}
        </Field>

        <div className="flex gap-2">
          <Button
            disabled={invalid}
            onClick={() =>
              onSave(existing?.code ?? code.trim(), {
                name_en: nameEn.trim(),
                name_ar: nameAr.trim(),
                clause_en: clauseEn.trim(),
                clause_ar: clauseAr.trim(),
                description_en: descriptionEn.trim() || null,
                description_ar: descriptionAr.trim() || null,
                default_status: status,
              })
            }
          >
            {t("catalogue.form.save")}
          </Button>
          <Button variant="secondary" onClick={onCancel}>
            {t("catalogue.form.cancel")}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
