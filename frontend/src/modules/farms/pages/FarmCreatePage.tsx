import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { createFarm } from "@/api/farms";
import { isApiError } from "@/api/errors";
import { FarmForm, type FarmFormValues } from "../components/FarmForm";

export function FarmCreatePage(): JSX.Element {
  const { t } = useTranslation("farms");
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (values: FarmFormValues): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      const created = await createFarm(values);
      navigate(`/farms/${created.id}`);
    } catch (err) {
      setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold text-brand-800">{t("list.createButton")}</h1>
      <FarmForm
        submitLabel={t("form.submitCreate")}
        onSubmit={handleSubmit}
        onCancel={() => navigate("/farms")}
        busy={busy}
        error={error}
      />
    </div>
  );
}
