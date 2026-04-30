import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { getFarm, updateFarm, type FarmDetail } from "@/api/farms";
import { isApiError } from "@/api/errors";
import { FarmForm, type FarmFormValues } from "../components/FarmForm";

export function FarmEditPage(): JSX.Element {
  const { farmId = "" } = useParams<{ farmId: string }>();
  const { t } = useTranslation("farms");
  const navigate = useNavigate();
  const [farm, setFarm] = useState<FarmDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getFarm(farmId).then(
      (f) => {
        if (!cancelled) setFarm(f);
      },
      (err) => {
        if (!cancelled) {
          setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err));
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [farmId]);

  const handleSubmit = async (values: FarmFormValues): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      await updateFarm(farmId, values);
      navigate(`/farms/${farmId}`);
    } catch (err) {
      setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (!farm) {
    return <p role="status">{t("detail.loading")}</p>;
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold text-brand-800">{t("detail.edit")}</h1>
      <FarmForm
        initial={{
          code: farm.code,
          name: farm.name,
          description: farm.description,
          governorate: farm.governorate,
          district: farm.district,
          nearest_city: farm.nearest_city,
          address_line: farm.address_line,
          farm_type: farm.farm_type,
          ownership_type: farm.ownership_type,
          primary_water_source: farm.primary_water_source,
          established_date: farm.established_date,
          tags: farm.tags,
          boundary: farm.boundary,
        }}
        submitLabel={t("form.submitUpdate")}
        onSubmit={handleSubmit}
        onCancel={() => navigate(`/farms/${farmId}`)}
        busy={busy}
        error={error}
      />
    </div>
  );
}
