import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";
import type { Polygon } from "geojson";

import {
  archiveHolding,
  assignOwner,
  deleteOwnership,
  endOwnership,
  getBlockHoldings,
  getHolding,
  updateHolding,
  type HoldingDetail,
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
import { MapDraw, type MapDrawReference } from "@/modules/farms/components/MapDraw";
import { useCapability } from "@/rbac/useCapability";
import { HoldingFields, type HoldingFieldValues } from "../components/HoldingFields";
import { HoldingsMap } from "../components/HoldingsMap";
import { AssignOwnerDialog, EndOwnershipDialog } from "../components/OwnerDialogs";
import { HOLDING_STATUS_PILL, blockHoldingsKey, errorText, formatPct } from "../lib";

function toValues(h: HoldingDetail): HoldingFieldValues {
  return {
    code: h.code,
    name: h.name,
    name_ar: h.name_ar ?? "",
    tree_count: h.tree_count === null ? "" : String(h.tree_count),
    status: h.status === "draft" ? "draft" : "available",
    notes_internal: h.notes_internal ?? "",
  };
}

/** /investments/holdings/:farmId/:holdingId — one holding, its details and owners. */
export function HoldingDetailPage(): JSX.Element {
  const { farmId = "", holdingId = "" } = useParams<{ farmId: string; holdingId: string }>();
  const { t, i18n } = useTranslation("investors");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const canManage = useCapability("holding.manage", { farmId });
  const canRedrawSold = useCapability("holding.redraw_sold", { farmId });
  const canAssign = useCapability("holding.assign_owner", { farmId });

  const holdingQ = useQuery({
    queryKey: ["holdings", "detail", farmId, holdingId],
    queryFn: () => getHolding(farmId, holdingId),
  });
  const holding = holdingQ.data;
  const blockQ = useQuery({
    queryKey: blockHoldingsKey(farmId, holding?.block_id ?? ""),
    queryFn: () => getBlockHoldings(farmId, holding?.block_id ?? ""),
    enabled: Boolean(holding),
  });

  const [values, setValues] = useState<HoldingFieldValues | null>(null);
  const [redrawing, setRedrawing] = useState(false);
  const [newBoundary, setNewBoundary] = useState<Polygon | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [assignOpen, setAssignOpen] = useState(false);
  const [ending, setEnding] = useState<Ownership | null>(null);
  const [ownerError, setOwnerError] = useState<string | null>(null);

  useEffect(() => {
    if (holding) setValues(toValues(holding));
  }, [holding]);

  const refresh = async (): Promise<void> => {
    await queryClient.invalidateQueries({ queryKey: ["holdings"] });
    await queryClient.invalidateQueries({ queryKey: ["investors"] });
  };

  const save = useMutation({
    mutationFn: () => {
      if (!values) throw new Error("no values");
      return updateHolding(farmId, holdingId, {
        name: values.name.trim(),
        name_ar: values.name_ar.trim() || null,
        tree_count: values.tree_count === "" ? null : Number(values.tree_count),
        notes_internal: values.notes_internal.trim() || null,
        ...(holding?.status === "draft" || holding?.status === "available"
          ? { status: values.status }
          : {}),
        ...(redrawing && newBoundary ? { boundary: newBoundary } : {}),
      });
    },
    onSuccess: async () => {
      setFormError(null);
      setRedrawing(false);
      setNewBoundary(null);
      await refresh();
    },
    onError: (err) => setFormError(errorText(err)),
  });

  const archive = useMutation({
    mutationFn: () => archiveHolding(farmId, holdingId),
    onSuccess: refresh,
    onError: (err) => setFormError(errorText(err)),
  });

  const assign = useMutation({
    mutationFn: (payload: Parameters<typeof assignOwner>[2]) =>
      assignOwner(farmId, holdingId, payload),
    onSuccess: async () => {
      setAssignOpen(false);
      setOwnerError(null);
      await refresh();
    },
    onError: (err) => setOwnerError(errorText(err)),
  });

  const end = useMutation({
    mutationFn: (payload: Parameters<typeof endOwnership>[2]) =>
      endOwnership(farmId, ending?.id ?? "", payload),
    onSuccess: async () => {
      setEnding(null);
      setOwnerError(null);
      await refresh();
    },
    onError: (err) => setOwnerError(errorText(err)),
  });

  const remove = useMutation({
    mutationFn: (ownershipId: string) => deleteOwnership(farmId, ownershipId),
    onSuccess: refresh,
    onError: (err) => setOwnerError(errorText(err)),
  });

  const references = useMemo<MapDrawReference[]>(() => {
    if (!blockQ.data) return [];
    return [
      { geometry: blockQ.data.boundary, kind: "frame" },
      ...blockQ.data.holdings
        .filter((h) => h.id !== holdingId)
        .map((h) => ({ geometry: h.boundary, kind: "neighbour" as const })),
    ];
  }, [blockQ.data, holdingId]);

  if (holdingQ.isError) return <ErrorState message={errorText(holdingQ.error)} />;
  if (!holding || !values) return <Skeleton className="h-64 w-full rounded-xl" />;

  const archived = holding.archived_at !== null;
  const sold = holding.current_owner !== null;
  const editable = canManage && !archived;
  const redrawAllowed = editable && (!sold || canRedrawSold);
  const hasOpenEnded = holding.ownerships.some((o) => o.end_date === null);
  const name = localizedName(i18n.language, holding.name, holding.name_ar);

  return (
    <Page>
      <PageHeader
        above={
          <Breadcrumb
            items={[
              { label: t("nav.holdings"), to: `/investments/holdings/${farmId}` },
              {
                label: `${localizedName(i18n.language, holding.farm_name ?? "", holding.farm_name_ar)} · ${holding.block_code ?? ""}`,
              },
              { label: holding.code },
            ]}
          />
        }
        title={
          <span className="flex items-center gap-2">
            <span className="font-mono">{holding.code}</span> {name}
            <Pill kind={HOLDING_STATUS_PILL[holding.status]}>
              {t(`holdingStatus.${holding.status}`)}
            </Pill>
          </span>
        }
        subtitle={
          <>
            <AreaDisplay areaM2={Number(holding.area_m2)} fractionDigits={2} /> ·{" "}
            {formatPct(holding.share_pct, i18n.language)}% · {t("holding.shareNote")}
          </>
        }
        actions={
          editable && !hasOpenEnded ? (
            <ArchiveButton
              label={t("holding.archive")}
              busy={archive.isPending}
              onConfirm={async () => {
                await archive.mutateAsync();
              }}
            />
          ) : null
        }
      />

      <Card>
        {redrawing ? (
          <MapDraw
            initial={holding.boundary}
            mode="simple_select"
            references={references}
            onChange={setNewBoundary}
          />
        ) : blockQ.data ? (
          <HoldingsMap
            block={blockQ.data.boundary}
            holdings={blockQ.data.holdings}
            highlightId={holding.id}
            onSelect={(id) => {
              if (id !== holdingId) navigate(`/investments/holdings/${farmId}/${id}`);
            }}
          />
        ) : (
          <Skeleton className="h-72 w-full" />
        )}
        {editable ? (
          <div className="mt-2 flex items-center gap-3">
            {redrawAllowed ? (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setRedrawing((v) => !v);
                  setNewBoundary(null);
                }}
              >
                {redrawing ? t("holding.stopEditBoundary") : t("holding.editBoundary")}
              </Button>
            ) : (
              <span className="text-sm text-ap-muted">{t("holding.redrawBlocked")}</span>
            )}
          </div>
        ) : null}
      </Card>

      <Card title={t("holding.details")}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <fieldset disabled={!editable} className="flex flex-col gap-3">
            <HoldingFields
              values={values}
              onChange={setValues}
              showStatus={holding.status === "draft" || holding.status === "available"}
            />
            {formError ? (
              <p role="alert" className="text-sm text-ap-crit">
                {formError}
              </p>
            ) : null}
            {editable ? (
              <div>
                <Button type="submit" disabled={save.isPending || !values.name.trim()}>
                  {t("holding.save")}
                </Button>
              </div>
            ) : null}
          </fieldset>
        </form>
      </Card>

      <Card
        title={t("holding.ownership")}
        actions={
          canAssign && !archived ? (
            <Button size="sm" onClick={() => setAssignOpen(true)}>
              {hasOpenEnded ? t("holding.transfer") : t("holding.assign")}
            </Button>
          ) : null
        }
      >
        {ownerError && !assignOpen && !ending ? (
          <p role="alert" className="mb-2 text-sm text-ap-crit">
            {ownerError}
          </p>
        ) : null}
        {holding.ownerships.length === 0 ? (
          <p className="text-sm text-ap-muted">{t("holding.noOwner")}</p>
        ) : (
          <Table>
            <Thead>
              <Tr>
                <Th>{t("col.investor")}</Th>
                <Th>{t("col.from")}</Th>
                <Th>{t("col.to")}</Th>
                <Th>{t("col.how")}</Th>
                <Th>{t("col.contract")}</Th>
                <Th>{t("col.status")}</Th>
                {canAssign ? <Th /> : null}
              </Tr>
            </Thead>
            <Tbody>
              {holding.ownerships.map((o) => (
                <Tr key={o.id}>
                  <Td>
                    <Link
                      className="text-ap-primary hover:underline"
                      to={`/investments/investors/${farmId}/${o.investor_id}`}
                    >
                      {o.investor_code} ·{" "}
                      {localizedName(i18n.language, o.investor_name, o.investor_name_ar)}
                    </Link>
                  </Td>
                  <Td>{o.start_date}</Td>
                  <Td>
                    {o.end_date ?? "—"}
                    {o.ended_by ? (
                      <span className="text-ap-muted"> · {t(`endedBy.${o.ended_by}`)}</span>
                    ) : null}
                  </Td>
                  <Td>{t(`acquiredBy.${o.acquired_by}`)}</Td>
                  <Td>{o.contract_ref ?? "—"}</Td>
                  <Td>
                    <Pill kind={o.period === "current" ? "ok" : "neutral"}>
                      {t(`period.${o.period}`)}
                    </Pill>
                  </Td>
                  {canAssign ? (
                    <Td className="whitespace-nowrap">
                      {o.end_date === null ? (
                        <Button variant="ghost" size="sm" onClick={() => setEnding(o)}>
                          {t("holding.end")}
                        </Button>
                      ) : null}
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          if (window.confirm(t("holding.deleteConfirm"))) remove.mutate(o.id);
                        }}
                      >
                        {t("holding.delete")}
                      </Button>
                    </Td>
                  ) : null}
                </Tr>
              ))}
            </Tbody>
          </Table>
        )}
      </Card>

      {assignOpen ? (
        <AssignOwnerDialog
          open={assignOpen}
          holding={holding}
          busy={assign.isPending}
          error={ownerError}
          onClose={() => {
            setAssignOpen(false);
            setOwnerError(null);
          }}
          onSubmit={(payload) => assign.mutate(payload)}
        />
      ) : null}
      {ending ? (
        <EndOwnershipDialog
          ownership={ending}
          busy={end.isPending}
          error={ownerError}
          onClose={() => {
            setEnding(null);
            setOwnerError(null);
          }}
          onSubmit={(payload) => end.mutate(payload)}
        />
      ) : null}
    </Page>
  );
}
