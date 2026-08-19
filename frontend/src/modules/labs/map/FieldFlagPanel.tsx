import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow, parseISO } from "date-fns";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
  closeFlag,
  commentOnFlag,
  getFieldFlag,
  reopenFlag,
  type FlagCloseReason,
} from "@/api/fieldFlags";
import { AnchoredPopup } from "@/components/AnchoredPopup";
import { useDateLocale } from "@/hooks/useDateLocale";

const CLOSE_REASONS: FlagCloseReason[] = ["actioned", "no_action_needed", "duplicate"];

/**
 * One field flag, and everything a supervisor can do about it.
 *
 * Closing asks for a reason **and** a comment, and the button stays disabled
 * until both are there. A flag closed silently reads to the scout as being
 * ignored, and that is how people stop flagging things — the comment is the
 * entire feedback loop, not paperwork around it.
 *
 * Chrome and click-anchoring come from the shared AnchoredPopup, so this reads
 * as a sibling of the grid-cell and signal-observation popups rather than a
 * third kind of card on the same map.
 */
export function FieldFlagPanel({
  flagId,
  x,
  y,
  onClose,
  onChanged,
}: {
  flagId: string;
  x: number | null;
  y: number | null;
  onClose: () => void;
  onChanged?: () => void;
}): ReactNode {
  const { t } = useTranslation("farmConsole");
  const dateLocale = useDateLocale();
  const qc = useQueryClient();

  const [reply, setReply] = useState("");
  const [closing, setClosing] = useState(false);
  const [reason, setReason] = useState<FlagCloseReason>("actioned");

  const flagQ = useQuery({
    queryKey: ["fieldFlag", flagId],
    queryFn: () => getFieldFlag(flagId),
  });

  function afterWrite(): void {
    setReply("");
    setClosing(false);
    void qc.invalidateQueries({ queryKey: ["fieldFlag", flagId] });
    // The pin's fill depends on status, so the layer has to re-read too.
    void qc.invalidateQueries({ queryKey: ["labs/mapnext/fieldFlags"] });
    onChanged?.();
  }

  const commentM = useMutation({
    mutationFn: () => commentOnFlag(flagId, reply.trim()),
    onSuccess: afterWrite,
  });
  const closeM = useMutation({
    mutationFn: () => closeFlag(flagId, { reason, comment: reply.trim() }),
    onSuccess: afterWrite,
  });
  const reopenM = useMutation({
    mutationFn: () => reopenFlag(flagId, reply.trim()),
    onSuccess: afterWrite,
  });

  const flag = flagQ.data;
  const busy = commentM.isPending || closeM.isPending || reopenM.isPending;
  const hasReply = reply.trim().length > 0;

  return (
    <AnchoredPopup x={x} y={y} title={t("flags.title")} onClose={onClose}>
      {flagQ.isLoading || !flag ? (
        <p className="text-ap-muted">{t("flags.loading")}</p>
      ) : (
        <div className="flex max-h-[26rem] flex-col gap-2 overflow-y-auto">
          <div className="flex items-center gap-2">
            <span
              className={
                flag.severity === "critical"
                  ? "rounded px-1.5 py-0.5 text-[10px] font-medium uppercase text-ap-crit ring-1 ring-ap-crit"
                  : flag.severity === "warning"
                    ? "rounded px-1.5 py-0.5 text-[10px] font-medium uppercase text-ap-warn ring-1 ring-ap-warn"
                    : "rounded px-1.5 py-0.5 text-[10px] font-medium uppercase text-ap-primary ring-1 ring-ap-primary"
              }
            >
              {t(`flags.severity.${flag.severity}`)}
            </span>
            <span className="text-[11px] text-ap-muted">
              {flag.status === "open" ? t("flags.open") : t("flags.closed")}
            </span>
            {/* Unpinned is NOT closed. Saying so on the card stops the map's
                silence being read as "this went away". */}
            {!flag.is_pinned ? (
              <span className="text-[11px] text-ap-muted">· {t("flags.unpinned")}</span>
            ) : null}
          </div>

          <p className="whitespace-pre-wrap text-[13px] text-ap-ink">{flag.note}</p>
          <p className="text-[11px] text-ap-muted">
            {flag.block_name} · {flag.raised_by_name ?? t("flags.someone")} ·{" "}
            {formatDistanceToNow(parseISO(flag.created_at), { addSuffix: true, locale: dateLocale })}
            {flag.point ? null : ` · ${t("flags.noPosition")}`}
          </p>

          {flag.photos.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {flag.photos.map((p) =>
                p.download_url ? (
                  <a key={p.id} href={p.download_url} target="_blank" rel="noreferrer">
                    <img
                      src={p.download_url}
                      alt=""
                      className="h-14 w-14 rounded border border-ap-line object-cover"
                    />
                  </a>
                ) : null,
              )}
            </div>
          ) : null}

          {flag.status === "closed" && flag.close_reason ? (
            <p className="rounded bg-ap-primary-soft px-2 py-1 text-[11px] text-ap-ink">
              {t(`flags.reason.${flag.close_reason}`)} — {flag.closed_by_name ?? ""}
            </p>
          ) : null}

          <div className="flex flex-col gap-1.5 border-t border-ap-line pt-2">
            {flag.comments.map((c) => (
              <div key={c.id} className="text-[12px]">
                <span className="text-[10px] text-ap-muted">
                  {c.author_name ?? t("flags.someone")} ·{" "}
                  {formatDistanceToNow(parseISO(c.created_at), {
                    addSuffix: true,
                    locale: dateLocale,
                  })}
                  {c.kind !== "comment" ? ` · ${t(`flags.kind.${c.kind}`)}` : ""}
                </span>
                <p className="whitespace-pre-wrap text-ap-ink">{c.body}</p>
              </div>
            ))}
          </div>

          <textarea
            value={reply}
            onChange={(e) => setReply(e.target.value)}
            rows={2}
            placeholder={t("flags.replyPlaceholder")}
            className="w-full rounded border border-ap-line bg-ap-panel px-2 py-1 text-[12px]"
          />

          {closing ? (
            <div className="flex flex-col gap-1.5">
              <span className="text-[10px] uppercase text-ap-muted">{t("flags.whyClosing")}</span>
              <div className="flex flex-wrap gap-1">
                {CLOSE_REASONS.map((r) => (
                  <button
                    key={r}
                    type="button"
                    onClick={() => setReason(r)}
                    className={`rounded-full border px-2 py-0.5 text-[11px] ${
                      r === reason
                        ? "border-ap-primary bg-ap-primary text-white"
                        : "border-ap-line text-ap-ink"
                    }`}
                  >
                    {t(`flags.reason.${r}`)}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          <div className="flex flex-wrap gap-1.5">
            <button
              type="button"
              disabled={busy || !hasReply}
              onClick={() => commentM.mutate()}
              className="rounded border border-ap-line px-2 py-1 text-[12px] disabled:opacity-50"
            >
              {t("flags.reply")}
            </button>
            {flag.status === "open" ? (
              closing ? (
                <button
                  type="button"
                  // Both required, and the control says so by staying off
                  // rather than by failing after the click.
                  disabled={busy || !hasReply}
                  onClick={() => closeM.mutate()}
                  className="rounded bg-ap-primary px-2 py-1 text-[12px] text-white disabled:opacity-50"
                >
                  {t("flags.confirmClose")}
                </button>
              ) : (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => setClosing(true)}
                  className="rounded bg-ap-primary px-2 py-1 text-[12px] text-white disabled:opacity-50"
                >
                  {t("flags.close")}
                </button>
              )
            ) : (
              <button
                type="button"
                disabled={busy || !hasReply}
                onClick={() => reopenM.mutate()}
                className="rounded border border-ap-warn px-2 py-1 text-[12px] text-ap-warn disabled:opacity-50"
              >
                {t("flags.reopen")}
              </button>
            )}
          </div>
          {!hasReply ? (
            <p className="text-[10px] text-ap-muted">{t("flags.commentRequired")}</p>
          ) : null}
        </div>
      )}
    </AnchoredPopup>
  );
}
