import { formatDistanceToNow, parseISO } from "date-fns";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import type { DecisionTreeVersion, DryRunResponse } from "@/api/decisionTrees";
import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { useDateLocale } from "@/hooks/useDateLocale";
import { useCapability } from "@/rbac/useCapability";
import {
  useAppendDecisionTreeVersion,
  useDecisionTree,
  useDryRunDecisionTree,
  usePublishDecisionTreeVersion,
} from "@/queries/decisionTrees";

export function DecisionTreeEditorPage(): ReactNode {
  const { code = "" } = useParams<{ code: string }>();
  const { t } = useTranslation("decisionTrees");
  const dateLocale = useDateLocale();
  const canManage = useCapability("decision_tree.manage");

  const detail = useDecisionTree(code);
  const append = useAppendDecisionTreeVersion();
  const publish = usePublishDecisionTreeVersion();
  const dryRun = useDryRunDecisionTree();

  // Editor buffer — initialised from the latest version once data loads.
  const [yamlBuffer, setYamlBuffer] = useState<string | null>(null);
  const [notes, setNotes] = useState("");
  const [dryRunBlockId, setDryRunBlockId] = useState("");
  const [dryRunMode, setDryRunMode] = useState<"editor" | "current">("editor");
  const [dryRunResult, setDryRunResult] = useState<DryRunResponse | null>(null);

  const versions = detail.data?.versions ?? [];
  const latestVersion: DecisionTreeVersion | undefined = versions[0];
  const currentVersionNumber = detail.data?.current_version ?? null;

  // Hydrate the buffer from the latest version on first load. We track
  // the version id we hydrated from so re-renders don't blow away
  // unsaved edits.
  const [hydratedFromId, setHydratedFromId] = useState<string | null>(null);
  useEffect(() => {
    if (yamlBuffer === null && latestVersion) {
      setYamlBuffer(latestVersion.tree_yaml);
      setHydratedFromId(latestVersion.id);
    }
  }, [yamlBuffer, latestVersion]);

  const dirty = useMemo(() => {
    if (!latestVersion || yamlBuffer === null) return false;
    return yamlBuffer !== latestVersion.tree_yaml;
  }, [latestVersion, yamlBuffer]);

  if (detail.isError) {
    return <p className="p-4 text-sm text-ap-crit">{t("edit.loadFailed")}</p>;
  }
  if (detail.isLoading || !detail.data) {
    return (
      <div className="mx-auto flex max-w-5xl flex-col gap-4 p-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  const tree = detail.data;

  const onSave = (): void => {
    if (!yamlBuffer) return;
    append.mutate(
      { code: tree.code, payload: { tree_yaml: yamlBuffer, notes: notes || null } },
      {
        onSuccess: (next) => {
          // Re-hydrate from the new latest so dirty resets.
          const newest = next.versions[0];
          if (newest) {
            setYamlBuffer(newest.tree_yaml);
            setHydratedFromId(newest.id);
          }
          setNotes("");
        },
      },
    );
  };

  const onPublish = (version: number): void => {
    publish.mutate({ code: tree.code, version });
  };

  const onLoadIntoEditor = (v: DecisionTreeVersion): void => {
    setYamlBuffer(v.tree_yaml);
    setHydratedFromId(v.id);
  };

  const onDryRun = (): void => {
    if (!dryRunBlockId.trim()) return;
    setDryRunResult(null);
    const payload =
      dryRunMode === "editor"
        ? { block_id: dryRunBlockId.trim(), tree_yaml: yamlBuffer ?? "" }
        : { block_id: dryRunBlockId.trim(), version: currentVersionNumber ?? undefined };
    dryRun.mutate({ code: tree.code, payload }, { onSuccess: (res) => setDryRunResult(res) });
  };

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4">
      <header>
        <h1 className="text-2xl font-semibold text-ap-ink">
          {tree.name_en} <span className="font-mono text-base text-ap-muted">{tree.code}</span>
        </h1>
        {tree.description_en ? (
          <p className="mt-1 text-sm text-ap-muted">{tree.description_en}</p>
        ) : null}
      </header>

      <section className="rounded-xl border border-ap-line bg-ap-panel p-4 text-sm">
        <h2 className="mb-2 text-sm font-semibold text-ap-ink">{t("edit.metadata.heading")}</h2>
        <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
          <Row label={t("edit.metadata.code")} value={<code>{tree.code}</code>} />
          <Row label={t("edit.metadata.name")} value={tree.name_en} />
          <Row label={t("edit.metadata.description")} value={tree.description_en ?? "—"} />
          <Row
            label={t("edit.metadata.crop")}
            value={tree.crop_id ? tree.crop_id.slice(0, 8) + "…" : "any"}
          />
          <Row
            label={t("edit.metadata.currentVersion")}
            value={
              currentVersionNumber != null
                ? `v${currentVersionNumber}`
                : t("edit.metadata.draftOnly")
            }
          />
        </dl>
      </section>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <section className="rounded-xl border border-ap-line bg-ap-panel lg:col-span-2">
          <header className="flex items-center justify-between border-b border-ap-line px-4 py-3">
            <div>
              <h2 className="text-sm font-semibold text-ap-ink">{t("edit.yaml.heading")}</h2>
              <p className="text-xs text-ap-muted">{t("edit.yaml.subtitle")}</p>
            </div>
            <div className="flex items-center gap-2">
              {hydratedFromId && hydratedFromId !== latestVersion?.id ? (
                <span className="text-[11px] text-ap-warn">loaded from older version</span>
              ) : null}
            </div>
          </header>
          <div className="p-4">
            <textarea
              value={yamlBuffer ?? ""}
              onChange={(e) => setYamlBuffer(e.target.value)}
              rows={28}
              spellCheck={false}
              className="w-full rounded-md border border-ap-line bg-ap-bg/40 px-3 py-2 font-mono text-xs text-ap-ink shadow-inner focus:border-ap-primary focus:outline-none focus:ring-1 focus:ring-ap-primary"
            />
            {canManage ? (
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <input
                  type="text"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="notes (optional)"
                  className="flex-1 rounded-md border border-ap-line bg-white px-2 py-1 text-xs shadow-sm focus:border-ap-primary focus:outline-none focus:ring-1 focus:ring-ap-primary"
                />
                {append.isError ? (
                  <span className="text-xs text-ap-crit">
                    {append.error?.message ?? t("edit.yaml.saveFailed")}
                  </span>
                ) : !dirty ? (
                  <span className="text-xs text-ap-muted">{t("edit.yaml.noChange")}</span>
                ) : null}
                <button
                  type="button"
                  onClick={onSave}
                  disabled={!dirty || append.isPending || !yamlBuffer}
                  className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
                >
                  {append.isPending ? t("edit.yaml.saving") : t("edit.yaml.save")}
                </button>
              </div>
            ) : null}
          </div>
        </section>

        <section className="rounded-xl border border-ap-line bg-ap-panel">
          <header className="flex items-center justify-between border-b border-ap-line px-4 py-3">
            <h2 className="text-sm font-semibold text-ap-ink">{t("edit.versions.heading")}</h2>
            <span className="text-xs text-ap-muted">{versions.length}</span>
          </header>
          <ul className="divide-y divide-ap-line">
            {versions.map((v) => {
              const isCurrent =
                v.id === tree.versions.find((x) => x.version === currentVersionNumber)?.id;
              return (
                <li key={v.id} className="flex flex-col gap-1 px-4 py-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-ap-ink">v{v.version}</span>
                    {isCurrent ? (
                      <Pill kind="ok">{t("edit.versions.currentBadge")}</Pill>
                    ) : v.published_at ? (
                      <Pill kind="info">published</Pill>
                    ) : (
                      <Pill kind="neutral">{t("edit.versions.draftBadge")}</Pill>
                    )}
                    {v.notes ? (
                      <span className="text-[11px] italic text-ap-muted">{v.notes}</span>
                    ) : null}
                  </div>
                  <div className="text-[11px] text-ap-muted">
                    {v.published_at
                      ? t("edit.versions.publishedAt", {
                          when: formatDistanceToNow(parseISO(v.published_at), {
                            addSuffix: true,
                            locale: dateLocale,
                          }),
                        })
                      : t("edit.versions.createdAt", {
                          when: formatDistanceToNow(parseISO(v.created_at), {
                            addSuffix: true,
                            locale: dateLocale,
                          }),
                        })}
                  </div>
                  <div className="mt-1 flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => onLoadIntoEditor(v)}
                      className="rounded-md border border-ap-line bg-ap-panel px-2 py-0.5 text-[11px] font-medium text-ap-ink hover:bg-ap-line/40"
                    >
                      {t("edit.versions.load")}
                    </button>
                    {canManage && !isCurrent ? (
                      <button
                        type="button"
                        onClick={() => onPublish(v.version)}
                        disabled={publish.isPending}
                        className="rounded-md bg-ap-primary px-2 py-0.5 text-[11px] font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
                      >
                        {publish.isPending
                          ? t("edit.versions.publishing")
                          : t("edit.versions.publish")}
                      </button>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ul>
          {publish.isError ? (
            <p className="border-t border-ap-line p-3 text-xs text-ap-crit">
              {publish.error?.message ?? t("edit.versions.publishFailed")}
            </p>
          ) : null}
        </section>
      </div>

      <section className="rounded-xl border border-ap-line bg-ap-panel">
        <header className="border-b border-ap-line px-4 py-3">
          <h2 className="text-sm font-semibold text-ap-ink">{t("edit.dryRun.heading")}</h2>
          <p className="text-xs text-ap-muted">{t("edit.dryRun.subtitle")}</p>
        </header>
        <div className="flex flex-col gap-3 p-4 text-sm">
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-1 flex-col gap-1">
              <span className="text-xs font-medium text-ap-muted">{t("edit.dryRun.blockId")}</span>
              <input
                value={dryRunBlockId}
                onChange={(e) => setDryRunBlockId(e.target.value)}
                placeholder={t("edit.dryRun.blockIdPlaceholder")}
                className="w-full rounded-md border border-ap-line bg-white px-2 py-1 font-mono text-xs shadow-sm focus:border-ap-primary focus:outline-none focus:ring-1 focus:ring-ap-primary"
              />
            </label>
            <fieldset className="flex flex-col gap-1 text-xs">
              <legend className="font-medium text-ap-muted">mode</legend>
              <label className="flex items-center gap-1">
                <input
                  type="radio"
                  name="mode"
                  value="editor"
                  checked={dryRunMode === "editor"}
                  onChange={() => setDryRunMode("editor")}
                />
                {t("edit.dryRun.useEditor")}
              </label>
              <label className="flex items-center gap-1">
                <input
                  type="radio"
                  name="mode"
                  value="current"
                  disabled={currentVersionNumber == null}
                  checked={dryRunMode === "current"}
                  onChange={() => setDryRunMode("current")}
                />
                {t("edit.dryRun.useCurrent")}
              </label>
            </fieldset>
            <button
              type="button"
              onClick={onDryRun}
              disabled={dryRun.isPending || !dryRunBlockId.trim()}
              className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
            >
              {dryRun.isPending ? t("edit.dryRun.running") : t("edit.dryRun.run")}
            </button>
          </div>

          {dryRunResult ? (
            <DryRunResult result={dryRunResult} />
          ) : dryRun.isError ? (
            <p className="text-xs text-ap-crit">{dryRun.error?.message}</p>
          ) : null}
        </div>
      </section>
    </div>
  );
}

function DryRunResult({ result }: { result: DryRunResponse }): ReactNode {
  const { t } = useTranslation("decisionTrees");
  return (
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
      <div className="rounded-md border border-ap-line bg-ap-bg/40 p-3 text-sm">
        <div className="mb-2 flex items-center gap-2">
          <span className="text-xs font-semibold text-ap-muted">{t("edit.dryRun.outcome")}</span>
          {result.matched ? (
            <Pill kind="ok">{t("edit.dryRun.matched")}</Pill>
          ) : (
            <Pill kind="neutral">no_action</Pill>
          )}
        </div>
        {result.outcome ? (
          <pre className="overflow-x-auto whitespace-pre-wrap font-mono text-[11px] text-ap-ink">
            {JSON.stringify(result.outcome, null, 2)}
          </pre>
        ) : (
          <p className="text-xs text-ap-muted">{t("edit.dryRun.noMatch")}</p>
        )}
        {result.error ? (
          <p className="mt-2 text-xs text-ap-crit">
            {t("edit.dryRun.error")}: {result.error}
          </p>
        ) : null}
      </div>

      <div className="rounded-md border border-ap-line bg-ap-bg/40 p-3 text-sm">
        <div className="mb-2 text-xs font-semibold text-ap-muted">{t("edit.dryRun.path")}</div>
        <ol className="flex flex-col gap-1 text-[11px]">
          {result.path.map((s, i) => (
            <li key={`${s.node_id}-${i}`} className="flex items-center gap-1.5">
              <span className="text-ap-muted">{i + 1}.</span>
              <span className="font-mono text-ap-ink">{s.node_id}</span>
              {s.matched === true ? (
                <Pill kind="ok">match</Pill>
              ) : s.matched === false ? (
                <Pill kind="neutral">no match</Pill>
              ) : (
                <Pill kind="info">leaf</Pill>
              )}
            </li>
          ))}
        </ol>
        {Object.keys(result.evaluation_snapshot).length > 0 ? (
          <details className="mt-2">
            <summary className="cursor-pointer text-[11px] font-medium text-ap-primary">
              {t("edit.dryRun.snapshot")}
            </summary>
            <pre className="mt-1 overflow-x-auto whitespace-pre-wrap font-mono text-[10px] text-ap-ink">
              {JSON.stringify(result.evaluation_snapshot, null, 2)}
            </pre>
          </details>
        ) : null}
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: ReactNode }): ReactNode {
  return (
    <div className="flex items-center justify-between gap-2">
      <dt className="text-ap-muted">{label}</dt>
      <dd className="text-ap-ink">{value}</dd>
    </div>
  );
}
