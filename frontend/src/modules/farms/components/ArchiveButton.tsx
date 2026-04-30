import { useState } from "react";
import { useTranslation } from "react-i18next";

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
      <button
        type="button"
        className="btn btn-ghost text-red-700"
        onClick={() => setConfirming(true)}
        disabled={busy}
      >
        {label}
      </button>
    );
  }
  return (
    <span className="flex items-center gap-2" role="dialog" aria-label={label}>
      <span className="text-sm text-slate-700">{t("actions.confirmArchive")}</span>
      <button
        type="button"
        className="btn btn-primary"
        onClick={() => {
          void onConfirm();
          setConfirming(false);
        }}
        disabled={busy}
      >
        {t("actions.yes")}
      </button>
      <button
        type="button"
        className="btn btn-ghost"
        onClick={() => setConfirming(false)}
        disabled={busy}
      >
        {t("actions.no")}
      </button>
    </span>
  );
}
