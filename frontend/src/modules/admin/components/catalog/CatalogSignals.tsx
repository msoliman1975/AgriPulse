// The catalogue's Signals tab (decision D21).
//
// Signals and scout forms carry a crop scope. Scoped to a path, they switch on
// by themselves for every block whose current crop is that path or sits below
// it, and the scout app offers them only there. Standing on a node, this tab
// answers "what does a scout on this crop record?": the rows scoped here, the
// rows inherited from a crop above, and (folded away) the ones every crop gets.
//
// Scope is edited here; the definitions themselves are authored on
// /platform/signals. Only a scope set on this exact path can be removed here:
// an inherited scope belongs to the crop above. Removing the last scope would
// silently widen a row to every crop, so that case is refused, not offered.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
  listPlatformSignalDefinitions,
  listPlatformSignalTemplates,
  updatePlatformSignalDefinition,
  updatePlatformSignalTemplate,
  type SignalDefinition,
  type SignalTemplate,
} from "@/api/signals";
import { Button } from "@/components/Button";
import { FIELD_CONTROL_CLASS } from "@/components/Field";
import { Pill } from "@/components/Pill";
import { StatusBanner } from "@/components/StatusBanner";
import {
  scopeAtPath,
  withPath,
  withoutPath,
  type ScopeAtPath,
} from "@/modules/admin/lib/signalScope";

type Row = Pick<
  SignalDefinition | SignalTemplate,
  "id" | "code" | "name" | "is_active" | "crop_paths"
>;
type Kind = "definition" | "template";

const DEFS_KEY = ["platform", "signals", "definitions"] as const;
const TPLS_KEY = ["platform", "signals", "templates"] as const;

export function SignalsPanel({
  cropPath,
  canManage,
}: {
  cropPath: string;
  canManage: boolean;
}): ReactNode {
  const { t } = useTranslation("admin");
  const client = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  // The whole platform catalogue, not the ?crop_path= filter: the picker needs
  // the rows that do NOT apply here too. Same keys as /platform/signals, so the
  // two screens share one cache.
  const definitions = useQuery({
    queryKey: DEFS_KEY,
    queryFn: () => listPlatformSignalDefinitions(true),
  });
  const templates = useQuery({
    queryKey: TPLS_KEY,
    queryFn: () => listPlatformSignalTemplates(true),
  });

  const scope = useMutation({
    mutationFn: ({ kind, row, next }: { kind: Kind; row: Row; next: string[] }) =>
      kind === "definition"
        ? updatePlatformSignalDefinition(row.id, { crop_paths: next })
        : updatePlatformSignalTemplate(row.id, { crop_paths: next }),
    onSuccess: (_data, { kind }) => {
      setError(null);
      void client.invalidateQueries({ queryKey: kind === "definition" ? DEFS_KEY : TPLS_KEY });
    },
    onError: () => setError(t("catalog.signals.saveFailed")),
  });

  if (definitions.isLoading || templates.isLoading) {
    return <p className="text-xs text-ap-muted">{t("crops.loading")}</p>;
  }
  if (definitions.isError || templates.isError) {
    return <StatusBanner kind="crit">{t("signals.loadFailed")}</StatusBanner>;
  }

  const edit = (kind: Kind, row: Row, next: string[]): void => scope.mutate({ kind, row, next });

  return (
    <section className="space-y-5">
      <p className="text-[11px] text-ap-muted">{t("catalog.signals.intro", { path: cropPath })}</p>
      {error ? <StatusBanner kind="crit">{error}</StatusBanner> : null}
      <ScopeGroup
        kind="definition"
        title={t("signals.definitions")}
        rows={definitions.data ?? []}
        cropPath={cropPath}
        canManage={canManage}
        busy={scope.isPending}
        onEdit={edit}
      />
      <ScopeGroup
        kind="template"
        title={t("signals.templates")}
        rows={templates.data ?? []}
        cropPath={cropPath}
        canManage={canManage}
        busy={scope.isPending}
        onEdit={edit}
      />
    </section>
  );
}

function ScopeGroup({
  kind,
  title,
  rows,
  cropPath,
  canManage,
  busy,
  onEdit,
}: {
  kind: Kind;
  title: string;
  rows: Row[];
  cropPath: string;
  canManage: boolean;
  busy: boolean;
  onEdit: (kind: Kind, row: Row, next: string[]) => void;
}): ReactNode {
  const { t } = useTranslation("admin");
  const [pick, setPick] = useState("");
  const by = (s: ScopeAtPath) =>
    rows
      .filter((r) => scopeAtPath(r.crop_paths, cropPath) === s)
      .sort((a, b) => a.code.localeCompare(b.code));
  const here = by("here");
  const inherited = by("inherited");
  const everyCrop = by("all");
  // Offer only rows already scoped elsewhere. Scoping an every-crop row here
  // would take it away from every other crop, which is not what "add" means.
  const addable = by("none").filter((r) => r.is_active);

  const add = (): void => {
    const row = addable.find((r) => r.id === pick);
    if (!row) return;
    onEdit(kind, row, withPath(row.crop_paths, cropPath));
    setPick("");
  };

  return (
    <div className="space-y-2">
      <h3 className="text-xs font-medium text-ap-ink">{title}</h3>
      <List
        rows={here}
        empty={t("catalog.signals.noneHere", { path: cropPath })}
        action={(row) => {
          if (!canManage) return null;
          const next = withoutPath(row.crop_paths, cropPath);
          if (next.length === 0) {
            return (
              <span className="text-[11px] text-ap-muted">{t("catalog.signals.lastScope")}</span>
            );
          }
          return (
            <Button
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => onEdit(kind, row, next)}
            >
              {t("catalog.signals.remove")}
            </Button>
          );
        }}
      />
      {inherited.length > 0 ? (
        <>
          <p className="text-[11px] text-ap-muted">{t("catalog.signals.inherited")}</p>
          <List
            rows={inherited}
            empty=""
            action={(row) => (
              <span className="font-mono text-[11px] text-ap-muted">
                {row.crop_paths.filter((p) => cropPath.startsWith(`${p}.`)).join(", ")}
              </span>
            )}
          />
        </>
      ) : null}
      {canManage && addable.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2">
          <select
            aria-label={t("catalog.signals.addLabel")}
            className={FIELD_CONTROL_CLASS}
            value={pick}
            onChange={(e) => setPick(e.target.value)}
          >
            <option value="">{t("catalog.signals.addPlaceholder")}</option>
            {addable.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name} ({r.code})
              </option>
            ))}
          </select>
          <Button size="sm" disabled={busy || pick === ""} onClick={add}>
            {t("catalog.signals.add")}
          </Button>
        </div>
      ) : null}
      {everyCrop.length > 0 ? (
        <details className="text-[11px] text-ap-muted">
          <summary className="cursor-pointer">
            {t("catalog.signals.everyCrop", { count: everyCrop.length })}
          </summary>
          <p className="mt-1">{everyCrop.map((r) => r.code).join(", ")}</p>
        </details>
      ) : null}
    </div>
  );
}

function List({
  rows,
  empty,
  action,
}: {
  rows: Row[];
  empty: string;
  action: (row: Row) => ReactNode;
}): ReactNode {
  const { t } = useTranslation("admin");
  if (rows.length === 0) {
    return (
      <p className="rounded-md border border-dashed border-ap-line px-3 py-3 text-center text-[11px] text-ap-muted">
        {empty}
      </p>
    );
  }
  return (
    <ul className="divide-y divide-ap-line rounded-md border border-ap-line">
      {rows.map((row) => (
        <li key={row.id} className="flex flex-wrap items-center gap-2 px-3 py-2">
          <span className="text-sm text-ap-ink">{row.name}</span>
          <code className="font-mono text-[11px] text-ap-muted">{row.code}</code>
          {!row.is_active ? <Pill kind="warn">{t("signals.retired")}</Pill> : null}
          <span className="ms-auto">{action(row)}</span>
        </li>
      ))}
    </ul>
  );
}
