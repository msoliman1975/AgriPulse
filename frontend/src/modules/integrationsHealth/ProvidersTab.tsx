import { formatDistanceToNow, parseISO } from "date-fns";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Card } from "@/components/Card";
import { Pill, type PillKind } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import { useDateLocale } from "@/hooks/useDateLocale";
import {
  useProviderErrorHistogram,
  useProviderProbes,
  useProvidersHealth,
} from "@/queries/integrationsHealth";
import type { AttemptKind, ProbeStatus, ProviderHealth } from "@/api/integrationsHealth";

export interface ProvidersTabProps {
  basePath: string;
  platformScope: boolean;
}

export function ProvidersTab({ basePath, platformScope }: ProvidersTabProps): ReactNode {
  const { t } = useTranslation("integrationsHealth");
  const providersQ = useProvidersHealth(platformScope, basePath);
  const [selected, setSelected] = useState<{
    kind: AttemptKind;
    code: string;
  } | null>(null);

  const rows = providersQ.data ?? [];

  return (
    <div className="flex flex-col gap-3">
      {!platformScope ? (
        <p className="text-xs text-ap-muted">{t("providers.platformOnly")}</p>
      ) : null}

      {providersQ.isLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : providersQ.isError ? (
        <p className="text-sm text-ap-crit">{t("loadFailed")}</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-ap-muted">{t("providers.empty")}</p>
      ) : (
        <ProvidersTable
          rows={rows}
          platformScope={platformScope}
          selected={selected}
          onSelect={setSelected}
        />
      )}

      {platformScope && selected ? (
        <>
          <ErrorHistogram kind={selected.kind} code={selected.code} />
          <ProbeHistory kind={selected.kind} code={selected.code} />
        </>
      ) : null}
    </div>
  );
}

function ErrorHistogram({ kind, code }: { kind: AttemptKind; code: string }): ReactNode {
  const { t } = useTranslation("integrationsHealth");
  const q = useProviderErrorHistogram(kind, code, 24);
  const entries = q.data ?? [];
  const max = entries.reduce((m, e) => Math.max(m, e.count), 0);

  return (
    <Card noPadding className="p-3">
      <header className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-medium text-ap-ink">{t("providers.histogram.title")}</h3>
        <span className="text-xs text-ap-muted">
          {t("providers.histogram.windowLabel", { h: 24 })}
        </span>
      </header>
      {q.isLoading ? (
        <Skeleton className="h-16 w-full" />
      ) : q.isError ? (
        <p className="text-xs text-ap-crit">{t("loadFailed")}</p>
      ) : entries.length === 0 ? (
        <p className="text-xs text-ap-muted">{t("providers.histogram.empty")}</p>
      ) : (
        <ul className="flex flex-col gap-1.5 text-xs">
          {entries.map((e) => (
            <li key={e.error_code} className="flex items-center gap-2">
              <span className="w-32 shrink-0 font-mono text-ap-ink">{e.error_code}</span>
              <div className="flex-1 overflow-hidden rounded bg-ap-line/40">
                <div
                  className="h-2 rounded bg-ap-crit"
                  style={{
                    width: max > 0 ? `${(e.count / max) * 100}%` : "0%",
                  }}
                />
              </div>
              <span className="w-10 shrink-0 text-end font-mono text-ap-muted">{e.count}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function ProvidersTable({
  rows,
  platformScope,
  selected,
  onSelect,
}: {
  rows: ProviderHealth[];
  platformScope: boolean;
  selected: { kind: AttemptKind; code: string } | null;
  onSelect: (s: { kind: AttemptKind; code: string } | null) => void;
}): ReactNode {
  const { t } = useTranslation("integrationsHealth");
  const dateLocale = useDateLocale();
  return (
    <Card noPadding className="overflow-x-auto">
      <Table>
        <Thead>
          <Tr>
            <Th>{t("providers.col.provider")}</Th>
            <Th>{t("providers.col.kind")}</Th>
            <Th>{t("providers.col.status")}</Th>
            <Th>{t("providers.col.lastProbeAt")}</Th>
            <Th className="text-end">{t("providers.col.latency")}</Th>
            <Th>{t("providers.col.error")}</Th>
          </Tr>
        </Thead>
        <Tbody>
          {rows.map((r) => {
            const isSelected =
              selected?.kind === r.provider_kind && selected?.code === r.provider_code;
            return (
              <Tr
                key={`${r.provider_kind}-${r.provider_code}`}
                className={
                  platformScope
                    ? "cursor-pointer hover:bg-ap-line/30 " + (isSelected ? "bg-ap-line/40" : "")
                    : ""
                }
                onClick={
                  platformScope
                    ? () =>
                        onSelect(
                          isSelected ? null : { kind: r.provider_kind, code: r.provider_code },
                        )
                    : undefined
                }
              >
                <Td className="font-mono text-ap-ink">{r.provider_code}</Td>
                <Td>{t(`kind.${r.provider_kind}`)}</Td>
                <Td>
                  <Pill kind={pillForProbe(r.last_status)}>
                    {t(
                      r.last_status
                        ? `providers.probeStatus.${r.last_status}`
                        : "providers.probeStatus.unknown",
                    )}
                  </Pill>
                  {r.failed_24h > 0 ? (
                    <span className="ms-2 text-xs text-ap-crit">
                      {t("badge.failed24h", { n: r.failed_24h })}
                    </span>
                  ) : null}
                </Td>
                <Td>
                  {r.last_probe_at
                    ? formatDistanceToNow(parseISO(r.last_probe_at), {
                        addSuffix: true,
                        locale: dateLocale,
                      })
                    : "—"}
                </Td>
                <Td className="text-end">
                  {r.last_latency_ms !== null ? `${r.last_latency_ms}ms` : "—"}
                </Td>
                <Td className="max-w-xs truncate" title={r.last_error_message ?? ""}>
                  {r.last_error_message ?? ""}
                </Td>
              </Tr>
            );
          })}
        </Tbody>
      </Table>
    </Card>
  );
}

function ProbeHistory({ kind, code }: { kind: AttemptKind; code: string }): ReactNode {
  const { t } = useTranslation("integrationsHealth");
  const probesQ = useProviderProbes(kind, code);
  const dateLocale = useDateLocale();

  return (
    <Card noPadding className="p-3">
      <header className="mb-2 flex items-center gap-2">
        <h3 className="text-sm font-medium text-ap-ink">
          {kind} · <span className="font-mono">{code}</span>
        </h3>
      </header>
      {probesQ.isLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : probesQ.isError ? (
        <p className="text-xs text-ap-crit">{t("loadFailed")}</p>
      ) : (probesQ.data ?? []).length === 0 ? (
        <p className="text-xs text-ap-muted">{t("providers.empty")}</p>
      ) : (
        <ul className="divide-y divide-ap-line text-xs">
          {(probesQ.data ?? []).map((p) => (
            <li key={p.probe_at} className="flex items-center justify-between gap-2 py-1.5">
              <span className="text-ap-muted">
                {formatDistanceToNow(parseISO(p.probe_at), {
                  addSuffix: true,
                  locale: dateLocale,
                })}
              </span>
              <Pill kind={pillForProbe(p.status)}>{t(`providers.probeStatus.${p.status}`)}</Pill>
              <span className="text-ap-muted">
                {p.latency_ms !== null ? `${p.latency_ms}ms` : "—"}
              </span>
              <span className="max-w-[12rem] truncate text-ap-muted" title={p.error_message ?? ""}>
                {p.error_message ?? ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function pillForProbe(s: ProbeStatus | null): PillKind {
  if (s === null) return "neutral";
  if (s === "ok") return "ok";
  if (s === "timeout") return "warn";
  return "crit";
}
