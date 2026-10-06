import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import {
  archiveInvestor,
  getInvestor,
  updateInvestor,
  type InvestorPayload,
  type Ownership,
} from "@/api/investors";
import { Breadcrumb } from "@/components/Breadcrumb";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { ErrorState } from "@/components/ErrorState";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import { localizedName } from "@/lib/localizedField";
import { ArchiveButton } from "@/modules/farms/components/ArchiveButton";
import { AreaDisplay } from "@/modules/farms/components/AreaDisplay";
import { useCapability } from "@/rbac/useCapability";
import { InvestorFormDialog } from "../components/InvestorFormDialog";
import { InvestorLoginCard } from "../components/InvestorLoginCard";
import { INVESTOR_STATUS_PILL, errorText } from "../lib";

/** /investments/investors/:investorId — one investor: profile, app login, holdings. */
export function InvestorDetailPage(): JSX.Element {
  const { investorId = "" } = useParams<{ investorId: string }>();
  const { t, i18n } = useTranslation("investors");
  const queryClient = useQueryClient();
  const canManage = useCapability("investor.manage");
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const q = useQuery({
    queryKey: ["investors", "detail", investorId],
    queryFn: () => getInvestor(investorId),
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["investors"] });
  const update = useMutation({
    mutationFn: (payload: InvestorPayload) => updateInvestor(investorId, payload),
    onSuccess: async () => {
      setEditing(false);
      setError(null);
      await refresh();
    },
    onError: (err) => setError(errorText(err)),
  });
  const archive = useMutation({
    mutationFn: () => archiveInvestor(investorId),
    onSuccess: refresh,
    onError: (err) => setError(errorText(err)),
  });

  if (q.isError) return <ErrorState message={errorText(q.error)} />;
  if (!q.data) return <Skeleton className="h-64 w-full rounded-xl" />;
  const inv = q.data;
  const archived = inv.archived_at !== null;
  const editable = canManage && !archived;
  const current = inv.ownerships.filter((o) => o.period !== "past");
  const past = inv.ownerships.filter((o) => o.period === "past");

  const row = (label: string, value: ReactNode) => (
    <div className="flex flex-col">
      <dt className="text-xs text-ap-muted">{label}</dt>
      <dd className="text-sm text-ap-ink">{value || "—"}</dd>
    </div>
  );

  return (
    <Page>
      <PageHeader
        above={
          <Breadcrumb
            items={[{ label: t("detail.back"), to: "/investments/investors" }, { label: inv.code }]}
          />
        }
        title={
          <span className="flex items-center gap-2">
            <span className="font-mono">{inv.code}</span>
            {localizedName(i18n.language, inv.full_name, inv.full_name_ar)}
            <Pill kind={INVESTOR_STATUS_PILL[inv.status]}>{t(`status.${inv.status}`)}</Pill>
          </span>
        }
        actions={
          editable ? (
            <>
              <Button variant="ghost" onClick={() => setEditing(true)}>
                {t("detail.edit")}
              </Button>
              <ArchiveButton
                label={t("detail.archive")}
                busy={archive.isPending}
                onConfirm={async () => {
                  await archive.mutateAsync().catch(() => undefined);
                }}
              />
            </>
          ) : null
        }
      />
      {error && !editing ? (
        <p role="alert" className="text-sm text-ap-crit">
          {error}
        </p>
      ) : null}

      <Card title={t("detail.profile")}>
        <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {row(t("form.type"), t(`type.${inv.investor_type}`))}
          {row(t("form.email"), inv.email)}
          {row(t("form.phone"), inv.phone ? <span dir="ltr">{inv.phone}</span> : null)}
          {inv.investor_type === "company"
            ? row(t("form.contactPerson"), inv.contact_person)
            : null}
          {row(
            t("form.idType"),
            inv.national_id_type
              ? `${t(`idType.${inv.national_id_type}`)} ···${inv.national_id_last4 ?? ""}`
              : null,
          )}
          {row(t("form.nationality"), inv.nationality)}
          {row(t("form.country"), [inv.city, inv.country].filter(Boolean).join(", "))}
          {row(t("form.language"), t(`language.${inv.preferred_language}`))}
          {row(
            t("detail.totalArea"),
            <AreaDisplay areaM2={Number(inv.current_area_m2)} fractionDigits={2} />,
          )}
          {inv.notes_internal ? row(t("form.notes"), inv.notes_internal) : null}
        </dl>
      </Card>

      <InvestorLoginCard investor={inv} />

      <Card title={t("detail.current")} noPadding>
        <OwnershipTable rows={current} empty={t("detail.noCurrent")} />
      </Card>
      <Card title={t("detail.past")} noPadding>
        <OwnershipTable rows={past} empty={t("detail.noPast")} />
      </Card>

      {editing ? (
        <InvestorFormDialog
          investor={inv}
          busy={update.isPending}
          error={error}
          onClose={() => {
            setEditing(false);
            setError(null);
          }}
          onSubmit={(payload) => update.mutate(payload)}
        />
      ) : null}
    </Page>
  );
}

function OwnershipTable({ rows, empty }: { rows: Ownership[]; empty: string }): JSX.Element {
  const { t, i18n } = useTranslation("investors");
  if (rows.length === 0) return <p className="p-4 text-sm text-ap-muted">{empty}</p>;
  return (
    <Table>
      <Thead>
        <Tr>
          <Th>{t("col.holding")}</Th>
          <Th>{t("col.farm")}</Th>
          <Th>{t("col.block")}</Th>
          <Th>{t("col.area")}</Th>
          <Th>{t("col.from")}</Th>
          <Th>{t("col.to")}</Th>
          <Th>{t("col.contract")}</Th>
        </Tr>
      </Thead>
      <Tbody>
        {rows.map((o) => (
          <Tr key={o.id}>
            <Td>
              <Link
                className="text-ap-primary hover:underline"
                to={`/investments/holdings/${o.farm_id}/${o.holding_id}`}
              >
                <span className="font-mono">{o.holding_code}</span> ·{" "}
                {localizedName(i18n.language, o.holding_name, o.holding_name_ar)}
              </Link>
            </Td>
            <Td>{localizedName(i18n.language, o.farm_name ?? "", o.farm_name_ar)}</Td>
            <Td className="font-mono">{o.block_code ?? "—"}</Td>
            <Td>
              <AreaDisplay areaM2={Number(o.area_m2)} fractionDigits={2} />
            </Td>
            <Td>{o.start_date}</Td>
            <Td>
              {o.end_date ?? "—"}
              {o.period === "future" ? (
                <span className="text-ap-muted"> · {t("period.future")}</span>
              ) : null}
            </Td>
            <Td>{o.contract_ref ?? "—"}</Td>
          </Tr>
        ))}
      </Tbody>
    </Table>
  );
}
