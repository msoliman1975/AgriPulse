import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { RbacCapability } from "@/api/rbacMatrix";
import { Card } from "@/components/Card";
import { Modal } from "@/components/Modal";
import { Pill } from "@/components/Pill";
import { StatusBanner } from "@/components/StatusBanner";

/** What the admin is about to do. `null` granted means "reset to default". */
export interface PendingRbacChange {
  role: string;
  capability: RbacCapability;
  /** Effective answer right now. */
  from: boolean;
  /** Effective answer afterwards. */
  to: boolean;
  /** `null` resets; a boolean writes an override. */
  granted: boolean | null;
}

interface Props {
  change: PendingRbacChange | null;
  pending: boolean;
  /** Upper bound before every API pod agrees. Served, not hardcoded. */
  propagationSeconds: number;
  error?: string | null;
  onClose: () => void;
  onConfirm: (note: string) => void;
}

/**
 * Confirmation for a single permission change.
 *
 * Deliberately a confirm step rather than an optimistic toggle: this edits
 * authorization for every user holding the role, across every tenant, and the
 * page that would undo it is the same one. The dialog states the before/after
 * explicitly instead of relying on the admin having read the row correctly.
 */
export function RbacOverrideDialog({
  change,
  pending,
  propagationSeconds,
  error,
  onClose,
  onConfirm,
}: Props): ReactNode {
  const { t } = useTranslation("admin");
  const [note, setNote] = useState("");

  // Clear the note per change, not per close: reopening on a different row
  // must not inherit the last justification.
  useEffect(() => {
    setNote("");
  }, [change?.role, change?.capability.name, change?.granted]);

  if (!change) return null;

  const isReset = change.granted === null;
  const answer = (value: boolean) => (value ? t("roles.grantedYes") : t("roles.grantedNo"));

  return (
    <Modal open onClose={onClose} labelledBy="rbac-override-title">
      <h2 id="rbac-override-title" className="text-lg font-semibold text-ap-ink">
        {isReset
          ? t("roles.edit.resetTitle")
          : change.to
            ? t("roles.edit.grantTitle")
            : t("roles.edit.revokeTitle")}
      </h2>

      <Card className="mt-3">
        <div className="text-sm font-semibold text-ap-ink">{change.role}</div>
        <code className="font-mono text-xs text-ap-ink">{change.capability.name}</code>
        <div className="mt-1 text-[11px] text-ap-muted">{change.capability.description}</div>
        <div className="mt-2 flex items-center gap-2 text-sm">
          <span className="text-ap-muted">{answer(change.from)}</span>
          <span aria-hidden="true" className="text-ap-muted">
            →
          </span>
          <span className="font-semibold text-ap-ink">{answer(change.to)}</span>
        </div>
      </Card>

      {/* A stub capability is grantable but inert. Saying so here is the whole
          point — otherwise an admin believes they just switched something on. */}
      {change.capability.status === "stub" && change.to ? (
        <div className="mt-3">
          <StatusBanner kind="warn" detail={t("roles.edit.stubDetail")}>
            <Pill kind="warn">{t("roles.statusStub")}</Pill> {t("roles.edit.stubWarning")}
          </StatusBanner>
        </div>
      ) : null}

      <label className="mt-4 block text-sm">
        <span className="block text-xs font-semibold uppercase tracking-wide text-ap-muted">
          {t("roles.edit.noteLabel")}
        </span>
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={2}
          maxLength={500}
          placeholder={t("roles.edit.notePlaceholder")}
          className="mt-1 w-full rounded-md border border-ap-line bg-ap-panel px-3 py-2 text-sm shadow-sm"
        />
      </label>

      <div className="mt-3">
        <StatusBanner kind="info">
          {t("roles.edit.propagation", { seconds: propagationSeconds })}
        </StatusBanner>
      </div>

      {error ? (
        <div className="mt-3">
          <StatusBanner kind="crit">{error}</StatusBanner>
        </div>
      ) : null}

      <div className="mt-4 flex justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          className="rounded-md border border-ap-line px-3 py-2 text-sm font-medium text-ap-muted hover:bg-ap-line/40"
        >
          {t("roles.edit.cancel")}
        </button>
        <button
          type="button"
          onClick={() => onConfirm(note.trim())}
          disabled={pending}
          className="rounded-md bg-ap-primary px-3 py-2 text-sm font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
        >
          {pending ? t("roles.edit.saving") : t("roles.edit.confirm")}
        </button>
      </div>
    </Modal>
  );
}
