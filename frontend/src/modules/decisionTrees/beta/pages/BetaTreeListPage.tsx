/**
 * The beta designer's index.
 *
 * The same `<Page>` / `<PageHeader>` / `<DataTable state>` pattern as
 * `DecisionTreeListPage`, so the two surfaces read as one product. It is a
 * separate list on purpose: a beta tree folds findings and an existing tree
 * ends at an outcome leaf, and mixing them in one table would put two engines
 * behind one row.
 */

import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/Button";
import { DataTable } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { Field } from "@/components/Field";
import { LinkButton } from "@/components/LinkButton";
import { Modal } from "@/components/Modal";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { StatusBanner } from "@/components/StatusBanner";
import { mapAsyncState, queryState, resolveErrorMessage } from "@/components/asyncState";
import { localizedField } from "@/lib/localizedField";
import { useCapability } from "@/rbac/useCapability";
import { useBetaTrees, useCreateBetaTree } from "@/queries/decisionTreesBeta";
import type { BetaTreeSummary } from "@/api/decisionTreesBeta";

import { useAuthoringScope } from "../../lib/authoringScope";
import { parseBetaDoc, STARTER_BETA_YAML } from "../lib/betaTree";
import { betaBasePath, betaTreePath, findingCataloguePath } from "../lib/betaRoutes";

const INPUT_CLASS = "w-full rounded-lg border border-ap-line px-2.5 py-1.5 text-sm text-ap-ink";

/** Lower snake case, the same expression the catalogue and both migrations
 *  use. The code reaches a URL and a JSONB key, so it is not free text. */
const CODE_PATTERN = /^[a-z][a-z0-9_]*$/;

export function BetaTreeListPage(): ReactNode {
  const { t, i18n } = useTranslation("decisionTreesBeta");
  const scope = useAuthoringScope();
  const navigate = useNavigate();
  const base = betaBasePath(scope);
  const query = useBetaTrees();
  const create = useCreateBetaTree();
  const canManage = useCapability("decision_tree.manage");

  const [creating, setCreating] = useState(false);
  const [code, setCode] = useState("");
  const [nameEn, setNameEn] = useState("");
  const [nameAr, setNameAr] = useState("");
  const [treeScope, setTreeScope] = useState<"block" | "cell">("cell");
  const [createError, setCreateError] = useState<string | null>(null);

  const taken = new Set((query.data ?? []).map((row) => row.code));
  const trimmedCode = code.trim();
  const codeError =
    trimmedCode === ""
      ? null
      : !CODE_PATTERN.test(trimmedCode)
        ? t("list.create.badCode")
        : taken.has(trimmedCode)
          ? t("list.create.duplicate")
          : null;
  const cannotCreate =
    trimmedCode === "" || nameEn.trim() === "" || Boolean(codeError) || create.isPending;

  /**
   * A new tree starts from the starter body, not from an empty one.
   *
   * An empty definition has no root, so the canvas would open on nothing and
   * the first thing the author would read is a publish check about a tree
   * they have not written yet. The starter is the smallest publishable shape:
   * one condition, one register, one stop that both routes reach.
   */
  const onCreate = (): void => {
    const starter = parseBetaDoc(
      STARTER_BETA_YAML.replace("code: REPLACE_ME", "code: " + trimmedCode),
    );
    if (!starter) return;
    // The name and the scope travel inside the definition, not beside it.
    // `BetaTreeCreateRequest` forbids extra fields, and the tree row is
    // stamped from the compiled body: `name_en=compiled["name_en"]` and
    // `scope=compiled.get("scope")`. Sending them at the top level is a 422.
    const definition = {
      ...starter,
      name_en: nameEn.trim(),
      name_ar: nameAr.trim() || null,
      scope: treeScope,
    };
    setCreateError(null);
    create.mutate(
      {
        code: trimmedCode,
        definition,
      },
      {
        onSuccess: (tree) => {
          setCreating(false);
          navigate(betaTreePath(scope, tree.code));
        },
        onError: (err) => setCreateError(resolveErrorMessage(err, t("list.create.failed"))),
      },
    );
  };

  // Never cast a query result: `mapAsyncState` carries loading and error
  // through and only touches the success payload.
  const rows = mapAsyncState(queryState(query), (list): readonly BetaTreeSummary[] => list);

  return (
    <Page>
      <PageHeader
        title={t("list.title")}
        badge={<Pill kind="info">{t("beta.badge")}</Pill>}
        subtitle={t("list.subtitle")}
        actions={
          <>
            <LinkButton to={findingCataloguePath(scope)} variant="secondary">
              {t("list.openCatalogue")}
            </LinkButton>
            {canManage ? (
              <Button onClick={() => setCreating(true)}>{t("list.create.open")}</Button>
            ) : null}
          </>
        }
      />
      <p className="text-sm text-ap-muted">{t("beta.note")}</p>
      <DataTable<BetaTreeSummary>
        state={rows}
        rowKey={(row) => row.code}
        rowHref={(row) => `${base}/${row.code}`}
        errorMessage={t("list.loadFailed")}
        empty={<EmptyState message={t("list.empty")} />}
        caption={t("list.title")}
        columns={[
          {
            key: "name",
            header: t("list.columns.name"),
            cell: (row) => localizedField(i18n.language, row.name_en, row.name_ar) ?? row.code,
          },
          {
            key: "code",
            header: t("list.columns.code"),
            cell: (row) => (
              <span dir="ltr" className="font-mono text-xs">
                {row.code}
              </span>
            ),
          },
          {
            key: "scope",
            header: t("list.columns.scope"),
            cell: (row) => t(`list.scope.${row.scope}`),
          },
          {
            key: "version",
            header: t("list.columns.version"),
            cell: (row) => row.current_version ?? "—",
          },
          {
            key: "published",
            header: t("list.columns.published"),
            cell: (row) =>
              row.published_version !== null ? (
                <Pill kind="ok">{row.published_version}</Pill>
              ) : (
                <Pill kind="neutral">{t("list.notPublished")}</Pill>
              ),
          },
        ]}
      />

      {creating ? (
        <Modal
          open
          onClose={() => setCreating(false)}
          labelledBy="beta-create-tree-title"
          className="max-w-lg"
        >
          <div className="flex flex-col gap-4 p-4">
            <h2 id="beta-create-tree-title" className="text-card-title font-semibold text-ap-ink">
              {t("list.create.title")}
            </h2>
            {createError ? <StatusBanner kind="crit">{createError}</StatusBanner> : null}

            <Field label={t("list.create.code")} help={t("list.create.codeHelp")} error={codeError}>
              {(props) => (
                <input
                  {...props}
                  dir="ltr"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  className={INPUT_CLASS + " font-mono"}
                />
              )}
            </Field>

            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t("list.create.nameEn")}>
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
              <Field label={t("list.create.nameAr")}>
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

            <Field label={t("list.create.scope")} help={t("list.create.scopeHelp")}>
              {(props) => (
                <select
                  {...props}
                  value={treeScope}
                  onChange={(e) => setTreeScope(e.target.value as "block" | "cell")}
                  className={INPUT_CLASS}
                >
                  <option value="cell">{t("list.scope.cell")}</option>
                  <option value="block">{t("list.scope.block")}</option>
                </select>
              )}
            </Field>

            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setCreating(false)}>
                {t("designer.cancel")}
              </Button>
              <Button onClick={onCreate} disabled={cannotCreate}>
                {create.isPending ? t("list.create.saving") : t("list.create.save")}
              </Button>
            </div>
          </div>
        </Modal>
      ) : null}
    </Page>
  );
}
