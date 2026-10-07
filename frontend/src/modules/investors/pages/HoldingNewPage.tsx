import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";
import type { Polygon } from "geojson";

import {
  checkHoldingShapes,
  createFarmHolding,
  getFarmHoldingsMap,
  listInvestors,
  type HoldingCheckResult,
  type HoldingFormStatus,
} from "@/api/investors";
import { Breadcrumb } from "@/components/Breadcrumb";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { ErrorState } from "@/components/ErrorState";
import { FIELD_CONTROL_CLASS } from "@/components/Field";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { SegmentedControl } from "@/components/SegmentedControl";
import { Skeleton } from "@/components/Skeleton";
import { StatusBanner } from "@/components/StatusBanner";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import type { PolygonalFeature } from "@/lib/aoi/parse";
import { localizedName } from "@/lib/localizedField";
import { AoiUploader } from "@/modules/farms/components/AoiUploader";
import { AreaDisplay } from "@/modules/farms/components/AreaDisplay";
import { MapDraw, type MapDrawReference } from "@/modules/farms/components/MapDraw";
import { FarmHoldingsMap } from "../components/FarmHoldingsMap";
import { HoldingFields, type HoldingFieldValues } from "../components/HoldingFields";
import { errorText, formatPct, isoDay, saleFields } from "../lib";

type Mode = "draw" | "upload";

const EMPTY: HoldingFieldValues = {
  code: "",
  name: "",
  name_ar: "",
  tree_count: "",
  status: "draft",
  investor_id: "",
  owner_since: isoDay(),
  notes_internal: "",
};

/** A shape taken from an AOI file, with what the user chose for it. */
interface UploadRow {
  polygon: Polygon;
  name: string;
  status: HoldingFormStatus;
  investor_id: string;
  check: HoldingCheckResult | null;
  created?: string;
  error?: string;
}

/** One holding per polygon: a multipolygon's parts become separate holdings. */
export function splitFeatures(
  features: PolygonalFeature[],
  defaultName: (n: number) => string,
): UploadRow[] {
  const rows: UploadRow[] = [];
  for (const f of features) {
    const props = (f.properties ?? {}) as Record<string, unknown>;
    const given = [props.name, props.Name, props.NAME, props.title].find(
      (v) => typeof v === "string" && v.trim(),
    ) as string | undefined;
    const parts: Polygon[] =
      f.geometry.type === "Polygon"
        ? [f.geometry]
        : f.geometry.coordinates.map((c) => ({
            type: "Polygon",
            coordinates: c,
          }));
    parts.forEach((polygon, i) => {
      const n = rows.length + 1;
      rows.push({
        polygon,
        name: given ? (parts.length > 1 ? `${given} ${i + 1}` : given) : defaultName(n),
        status: "draft",
        investor_id: "",
        check: null,
      });
    });
  }
  return rows;
}

/**
 * /investments/holdings/:farmId/new — draw a holding or upload AOI files.
 * The block is never picked: the server finds the block that fully contains
 * each shape, and refuses a shape that crosses blocks or overlaps a holding.
 */
export function HoldingNewPage(): JSX.Element {
  const { farmId = "" } = useParams<{ farmId: string }>();
  const { t, i18n } = useTranslation("investors");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<Mode>("draw");

  const mapQ = useQuery({
    queryKey: ["holdings", "farm-map", farmId],
    queryFn: () => getFarmHoldingsMap(farmId),
  });
  const references = useMemo<MapDrawReference[]>(() => {
    if (!mapQ.data) return [];
    return [
      ...mapQ.data.blocks.map((b) => ({ geometry: b.boundary, kind: "frame" as const })),
      ...mapQ.data.holdings.map((h) => ({ geometry: h.boundary, kind: "neighbour" as const })),
    ];
  }, [mapQ.data]);

  // ---- Draw ---------------------------------------------------------------
  const [polygon, setPolygon] = useState<Polygon | null>(null);
  const [check, setCheck] = useState<HoldingCheckResult | null>(null);
  const [checking, setChecking] = useState(false);
  const [values, setValues] = useState<HoldingFieldValues>(EMPTY);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setCheck(null);
    if (!polygon) return;
    let cancelled = false;
    setChecking(true);
    checkHoldingShapes(farmId, [polygon])
      .then(([r]) => {
        if (!cancelled) setCheck(r ?? null);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(errorText(err));
      })
      .finally(() => {
        if (!cancelled) setChecking(false);
      });
    return () => {
      cancelled = true;
    };
  }, [farmId, polygon]);

  const create = useMutation({
    mutationFn: () =>
      createFarmHolding(farmId, {
        code: values.code.trim() || null,
        name: values.name.trim(),
        name_ar: values.name_ar.trim() || null,
        boundary: polygon as Polygon,
        tree_count: values.tree_count === "" ? null : Number(values.tree_count),
        status: values.status,
        notes_internal: values.notes_internal.trim() || null,
        ...saleFields(values),
      }),
    onSuccess: async (holding) => {
      await queryClient.invalidateQueries({ queryKey: ["holdings"] });
      navigate(`/investments/holdings/${farmId}/${holding.id}`, { state: { created: true } });
    },
    onError: (err) => setError(errorText(err)),
  });
  const saleMissing = values.status === "sold" && !values.investor_id;
  const canSave =
    Boolean(polygon) &&
    Boolean(check?.block_id) &&
    !check?.problem &&
    Boolean(values.name.trim()) &&
    !saleMissing &&
    !create.isPending;

  // ---- Upload ------------------------------------------------------------
  const [rows, setRows] = useState<UploadRow[]>([]);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const investorsQ = useQuery({
    queryKey: ["investors", "list", "picker"],
    queryFn: () => listInvestors(),
    enabled: rows.some((r) => r.status === "sold"),
  });

  const onFeatures = async (features: PolygonalFeature[]): Promise<void> => {
    setUploadError(null);
    const next = splitFeatures(features, (n) => t("newHolding.defaultName", { n }));
    setRows(next);
    try {
      const results = await checkHoldingShapes(
        farmId,
        next.map((r) => r.polygon),
      );
      setRows(next.map((r, i) => ({ ...r, check: results[i] ?? null })));
    } catch (err) {
      setUploadError(errorText(err));
    }
  };
  const setRow = (i: number, patch: Partial<UploadRow>): void =>
    setRows((prev) => prev.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const ready = rows.filter(
    (r) =>
      !r.created &&
      r.check?.block_id &&
      !r.check.problem &&
      r.name.trim() &&
      !(r.status === "sold" && !r.investor_id),
  );
  const createAll = async (): Promise<void> => {
    setRunning(true);
    for (let i = 0; i < rows.length; i += 1) {
      const r = rows[i];
      if (!ready.includes(r)) continue;
      try {
        const h = await createFarmHolding(farmId, {
          name: r.name.trim(),
          boundary: r.polygon,
          status: r.status,
          block_id: r.check?.block_id ?? null,
          ...(r.status === "sold" ? { investor_id: r.investor_id, owner_since: isoDay() } : {}),
        });
        setRow(i, { created: h.code, error: undefined });
      } catch (err) {
        setRow(i, { error: errorText(err) });
      }
    }
    setRunning(false);
    await queryClient.invalidateQueries({ queryKey: ["holdings"] });
  };
  const createdCount = rows.filter((r) => r.created).length;
  const failedCount = rows.filter((r) => r.error).length;
  // Every shape that could be created was: the Create button has nothing
  // left to do, so it gives way to the result and the next steps.
  const finished = createdCount > 0 && ready.length === 0 && !running;

  if (mapQ.isError) return <ErrorState message={errorText(mapQ.error)} />;
  if (!mapQ.data) return <Skeleton className="h-64 w-full rounded-xl" />;

  return (
    <Page>
      <PageHeader
        above={
          <Breadcrumb
            items={[
              { label: t("nav.holdings"), to: `/investments/holdings/${farmId}` },
              { label: t("newHolding.title") },
            ]}
          />
        }
        title={t("newHolding.title")}
        subtitle={t("newHolding.subtitle")}
      />
      <SegmentedControl<Mode>
        ariaLabel={t("newHolding.title")}
        value={mode}
        onChange={setMode}
        items={[
          { value: "draw", label: t("newHolding.tabDraw") },
          { value: "upload", label: t("newHolding.tabUpload") },
        ]}
      />

      {mode === "draw" ? (
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            setError(null);
            if (canSave) create.mutate();
          }}
        >
          <Card>
            <p className="mb-2 text-sm text-ap-muted">{t("newHolding.drawHelp")}</p>
            <MapDraw
              references={references}
              onChange={setPolygon}
              clearLabel={t("newHolding.clear")}
              className="h-[28rem] w-full overflow-hidden rounded-md border border-ap-line"
            />
            <p className="mt-2 text-sm" data-testid="draw-check">
              {!polygon ? (
                <span className="text-ap-muted">{t("newHolding.noShape")}</span>
              ) : checking ? (
                <span className="text-ap-muted">{t("newHolding.checking")}</span>
              ) : check?.problem ? (
                <span className="text-ap-crit">{check.detail}</span>
              ) : check?.block_id ? (
                <span className="text-ap-ink">
                  <AreaDisplay areaM2={Number(check.area_m2)} fractionDigits={2} /> ·{" "}
                  {t("newHolding.detected", {
                    block: check.block_code ?? "",
                    share: formatPct(check.share_pct ?? 0, i18n.language),
                  })}
                </span>
              ) : null}
            </p>
          </Card>
          <Card>
            <HoldingFields values={values} onChange={setValues} showCode />
            {saleMissing ? (
              <p className="mt-2 text-sm text-ap-warn">{t("newHolding.soldNeedsInvestor")}</p>
            ) : null}
          </Card>
          {error ? (
            <p role="alert" className="text-sm text-ap-crit">
              {error}
            </p>
          ) : null}
          <div className="flex gap-2">
            <Button type="submit" disabled={!canSave}>
              {t("holding.create")}
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={() => navigate(`/investments/holdings/${farmId}`)}
            >
              {t("holding.cancel")}
            </Button>
          </div>
        </form>
      ) : (
        <div className="flex flex-col gap-4">
          <Card>
            <p className="mb-2 text-sm text-ap-muted">{t("newHolding.uploadHelp")}</p>
            <AoiUploader multiple onFeaturesParsed={(f) => void onFeatures(f)} />
            {uploadError ? (
              <p role="alert" className="mt-2 text-sm text-ap-crit">
                {uploadError}
              </p>
            ) : null}
          </Card>
          {rows.length > 0 ? (
            <>
              <Card>
                <FarmHoldingsMap
                  blocks={mapQ.data.blocks}
                  holdings={mapQ.data.holdings}
                  previews={rows.map((r) => ({
                    geometry: r.polygon,
                    ok: Boolean(r.check?.block_id && !r.check.problem),
                  }))}
                />
              </Card>
              <Card noPadding>
                <Table>
                  <Thead>
                    <Tr>
                      <Th>{t("newHolding.colShape")}</Th>
                      <Th>{t("newHolding.colName")}</Th>
                      <Th>{t("newHolding.colBlock")}</Th>
                      <Th>{t("newHolding.colArea")}</Th>
                      <Th>{t("newHolding.colStatus")}</Th>
                      <Th>{t("newHolding.colInvestor")}</Th>
                      <Th>{t("newHolding.colResult")}</Th>
                    </Tr>
                  </Thead>
                  <Tbody>
                    {rows.map((r, i) => {
                      const locked = Boolean(r.created) || running;
                      return (
                        <Tr key={i}>
                          <Td>{i + 1}</Td>
                          <Td>
                            <input
                              aria-label={t("newHolding.colName")}
                              className={FIELD_CONTROL_CLASS}
                              value={r.name}
                              disabled={locked}
                              onChange={(e) => setRow(i, { name: e.target.value })}
                            />
                          </Td>
                          <Td className="font-mono">{r.check?.block_code ?? "—"}</Td>
                          <Td>
                            {r.check?.area_m2 ? (
                              <AreaDisplay areaM2={Number(r.check.area_m2)} fractionDigits={2} />
                            ) : (
                              "—"
                            )}
                          </Td>
                          <Td>
                            <select
                              aria-label={t("newHolding.colStatus")}
                              className={FIELD_CONTROL_CLASS}
                              value={r.status}
                              disabled={locked}
                              onChange={(e) =>
                                setRow(i, { status: e.target.value as HoldingFormStatus })
                              }
                            >
                              <option value="draft">{t("holdingStatus.draft")}</option>
                              <option value="available">{t("holdingStatus.available")}</option>
                              <option value="sold">{t("holdingStatus.sold")}</option>
                            </select>
                          </Td>
                          <Td>
                            {r.status === "sold" ? (
                              <select
                                aria-label={t("newHolding.colInvestor")}
                                className={FIELD_CONTROL_CLASS}
                                value={r.investor_id}
                                disabled={locked}
                                onChange={(e) => setRow(i, { investor_id: e.target.value })}
                              >
                                <option value="">{t("newHolding.pickInvestor")}</option>
                                {(investorsQ.data ?? []).map((inv) => (
                                  <option key={inv.id} value={inv.id}>
                                    {inv.code} ·{" "}
                                    {localizedName(i18n.language, inv.full_name, inv.full_name_ar)}
                                  </option>
                                ))}
                              </select>
                            ) : (
                              "—"
                            )}
                            {r.status === "sold" &&
                            investorsQ.isSuccess &&
                            investorsQ.data.length === 0 ? (
                              <p className="mt-1 text-xs text-ap-warn">
                                {t("newHolding.noInvestors")}
                              </p>
                            ) : null}
                          </Td>
                          <Td className="text-sm">
                            {r.created ? (
                              <span className="text-ap-primary">
                                {t("newHolding.created", { code: r.created })}
                              </span>
                            ) : r.error ? (
                              <span className="text-ap-crit">{r.error}</span>
                            ) : r.check?.problem ? (
                              <span className="text-ap-crit">{r.check.detail}</span>
                            ) : r.check ? (
                              <span className="text-ap-primary">✓</span>
                            ) : (
                              <span className="text-ap-muted">{t("newHolding.checking")}</span>
                            )}
                          </Td>
                        </Tr>
                      );
                    })}
                  </Tbody>
                </Table>
              </Card>
              {finished ? (
                <StatusBanner
                  detail={
                    failedCount > 0
                      ? t("newHolding.doneSummary", { created: createdCount, failed: failedCount })
                      : undefined
                  }
                >
                  {t("newHolding.createdOkCount", { count: createdCount })}
                </StatusBanner>
              ) : null}
              <div className="flex flex-wrap items-center gap-3">
                {finished ? (
                  <>
                    <Button onClick={() => navigate(`/investments/holdings/${farmId}`)}>
                      {t("newHolding.viewHoldings")}
                    </Button>
                    <Button variant="ghost" onClick={() => setRows([])}>
                      {t("newHolding.uploadMore")}
                    </Button>
                  </>
                ) : (
                  <>
                    <Button
                      disabled={ready.length === 0 || running}
                      onClick={() => void createAll()}
                    >
                      {t("newHolding.createAll", { count: ready.length })}
                    </Button>
                    {createdCount + failedCount > 0 ? (
                      <span className="text-sm text-ap-muted">
                        {t("newHolding.doneSummary", {
                          created: createdCount,
                          failed: failedCount,
                        })}
                      </span>
                    ) : null}
                    <Link
                      className="text-sm text-ap-primary hover:underline"
                      to={`/investments/holdings/${farmId}`}
                    >
                      {t("newHolding.backToList")}
                    </Link>
                  </>
                )}
              </div>
            </>
          ) : null}
        </div>
      )}
    </Page>
  );
}
