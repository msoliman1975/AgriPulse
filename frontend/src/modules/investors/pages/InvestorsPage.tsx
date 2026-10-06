import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

import { createInvestor, listInvestors, type InvestorStatus } from "@/api/investors";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { FilterChip } from "@/components/FilterChip";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import { Toolbar } from "@/components/Toolbar";
import { queryState } from "@/components/asyncState";
import { localizedName } from "@/lib/localizedField";
import { AreaDisplay } from "@/modules/farms/components/AreaDisplay";
import { useCapability } from "@/rbac/useCapability";
import { InvestorFormDialog } from "../components/InvestorFormDialog";
import { INVESTOR_STATUS_PILL, errorText } from "../lib";

const STATUSES: InvestorStatus[] = ["not_invited", "invited", "active", "suspended"];

/** /settings/investors — the investor master list. */
export function InvestorsPage(): JSX.Element {
  const { t, i18n } = useTranslation("investors");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const canManage = useCapability("investor.manage");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<InvestorStatus | "">("");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [adding, setAdding] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const listQ = useQuery({
    queryKey: ["investors", "list", q, status, includeArchived],
    queryFn: () =>
      listInvestors({
        q: q.trim() || undefined,
        status: status || undefined,
        include_archived: includeArchived,
      }),
  });

  const create = useMutation({
    mutationFn: createInvestor,
    onSuccess: async (investor) => {
      setAdding(false);
      setFormError(null);
      await queryClient.invalidateQueries({ queryKey: ["investors"] });
      navigate(`/settings/investors/${investor.id}`);
    },
    onError: (err) => setFormError(errorText(err)),
  });

  const filtered = Boolean(q.trim() || status || includeArchived);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={t("list.title")}
        subtitle={t("list.subtitle")}
        actions={
          canManage ? <Button onClick={() => setAdding(true)}>{t("list.add")}</Button> : null
        }
      />
      <Toolbar
        right={
          <div className="flex flex-wrap items-center gap-2">
            <input
              aria-label={t("list.search")}
              placeholder={t("list.search")}
              className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-sm"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            <select
              aria-label={t("col.status")}
              className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-sm"
              value={status}
              onChange={(e) => setStatus(e.target.value as InvestorStatus | "")}
            >
              <option value="">{t("list.allStatuses")}</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {t(`status.${s}`)}
                </option>
              ))}
            </select>
          </div>
        }
        chips={
          <FilterChip active={includeArchived} onToggle={() => setIncludeArchived((v) => !v)}>
            {t("list.includeArchived")}
          </FilterChip>
        }
      />
      <AsyncBoundary
        state={queryState(listQ)}
        errorMessage={t("error.load")}
        isEmpty={(rows) => rows.length === 0}
        filtered={filtered}
        empty={
          <EmptyState
            message={t("list.empty")}
            action={
              canManage ? <Button onClick={() => setAdding(true)}>{t("list.add")}</Button> : null
            }
          />
        }
        noResults={<EmptyState message={t("list.emptyFiltered")} action={null} />}
      >
        {(rows) => (
          <Card noPadding>
            <Table>
              <Thead>
                <Tr>
                  <Th>{t("col.code")}</Th>
                  <Th>{t("col.name")}</Th>
                  <Th>{t("col.type")}</Th>
                  <Th>{t("col.email")}</Th>
                  <Th>{t("col.phone")}</Th>
                  <Th>{t("col.status")}</Th>
                  <Th>{t("col.holdings")}</Th>
                  <Th>{t("col.area")}</Th>
                </Tr>
              </Thead>
              <Tbody>
                {rows.map((r) => (
                  <Tr key={r.id}>
                    <Td>
                      <Link
                        className="font-mono text-ap-primary hover:underline"
                        to={`/settings/investors/${r.id}`}
                      >
                        {r.code}
                      </Link>
                    </Td>
                    <Td>
                      <Link className="hover:underline" to={`/settings/investors/${r.id}`}>
                        {localizedName(i18n.language, r.full_name, r.full_name_ar)}
                      </Link>
                    </Td>
                    <Td>{t(`type.${r.investor_type}`)}</Td>
                    <Td>{r.email}</Td>
                    <Td dir="ltr">{r.phone ?? "—"}</Td>
                    <Td>
                      <Pill kind={INVESTOR_STATUS_PILL[r.status]}>{t(`status.${r.status}`)}</Pill>
                    </Td>
                    <Td>{r.current_holdings_count}</Td>
                    <Td>
                      {r.current_holdings_count > 0 ? (
                        <AreaDisplay areaM2={Number(r.current_area_m2)} fractionDigits={2} />
                      ) : (
                        "—"
                      )}
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          </Card>
        )}
      </AsyncBoundary>
      {adding ? (
        <InvestorFormDialog
          investor={null}
          busy={create.isPending}
          error={formError}
          onClose={() => {
            setAdding(false);
            setFormError(null);
          }}
          onSubmit={(payload) => create.mutate(payload)}
        />
      ) : null}
    </div>
  );
}
