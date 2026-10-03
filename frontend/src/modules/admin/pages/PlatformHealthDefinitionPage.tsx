// /platform/health-definition — the platform default of the block health
// rule (public migration 0095).
//
// Two writers on one page, because the platform default lives in two rows:
//
//   * `public.health_definition_platform` holds seven values, saved together;
//   * the cell rule is the platform default `health.cell_rollup` (and
//     `health.cell_share_pct`), the same key a tenant overrides in
//     Settings → Block health. It keeps its one writer, the defaults API.
//
// Order of the tiers, first to last: this page, the tenant, the crop path
// (Crop catalog → Health tab), the farm. A later tier replaces only the
// values it sets.

import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { isApiError } from "@/api/errors";
import { PLATFORM_HEALTH_KEYS, type HealthBody } from "@/api/healthDefinitions";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Button } from "@/components/Button";
import { FIELD_CONTROL_CLASS } from "@/components/Field";
import { Card } from "@/components/Card";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { StatusBanner } from "@/components/StatusBanner";
import { queryState } from "@/components/asyncState";
import { HealthDefinitionEditor } from "@/modules/health/components/HealthDefinitionEditor";
import {
  CELL_ROLLUP_KEY,
  CELL_SHARE_KEY,
  CellRollupCard,
} from "@/modules/settings/components/CellRollupCard";
import {
  usePlatformHealthDefinition,
  useSavePlatformHealthDefinition,
  useSavePlatformRollup,
} from "@/queries/healthDefinitions";
import type { PlatformHealthDefinition } from "@/api/healthDefinitions";
import { useCapability } from "@/rbac/useCapability";

export function PlatformHealthDefinitionPage(): ReactNode {
  const { t } = useTranslation("admin");
  const query = usePlatformHealthDefinition();
  const canManage = useCapability("platform.manage_defaults");

  return (
    <Page width="standard">
      <PageHeader
        title={t("healthDefinition.pageTitle")}
        subtitle={t("healthDefinition.pageSubtitle")}
        badge={!canManage ? <Pill kind="warn">{t("healthDefinition.readOnly")}</Pill> : undefined}
      />
      <StatusBanner kind="info">{t("healthDefinition.tiersNote")}</StatusBanner>
      <AsyncBoundary
        state={queryState(query)}
        errorMessage={t("healthDefinition.loadFailed")}
        empty={null}
      >
        {(data) => <Body data={data} canManage={canManage} />}
      </AsyncBoundary>
    </Page>
  );
}

function Body({
  data,
  canManage,
}: {
  data: PlatformHealthDefinition;
  canManage: boolean;
}): ReactNode {
  const { t, i18n } = useTranslation("admin");
  const save = useSavePlatformHealthDefinition();
  const saveRollup = useSavePlatformRollup();
  const [draft, setDraft] = useState<HealthBody>(data.definition);
  const [notes, setNotes] = useState(data.notes ?? "");
  const [result, setResult] = useState<{ kind: "info" | "crit"; text: string } | null>(null);

  // A save returns the stored row; take it as the new starting point.
  useEffect(() => {
    setDraft(data.definition);
    setNotes(data.notes ?? "");
  }, [data]);

  const dirty =
    JSON.stringify(draft) !== JSON.stringify(data.definition) || notes !== (data.notes ?? "");

  const onSave = (): void => {
    setResult(null);
    save.mutate(
      { definition: draft, notes: notes.trim() === "" ? null : notes },
      {
        onSuccess: () => setResult({ kind: "info", text: t("healthDefinition.saved") }),
        onError: (err) =>
          setResult({
            kind: "crit",
            text: isApiError(err)
              ? (err.problem.detail ?? err.message)
              : t("healthDefinition.saveFailed"),
          }),
      },
    );
  };

  return (
    <>
      <Card noPadding className="flex flex-col gap-3 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-semibold text-ap-ink">{t("healthDefinition.valuesTitle")}</h2>
          <Pill kind="neutral">{t("healthDefinition.version", { version: data.version })}</Pill>
          <span className="text-xs text-ap-muted">
            {t("healthDefinition.updatedAt", {
              when: new Date(data.updated_at).toLocaleString(i18n.language),
            })}
          </span>
        </div>

        <HealthDefinitionEditor
          keys={PLATFORM_HEALTH_KEYS}
          values={draft}
          onChange={(next) => {
            setDraft(next);
            setResult(null);
          }}
          disabled={!canManage || save.isPending}
        />

        <label className="flex flex-col gap-1 text-xs font-semibold text-ap-ink">
          {t("healthDefinition.notes")}
          <span className="font-normal text-ap-muted">{t("healthDefinition.notesHint")}</span>
          <textarea
            rows={3}
            maxLength={2000}
            disabled={!canManage || save.isPending}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className={`${FIELD_CONTROL_CLASS} font-normal`}
          />
        </label>

        {result ? <StatusBanner kind={result.kind}>{result.text}</StatusBanner> : null}

        {canManage ? (
          <div>
            <Button onClick={onSave} disabled={!dirty || save.isPending}>
              {save.isPending ? t("healthDefinition.saving") : t("healthDefinition.save")}
            </Button>
          </div>
        ) : null}
      </Card>

      <p className="text-xs text-ap-muted">{t("healthDefinition.rollupHelp")}</p>
      {canManage ? (
        <CellRollupCard
          rollup={{
            key: CELL_ROLLUP_KEY,
            value: data.rollup.cell_rollup,
            source: "platform",
            overridden_at: null,
          }}
          share={{
            key: CELL_SHARE_KEY,
            value: data.rollup.cell_share_pct,
            source: "platform",
            overridden_at: null,
          }}
          onSave={(key, value) => saveRollup.mutateAsync({ key, value })}
        />
      ) : null}
    </>
  );
}
