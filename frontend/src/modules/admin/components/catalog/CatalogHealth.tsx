// The catalogue's Health tab: the block health values one crop path sets
// (public migration 0095, `public.crop_health_definitions`).
//
// A path sets only the values that differ from the level above it. Every
// other value shows what the path inherits and from where — the platform
// default or a shallower path — so "where does 72 hours come from" is
// answered on the screen. Saving with nothing set removes the row.

import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { isApiError } from "@/api/errors";
import { CROP_HEALTH_KEYS, type CropPathHealth, type HealthBody } from "@/api/healthDefinitions";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Button } from "@/components/Button";
import { FIELD_CONTROL_CLASS } from "@/components/Field";
import { Pill } from "@/components/Pill";
import { StatusBanner } from "@/components/StatusBanner";
import { queryState } from "@/components/asyncState";
import { HealthDefinitionEditor } from "@/modules/health/components/HealthDefinitionEditor";
import { useCropPathHealth, useSaveCropPathHealth } from "@/queries/healthDefinitions";

export function HealthPanel({
  cropPath,
  canManage,
}: {
  cropPath: string;
  canManage: boolean;
}): ReactNode {
  const { t } = useTranslation("admin");
  const query = useCropPathHealth(cropPath);
  return (
    <AsyncBoundary
      state={queryState(query)}
      errorMessage={t("healthDefinition.loadFailed")}
      empty={null}
    >
      {(data) => <Body data={data} canManage={canManage} />}
    </AsyncBoundary>
  );
}

function Body({ data, canManage }: { data: CropPathHealth; canManage: boolean }): ReactNode {
  const { t } = useTranslation("admin");
  const save = useSaveCropPathHealth(data.crop_path);
  const stored: HealthBody = data.own?.definition ?? {};
  const [draft, setDraft] = useState<HealthBody>(stored);
  const [notes, setNotes] = useState(data.own?.notes ?? "");
  const [result, setResult] = useState<{ kind: "info" | "crit"; text: string } | null>(null);

  useEffect(() => {
    setDraft(data.own?.definition ?? {});
    setNotes(data.own?.notes ?? "");
  }, [data]);

  const count = Object.keys(draft).length;
  const dirty =
    JSON.stringify(draft) !== JSON.stringify(stored) || notes !== (data.own?.notes ?? "");

  const onSave = (): void => {
    setResult(null);
    save.mutate(
      { definition: draft, notes: notes.trim() === "" ? null : notes },
      {
        onSuccess: (saved) =>
          setResult({
            kind: "info",
            text: saved.own ? t("healthDefinition.saved") : t("healthDefinition.crop.removed"),
          }),
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
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-ap-ink">{t("healthDefinition.crop.title")}</h3>
        {data.own ? (
          <Pill kind="neutral">{t("healthDefinition.version", { version: data.own.version })}</Pill>
        ) : null}
      </div>
      <p className="text-xs text-ap-muted">{t("healthDefinition.crop.intro")}</p>

      <HealthDefinitionEditor
        keys={CROP_HEALTH_KEYS}
        values={draft}
        inherited={data.inherited}
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

      <div className="flex flex-wrap items-center gap-2">
        {canManage ? (
          <>
            <Button onClick={onSave} disabled={!dirty || save.isPending}>
              {save.isPending ? t("healthDefinition.saving") : t("healthDefinition.save")}
            </Button>
            <Button
              variant="secondary"
              onClick={() => {
                setDraft({});
                setResult(null);
              }}
              disabled={count === 0 || save.isPending}
            >
              {t("healthDefinition.crop.clearAll")}
            </Button>
          </>
        ) : null}
        <span className="text-xs text-ap-muted">
          {count === 0
            ? t("healthDefinition.crop.noOverrides")
            : t("healthDefinition.crop.overrideCount", { count })}
        </span>
      </div>
    </section>
  );
}
