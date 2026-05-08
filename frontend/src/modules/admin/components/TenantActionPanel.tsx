import type { ReactNode } from "react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import type { AdminTenant } from "@/api/adminTenants";
import { isApiError } from "@/api/errors";
import { Modal } from "@/components/Modal";
import {
  useCancelDeleteAdminTenant,
  usePurgeAdminTenant,
  useReactivateAdminTenant,
  useRequestDeleteAdminTenant,
  useRetryProvisioningAdminTenant,
  useSuspendAdminTenant,
} from "@/queries/admin/tenants";

type Action = "suspend" | "requestDelete" | "purge" | null;

interface Props {
  tenant: AdminTenant;
  /** Picker meta — passed in to avoid re-fetching here. */
  purgeGraceDays: number;
}

export function TenantActionPanel({ tenant, purgeGraceDays }: Props): ReactNode {
  const { t } = useTranslation("admin");
  const navigate = useNavigate();

  const suspend = useSuspendAdminTenant(tenant.id);
  const reactivate = useReactivateAdminTenant(tenant.id);
  const requestDelete = useRequestDeleteAdminTenant(tenant.id);
  const cancelDelete = useCancelDeleteAdminTenant(tenant.id);
  const purge = usePurgeAdminTenant(tenant.id);
  const retry = useRetryProvisioningAdminTenant(tenant.id);

  const anyError =
    suspend.error ||
    reactivate.error ||
    requestDelete.error ||
    cancelDelete.error ||
    purge.error ||
    retry.error;

  const [open, setOpen] = useState<Action>(null);

  // Per-status visible actions. Sign-in-blocking already happens via the
  // service layer + auth middleware — these toggles are pure operator UX.
  const canSuspend = tenant.status === "active";
  const canReactivate = tenant.status === "suspended";
  const canRequestDelete =
    tenant.status === "active" || tenant.status === "suspended";
  const canCancelDelete = tenant.status === "pending_delete";
  const canPurge = tenant.status === "pending_delete";
  const canRetry = tenant.status === "pending_provision";

  return (
    <section className="rounded-lg border border-ap-line bg-ap-panel p-4 shadow-card">
      <h2 className="border-b border-ap-line pb-2 text-sm font-semibold text-ap-ink">
        {t("tenants.detail.actions.title")}
      </h2>

      <div className="mt-3 flex flex-wrap gap-2">
        {canSuspend ? (
          <ActionButton
            tone="warning"
            label={t("tenants.detail.actions.suspend")}
            onClick={() => setOpen("suspend")}
          />
        ) : null}
        {canReactivate ? (
          <ActionButton
            tone="primary"
            label={t("tenants.detail.actions.reactivate")}
            pending={reactivate.isPending}
            onClick={() => reactivate.mutate()}
          />
        ) : null}
        {canRequestDelete ? (
          <ActionButton
            tone="danger"
            label={t("tenants.detail.actions.requestDelete")}
            onClick={() => setOpen("requestDelete")}
          />
        ) : null}
        {canCancelDelete ? (
          <ActionButton
            tone="primary"
            label={t("tenants.detail.actions.cancelDelete")}
            pending={cancelDelete.isPending}
            onClick={() => cancelDelete.mutate()}
          />
        ) : null}
        {canPurge ? (
          <ActionButton
            tone="danger"
            label={t("tenants.detail.actions.purge")}
            onClick={() => setOpen("purge")}
          />
        ) : null}
        {canRetry ? (
          <ActionButton
            tone="primary"
            label={t("tenants.detail.actions.retryProvisioning")}
            pending={retry.isPending}
            onClick={() => retry.mutate()}
          />
        ) : null}
      </div>

      {anyError ? (
        <p
          role="alert"
          className="mt-3 rounded-md border border-rose-200 bg-rose-50 p-3 text-xs text-rose-800"
        >
          <span className="font-semibold">
            {t("tenants.detail.errorTitleAction")}
          </span>
          {": "}
          {extractError(anyError)}
        </p>
      ) : null}

      <SuspendModal
        open={open === "suspend"}
        pending={suspend.isPending}
        onClose={() => setOpen(null)}
        onSubmit={(reason) =>
          suspend.mutate(
            { reason },
            { onSuccess: () => setOpen(null) },
          )
        }
      />
      <RequestDeleteModal
        open={open === "requestDelete"}
        pending={requestDelete.isPending}
        graceDays={purgeGraceDays}
        onClose={() => setOpen(null)}
        onSubmit={(reason) =>
          requestDelete.mutate(
            { reason },
            { onSuccess: () => setOpen(null) },
          )
        }
      />
      <PurgeModal
        open={open === "purge"}
        pending={purge.isPending}
        slug={tenant.slug}
        graceDays={purgeGraceDays}
        purgeEligibleAt={tenant.purge_eligible_at}
        onClose={() => setOpen(null)}
        onSubmit={(slug, force) =>
          purge.mutate(
            { slug_confirmation: slug, force },
            {
              onSuccess: () => {
                setOpen(null);
                navigate("/admin/tenants");
              },
            },
          )
        }
      />
    </section>
  );
}

function extractError(err: unknown): string {
  if (isApiError(err)) return err.problem.detail || err.problem.title;
  if (err instanceof Error) return err.message;
  return "Unknown error";
}

interface ActionButtonProps {
  tone: "primary" | "warning" | "danger";
  label: string;
  pending?: boolean;
  onClick: () => void;
}

function ActionButton({ tone, label, pending, onClick }: ActionButtonProps): ReactNode {
  const tones: Record<ActionButtonProps["tone"], string> = {
    primary: "bg-ap-primary text-white hover:bg-ap-primary/90",
    warning: "bg-amber-600 text-white hover:bg-amber-700",
    danger: "bg-rose-600 text-white hover:bg-rose-700",
  };
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={pending}
      className={`rounded-md px-3 py-2 text-sm font-medium disabled:opacity-60 ${tones[tone]}`}
    >
      {label}
    </button>
  );
}

interface SuspendModalProps {
  open: boolean;
  pending: boolean;
  onClose: () => void;
  onSubmit: (reason: string | null) => void;
}

function SuspendModal({ open, pending, onClose, onSubmit }: SuspendModalProps): ReactNode {
  const { t } = useTranslation("admin");
  const [reason, setReason] = useState("");
  return (
    <Modal open={open} onClose={onClose} labelledBy="suspend-modal-title">
      <h2 id="suspend-modal-title" className="text-lg font-semibold text-ap-ink">
        {t("tenants.detail.modals.suspend.title")}
      </h2>
      <p className="mt-2 text-sm text-ap-muted">
        {t("tenants.detail.modals.suspend.body")}
      </p>
      <label className="mt-4 block text-sm">
        <span className="block text-xs font-semibold uppercase tracking-wide text-ap-muted">
          {t("tenants.detail.modals.suspend.reasonLabel")}
        </span>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={3}
          className="mt-1 w-full rounded-md border border-ap-line bg-ap-panel px-3 py-2 text-sm shadow-sm"
        />
      </label>
      <div className="mt-4 flex justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          className="rounded-md border border-ap-line px-3 py-2 text-sm font-medium text-ap-muted hover:bg-ap-line/40"
        >
          {t("tenants.create.actions.cancel")}
        </button>
        <button
          type="button"
          onClick={() => onSubmit(reason.trim() || null)}
          disabled={pending}
          className="rounded-md bg-amber-600 px-3 py-2 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-60"
        >
          {pending
            ? t("tenants.detail.actionPending")
            : t("tenants.detail.modals.suspend.confirm")}
        </button>
      </div>
    </Modal>
  );
}

interface RequestDeleteModalProps {
  open: boolean;
  pending: boolean;
  graceDays: number;
  onClose: () => void;
  onSubmit: (reason: string | null) => void;
}

function RequestDeleteModal({
  open,
  pending,
  graceDays,
  onClose,
  onSubmit,
}: RequestDeleteModalProps): ReactNode {
  const { t } = useTranslation("admin");
  const [reason, setReason] = useState("");
  return (
    <Modal open={open} onClose={onClose} labelledBy="rd-modal-title">
      <h2 id="rd-modal-title" className="text-lg font-semibold text-ap-ink">
        {t("tenants.detail.modals.requestDelete.title")}
      </h2>
      <p className="mt-2 text-sm text-ap-muted">
        {t("tenants.detail.modals.requestDelete.body", { days: graceDays })}
      </p>
      <label className="mt-4 block text-sm">
        <span className="block text-xs font-semibold uppercase tracking-wide text-ap-muted">
          {t("tenants.detail.modals.requestDelete.reasonLabel")}
        </span>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={3}
          className="mt-1 w-full rounded-md border border-ap-line bg-ap-panel px-3 py-2 text-sm shadow-sm"
        />
      </label>
      <div className="mt-4 flex justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          className="rounded-md border border-ap-line px-3 py-2 text-sm font-medium text-ap-muted hover:bg-ap-line/40"
        >
          {t("tenants.create.actions.cancel")}
        </button>
        <button
          type="button"
          onClick={() => onSubmit(reason.trim() || null)}
          disabled={pending}
          className="rounded-md bg-rose-600 px-3 py-2 text-sm font-medium text-white hover:bg-rose-700 disabled:opacity-60"
        >
          {pending
            ? t("tenants.detail.actionPending")
            : t("tenants.detail.modals.requestDelete.confirm")}
        </button>
      </div>
    </Modal>
  );
}

interface PurgeModalProps {
  open: boolean;
  pending: boolean;
  slug: string;
  graceDays: number;
  purgeEligibleAt: string | null;
  onClose: () => void;
  onSubmit: (slugConfirmation: string, force: boolean) => void;
}

function PurgeModal({
  open,
  pending,
  slug,
  graceDays,
  purgeEligibleAt,
  onClose,
  onSubmit,
}: PurgeModalProps): ReactNode {
  const { t } = useTranslation("admin");
  const [confirmation, setConfirmation] = useState("");
  const [force, setForce] = useState(false);

  // Within grace window? If purgeEligibleAt is set and in the future, the
  // backend will reject without `force=true`. Offer the toggle in that case.
  const insideGrace = Boolean(
    purgeEligibleAt && new Date(purgeEligibleAt).getTime() > Date.now(),
  );
  const canSubmit = confirmation === slug && (!insideGrace || force);

  return (
    <Modal open={open} onClose={onClose} labelledBy="purge-modal-title">
      <h2 id="purge-modal-title" className="text-lg font-semibold text-rose-700">
        {t("tenants.detail.modals.purge.title")}
      </h2>
      <p className="mt-2 text-sm text-ap-ink">
        {t("tenants.detail.modals.purge.body")}
      </p>
      <label className="mt-4 block text-sm">
        <span className="block text-xs font-semibold uppercase tracking-wide text-ap-muted">
          {t("tenants.detail.modals.purge.confirmLabel")}{" "}
          <code className="font-mono">{slug}</code>
        </span>
        <input
          type="text"
          value={confirmation}
          onChange={(e) => setConfirmation(e.target.value)}
          autoComplete="off"
          className="mt-1 w-full rounded-md border border-ap-line bg-ap-panel px-3 py-2 font-mono text-sm shadow-sm"
        />
      </label>
      {insideGrace ? (
        <label className="mt-4 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm">
          <input
            type="checkbox"
            checked={force}
            onChange={(e) => setForce(e.target.checked)}
            className="mt-0.5"
          />
          <span>
            <span className="block font-semibold text-amber-900">
              {t("tenants.detail.modals.purge.forceLabel")}
            </span>
            <span className="block text-xs text-amber-800/80">
              {t("tenants.detail.modals.purge.forceWarning", { days: graceDays })}
            </span>
          </span>
        </label>
      ) : null}
      <div className="mt-4 flex justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          className="rounded-md border border-ap-line px-3 py-2 text-sm font-medium text-ap-muted hover:bg-ap-line/40"
        >
          {t("tenants.create.actions.cancel")}
        </button>
        <button
          type="button"
          onClick={() => onSubmit(confirmation, force)}
          disabled={pending || !canSubmit}
          className="rounded-md bg-rose-600 px-3 py-2 text-sm font-medium text-white hover:bg-rose-700 disabled:opacity-60"
        >
          {pending
            ? t("tenants.detail.actionPending")
            : t("tenants.detail.modals.purge.confirm")}
        </button>
      </div>
    </Modal>
  );
}
