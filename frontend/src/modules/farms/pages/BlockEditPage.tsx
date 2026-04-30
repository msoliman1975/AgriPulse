import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { getBlock, updateBlock, type BlockDetail } from "@/api/blocks";
import { isApiError } from "@/api/errors";
import { BlockForm, type BlockFormValues } from "../components/BlockForm";

export function BlockEditPage(): JSX.Element {
  const { farmId = "", blockId = "" } = useParams<{ farmId: string; blockId: string }>();
  const { t } = useTranslation("farms");
  const navigate = useNavigate();
  const [block, setBlock] = useState<BlockDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getBlock(blockId).then(
      (b) => {
        if (!cancelled) setBlock(b);
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
  }, [blockId]);

  const handleSubmit = async (values: BlockFormValues): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      await updateBlock(blockId, values);
      navigate(`/farms/${farmId}/blocks/${blockId}`);
    } catch (err) {
      setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (!block) {
    return <p role="status">{t("detail.loading")}</p>;
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold text-brand-800">{t("block.edit")}</h1>
      <BlockForm
        initial={{
          code: block.code,
          name: block.name,
          irrigation_system: block.irrigation_system,
          irrigation_source: block.irrigation_source,
          soil_texture: block.soil_texture,
          salinity_class: block.salinity_class,
          soil_ph: block.soil_ph,
          notes: block.notes,
        }}
        initialBoundary={block.boundary}
        submitLabel={t("form.submitBlockUpdate")}
        onSubmit={handleSubmit}
        onCancel={() => navigate(`/farms/${farmId}/blocks/${blockId}`)}
        busy={busy}
        error={error}
      />
    </div>
  );
}
