import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/Button";

interface Props {
  label: string;
  busy?: boolean;
  onConfirm: () => Promise<void> | void;
}

export function ArchiveButton({ label, busy, onConfirm }: Props): JSX.Element {
  const { t } = useTranslation("farms");
  const [confirming, setConfirming] = useState(false);

  if (!confirming) {
    return (
      <Button
        variant="ghost"
        className="text-ap-crit"
        onClick={() => setConfirming(true)}
        disabled={busy}
      >
        {label}
      </Button>
    );
  }
  return (
    <span className="flex items-center gap-2" role="dialog" aria-label={label}>
      <span className="text-sm text-ap-ink">{t("actions.confirmArchive")}</span>
      <Button
        onClick={() => {
          void onConfirm();
          setConfirming(false);
        }}
        disabled={busy}
      >
        {t("actions.yes")}
      </Button>
      <Button variant="ghost" onClick={() => setConfirming(false)} disabled={busy}>
        {t("actions.no")}
      </Button>
    </span>
  );
}
