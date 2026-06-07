import { isAxiosError } from "axios";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { isApiError } from "@/api/errors";
import type { SignalReference, SignalReferences } from "@/api/signals";

export function refCount(r: SignalReferences | undefined | null): number {
  if (!r) return 0;
  return r.decision_trees.length + r.templates.length;
}

/** Pull the reference list out of a 409 archive-conflict response. */
export function referencesFromError(err: unknown): SignalReferences | null {
  // The apiClient interceptor surfaces errors as ApiError (problem+json
  // body, extras flattened on top); fall back to a raw AxiosError too.
  let src: (Partial<SignalReferences> & { extras?: Partial<SignalReferences> }) | undefined;
  if (isApiError(err) && err.status === 409) {
    src = err.problem as Partial<SignalReferences>;
  } else if (isAxiosError(err) && err.response?.status === 409) {
    src = err.response.data as typeof src;
  }
  src = src?.extras ?? src;
  if (src && (Array.isArray(src.decision_trees) || Array.isArray(src.templates))) {
    return {
      decision_trees: src.decision_trees ?? [],
      templates: src.templates ?? [],
    };
  }
  return null;
}

export function UsedByBadge({
  count,
  onClick,
}: {
  count: number;
  onClick: () => void;
}): ReactNode {
  const { t } = useTranslation("signals");
  if (count === 0) return null;
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-full border border-ap-line bg-ap-line/30 px-2 py-0.5 text-[11px] font-medium text-ap-ink hover:bg-ap-line/60"
      title={t("config.references.badgeTitle")}
    >
      {t("config.references.badge", { count })}
    </button>
  );
}

function ReferenceItem({ reference }: { reference: SignalReference }): ReactNode {
  const label = (
    <>
      <span className="font-medium text-ap-ink">{reference.name}</span>{" "}
      <span className="font-mono text-[11px] text-ap-muted">{reference.code}</span>
    </>
  );
  // Decision trees have a tenant-wide viewer keyed by code; templates live
  // on this same page, so they render as plain rows.
  if (reference.kind === "decision_tree") {
    return (
      <Link
        to={`/settings/decision-trees/${reference.code}`}
        className="block rounded-md px-2 py-1.5 text-sm hover:bg-ap-line/30"
      >
        {label}
      </Link>
    );
  }
  return <div className="px-2 py-1.5 text-sm">{label}</div>;
}

export function ReferencesDrawer({
  title,
  references,
  onClose,
}: {
  title: string;
  references: SignalReferences;
  onClose: () => void;
}): ReactNode {
  const { t } = useTranslation("signals");
  const sections: { key: string; label: string; items: SignalReference[] }[] = [
    {
      key: "decision_trees",
      label: t("config.references.decisionTrees"),
      items: references.decision_trees,
    },
    { key: "templates", label: t("config.references.templates"), items: references.templates },
  ];
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" role="dialog" aria-modal="true">
      <button type="button" aria-label={t("config.references.close")} className="flex-1" onClick={onClose} />
      <aside className="flex w-full max-w-sm flex-col overflow-y-auto border-s border-ap-line bg-white p-4 shadow-xl">
        <div className="flex items-baseline justify-between">
          <h3 className="text-sm font-semibold text-ap-ink">{title}</h3>
          <button type="button" onClick={onClose} className="text-xs text-ap-muted hover:text-ap-ink">
            {t("config.references.close")}
          </button>
        </div>
        {refCount(references) === 0 ? (
          <p className="mt-4 text-xs text-ap-muted">{t("config.references.none")}</p>
        ) : (
          <div className="mt-3 flex flex-col gap-3">
            {sections
              .filter((s) => s.items.length > 0)
              .map((s) => (
                <div key={s.key}>
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-ap-muted">
                    {s.label} ({s.items.length})
                  </p>
                  <div className="mt-1 divide-y divide-ap-line">
                    {s.items.map((r) => (
                      <ReferenceItem key={`${r.kind}-${r.id}`} reference={r} />
                    ))}
                  </div>
                </div>
              ))}
          </div>
        )}
      </aside>
    </div>
  );
}

export function ArchiveConflictModal({
  references,
  pending,
  onCancel,
  onForce,
}: {
  references: SignalReferences;
  pending: boolean;
  onCancel: () => void;
  onForce: () => void;
}): ReactNode {
  const { t } = useTranslation("signals");
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" role="dialog" aria-modal="true">
      <div className="w-full max-w-md rounded-xl border border-ap-line bg-white p-4 shadow-xl">
        <h3 className="text-sm font-semibold text-ap-ink">{t("config.references.conflictTitle")}</h3>
        <p className="mt-1 text-xs text-ap-muted">{t("config.references.conflictBody")}</p>
        <div className="mt-3 max-h-48 overflow-y-auto rounded-md border border-ap-line">
          {[...references.decision_trees, ...references.templates].map((r) => (
            <div key={`${r.kind}-${r.id}`} className="border-b border-ap-line px-2 py-1.5 text-sm last:border-b-0">
              <span className="font-medium text-ap-ink">{r.name}</span>{" "}
              <span className="font-mono text-[11px] text-ap-muted">{r.code}</span>
              <span className="ms-1 text-[11px] text-ap-muted">
                · {t(`config.references.kind.${r.kind}`)}
              </span>
            </div>
          ))}
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={pending}
            className="rounded-md border border-ap-line bg-white px-3 py-1.5 text-xs font-medium text-ap-ink hover:bg-ap-line/40 disabled:opacity-60"
          >
            {t("config.references.cancel")}
          </button>
          <button
            type="button"
            onClick={onForce}
            disabled={pending}
            className="rounded-md bg-ap-crit px-3 py-1.5 text-xs font-medium text-white hover:bg-ap-crit/90 disabled:opacity-60"
          >
            {pending ? t("config.references.archiving") : t("config.references.archiveAnyway")}
          </button>
        </div>
      </div>
    </div>
  );
}
