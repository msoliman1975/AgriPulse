// The "Sources" marker (decision D27): a small button beside a finding, tree,
// parameter, signal, activity, reference value or input that opens the
// publications it rests on, each with its confidence. It renders nothing when
// the entity cites nothing, so it can be placed anywhere without clutter.

import { useQuery } from "@tanstack/react-query";
import { useId, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { listSourceLinks, type SourceEntityType } from "@/api/sources";
import { Pill } from "@/components/Pill";

import { CONFIDENCE_PILL, sourceHref } from "./sourceLabels";

export function SourcesMarker({
  entityType,
  entityKey,
  detail,
}: {
  entityType: SourceEntityType;
  entityKey: string;
  /** Narrow to one parameter or part of the entity; omit for all. */
  detail?: string;
}): ReactNode {
  const { t } = useTranslation("sources");
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const links = useQuery({
    queryKey: ["sources", "links", entityType, entityKey] as const,
    queryFn: () => listSourceLinks(entityType, entityKey),
    staleTime: 5 * 60_000,
  });
  const rows = (links.data ?? []).filter((l) => detail === undefined || l.detail === detail);
  if (rows.length === 0) return null;

  return (
    <span className="relative inline-block">
      <button
        type="button"
        className="rounded border border-ap-line px-1.5 py-0.5 text-[11px] text-ap-muted hover:text-ap-ink"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
      >
        {t("marker", { count: rows.length })}
      </button>
      {open ? (
        <div
          id={panelId}
          role="dialog"
          aria-label={t("markerTitle")}
          className="absolute z-20 mt-1 w-80 max-w-[90vw] rounded-md border border-ap-line bg-ap-panel p-3 shadow-lg"
        >
          <ul className="flex flex-col gap-2 text-xs">
            {rows.map((l) => {
              const href = sourceHref(l);
              return (
                <li key={l.id} className="flex flex-col gap-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <Pill kind={CONFIDENCE_PILL[l.confidence] ?? "neutral"}>
                      {t(`confidence.${l.confidence}`)}
                    </Pill>
                    {l.detail ? <code className="font-mono text-[11px]">{l.detail}</code> : null}
                  </span>
                  {href ? (
                    <a
                      className="text-ap-accent underline"
                      href={href}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {l.citation}
                    </a>
                  ) : (
                    <span>{l.citation}</span>
                  )}
                  {l.note ? <span className="text-ap-muted">{l.note}</span> : null}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </span>
  );
}
