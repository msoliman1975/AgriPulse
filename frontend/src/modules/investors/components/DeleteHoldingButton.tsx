import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { deleteHolding } from "@/api/investors";
import { Button } from "@/components/Button";
import { errorText } from "../lib";

interface Props {
  farmId: string;
  holdingId: string;
  code: string;
}

/**
 * Delete for a holding that was never sold. The caller shows it only when
 * the holding has no ownership history; the server checks again.
 */
export function DeleteHoldingButton({ farmId, holdingId, code }: Props): JSX.Element {
  const { t } = useTranslation("investors");
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const remove = useMutation({
    mutationFn: () => deleteHolding(farmId, holdingId),
    onSuccess: async () => {
      setConfirming(false);
      await queryClient.invalidateQueries({ queryKey: ["holdings"] });
      await queryClient.invalidateQueries({ queryKey: ["investments"] });
    },
  });

  if (!confirming) {
    return (
      <Button
        size="sm"
        variant="ghost"
        className="text-ap-crit"
        aria-label={t("holdingsPage.deleteAria", { code })}
        onClick={() => setConfirming(true)}
      >
        {t("holdingsPage.delete")}
      </Button>
    );
  }
  return (
    <span className="flex flex-wrap items-center gap-2" role="group" aria-label={code}>
      <span className="text-sm text-ap-ink">{t("holdingsPage.deleteConfirm", { code })}</span>
      <Button size="sm" onClick={() => remove.mutate()} disabled={remove.isPending}>
        {t("holdingsPage.deleteYes")}
      </Button>
      <Button
        size="sm"
        variant="ghost"
        onClick={() => setConfirming(false)}
        disabled={remove.isPending}
      >
        {t("holdingsPage.deleteNo")}
      </Button>
      {remove.isError ? (
        <span role="alert" className="text-sm text-ap-crit">
          {errorText(remove.error)}
        </span>
      ) : null}
    </span>
  );
}
