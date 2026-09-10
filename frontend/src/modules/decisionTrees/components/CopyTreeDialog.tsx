// Copy a platform tree into this tenant.
//
// The dialog shows the derived code before confirming, because the copy
// cannot keep the original's: a tenant code that collides with a platform one
// makes every lookup by code ambiguous, and the API refuses it. The author can
// change it here.
//
// It also says the two things the copy does not do, which are the parts people
// discover months later: open recommendations from the original stay open
// under the original's code, and the copy never moves when the platform
// republishes the original.

import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Modal } from "@/components/Modal";
import { useCopyDecisionTree } from "@/queries/decisionTrees";

interface CopyTreeDialogProps {
  code: string;
  /** Where to send the author once the copy exists. */
  onCopied: (newCode: string) => void;
  onClose: () => void;
}

export function CopyTreeDialog({ code, onCopied, onClose }: CopyTreeDialogProps): ReactNode {
  const { t } = useTranslation("decisionTrees");
  const copy = useCopyDecisionTree();
  // Empty means "take the derived code". The API derives it from the tenant's
  // slug, which the browser does not have, so the field starts blank with the
  // rule stated rather than guessing the value and showing it wrong.
  const [newCode, setNewCode] = useState("");
  const [disableOriginal, setDisableOriginal] = useState(true);

  const submit = (): void => {
    copy.mutate(
      {
        code,
        payload: {
          new_code: newCode.trim() === "" ? null : newCode.trim(),
          disable_original: disableOriginal,
        },
      },
      { onSuccess: (tree) => onCopied(tree.code) },
    );
  };

  return (
    <Modal open onClose={onClose} labelledBy="dt-copy-title" className="max-w-md">
      <h2 id="dt-copy-title" className="text-base font-semibold text-ap-ink">
        {t("copy.title")}
      </h2>
      <p className="mt-2 text-sm text-ap-ink">{t("copy.body", { code })}</p>

      <label className="mt-4 block text-xs font-medium text-ap-ink" htmlFor="dt-copy-code">
        {t("copy.codeLabel")}
      </label>
      <input
        id="dt-copy-code"
        value={newCode}
        onChange={(e) => setNewCode(e.target.value)}
        placeholder={t("copy.codePlaceholder")}
        className="mt-1 w-full rounded-md border border-ap-line bg-ap-surface px-2 py-1.5 font-mono text-xs text-ap-ink"
      />
      <p className="mt-1 text-[11px] text-ap-muted">{t("copy.codeHint")}</p>

      <label className="mt-4 flex items-start gap-2 text-sm text-ap-ink">
        <input
          type="checkbox"
          checked={disableOriginal}
          onChange={(e) => setDisableOriginal(e.target.checked)}
          className="mt-0.5"
        />
        <span>
          {t("copy.disableOriginal")}
          <span className="mt-0.5 block text-[11px] text-ap-muted">
            {t("copy.disableOriginalHint")}
          </span>
        </span>
      </label>

      <p className="mt-4 rounded-md border border-ap-line bg-ap-line/20 p-2 text-[11px] leading-snug text-ap-muted">
        {t("copy.frozenNote")}
      </p>

      {copy.isError ? (
        <p className="mt-2 text-xs text-ap-crit">{copy.error?.message || t("copy.failed")}</p>
      ) : null}

      <div className="mt-4 flex justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          className="rounded-md px-3 py-1.5 text-sm text-ap-muted"
        >
          {t("copy.cancel")}
        </button>
        <button
          type="button"
          onClick={submit}
          disabled={copy.isPending}
          className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
        >
          {copy.isPending ? t("copy.copying") : t("copy.confirm")}
        </button>
      </div>
    </Modal>
  );
}
