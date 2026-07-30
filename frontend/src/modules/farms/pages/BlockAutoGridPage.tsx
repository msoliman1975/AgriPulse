import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { autoGrid, createBlock, type AutoGridCandidate } from "@/api/blocks";
import { isApiError } from "@/api/errors";
import { AreaDisplay } from "../components/AreaDisplay";
import { Breadcrumb } from "@/components/Breadcrumb";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";

export function BlockAutoGridPage(): JSX.Element {
  const { farmId = "" } = useParams<{ farmId: string }>();
  const { t } = useTranslation("farms");
  const navigate = useNavigate();
  const [cellSize, setCellSize] = useState(500);
  const [candidates, setCandidates] = useState<AutoGridCandidate[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const compute = async (): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      const result = await autoGrid(farmId, { cellSizeM: cellSize });
      setCandidates(result.candidates);
      setSelected(new Set(result.candidates.map((c) => c.code)));
    } catch (err) {
      setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err));
    } finally {
      setBusy(false);
    }
  };

  const commit = async (): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      for (const c of candidates) {
        if (!selected.has(c.code)) continue;
        await createBlock(farmId, {
          code: c.code,
          name: c.code,
          boundary: c.boundary,
          tags: [],
        });
      }
      navigate(`/farms/${farmId}`);
    } catch (err) {
      setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err));
    } finally {
      setBusy(false);
    }
  };

  const toggle = (code: string): void => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  return (
    <Page>
      <PageHeader
        above={
          <Breadcrumb
            items={[
              { label: t("list.heading"), to: "/farms" },
              { label: t("autoGrid.back"), to: `/farms/${farmId}` },
              { label: t("autoGrid.heading") },
            ]}
          />
        }
        title={t("autoGrid.heading")}
      />

      <Card className="flex items-end gap-3">
        <div>
          <label className="label" htmlFor="cell-size">
            {t("autoGrid.cellSize")}
          </label>
          <input
            id="cell-size"
            type="number"
            min={10}
            max={5000}
            step={10}
            className="input"
            value={cellSize}
            onChange={(e) => setCellSize(Number(e.target.value))}
          />
        </div>
        <Button onClick={compute} disabled={busy}>
          {t("autoGrid.compute")}
        </Button>
      </Card>

      {error ? (
        <p role="alert" className="text-sm text-ap-crit">
          {error}
        </p>
      ) : null}

      <Card>
        <h2 className="text-lg font-semibold text-ap-ink">{t("autoGrid.candidates")}</h2>
        {candidates.length === 0 ? (
          <p className="mt-2 text-sm text-ap-muted">{t("autoGrid.empty")}</p>
        ) : (
          <ul className="mt-3 space-y-1">
            {candidates.map((c) => (
              <li key={c.code} className="flex items-center justify-between text-sm">
                <label className="inline-flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={selected.has(c.code)}
                    onChange={() => toggle(c.code)}
                  />
                  {c.code}
                </label>
                <AreaDisplay areaM2={Number(c.area_m2)} />
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Button onClick={commit} disabled={busy || selected.size === 0}>
        {t("autoGrid.commit")}
      </Button>
    </Page>
  );
}
