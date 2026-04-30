import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { createBlock } from "@/api/blocks";
import { isApiError } from "@/api/errors";
import { BlockForm, type BlockFormValues } from "../components/BlockForm";

export function BlockCreatePage(): JSX.Element {
  const { farmId = "" } = useParams<{ farmId: string }>();
  const { t } = useTranslation("farms");
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (values: BlockFormValues): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      const block = await createBlock(farmId, values);
      navigate(`/farms/${farmId}/blocks/${block.id}`);
    } catch (err) {
      setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold text-brand-800">{t("detail.addBlock")}</h1>
      <BlockForm
        submitLabel={t("form.submitBlockCreate")}
        onSubmit={handleSubmit}
        onCancel={() => navigate(`/farms/${farmId}`)}
        busy={busy}
        error={error}
      />
    </div>
  );
}
