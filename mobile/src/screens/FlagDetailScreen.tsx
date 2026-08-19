import { useEffect, useState, type ReactNode } from "react";

import {
  ApiError,
  commentOnFlag,
  getFieldFlag,
  reopenFieldFlag,
  type FieldFlag,
} from "@/api/client";
import { t, type Lang, type MessageKey } from "@/i18n";

/**
 * A flag the scout raised, and what happened to it.
 *
 * This screen is the feedback loop. Before it, an observation went into a
 * hypertable and the scout never heard another word — which is exactly how
 * people learn that reporting things is pointless. Here they see the reply,
 * the closing reason, and can say "it is still there" by re-opening it.
 */

const REASON_LABEL: Record<string, MessageKey> = {
  actioned: "flag.reason.actioned",
  no_action_needed: "flag.reason.noAction",
  duplicate: "flag.reason.duplicate",
};

export function FlagDetailScreen({
  lang,
  flagId,
  meId,
  onClose,
}: {
  lang: Lang;
  flagId: string;
  meId: string | null;
  onClose: () => void;
}): ReactNode {
  const [flag, setFlag] = useState<FieldFlag | null>(null);
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load(): Promise<void> {
    try {
      setFlag(await getFieldFlag(flagId));
    } catch {
      setError(t(lang, "flag.loadFailed"));
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flagId]);

  async function send(action: "comment" | "reopen"): Promise<void> {
    if (reply.trim() === "") {
      setError(t(lang, "flag.needReply"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const updated =
        action === "comment"
          ? await commentOnFlag(flagId, reply.trim())
          : await reopenFieldFlag(flagId, reply.trim());
      setFlag(updated);
      setReply("");
    } catch (e) {
      setError(e instanceof ApiError && e.message ? e.message : t(lang, "flag.replyFailed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="screen detail overlay">
      <header>
        <button type="button" className="link" onClick={onClose}>
          {t(lang, "work.back")}
        </button>
        {flag ? (
          <span className={`status status-${flag.status}`}>
            {t(lang, flag.status === "open" ? "flag.open" : "flag.closed")}
          </span>
        ) : null}
      </header>

      {error ? <p className="error">{error}</p> : null}
      {!flag ? (
        <p className="empty">{t(lang, "farms.loading")}</p>
      ) : (
        <>
          <h1>{flag.note.split("\n")[0]}</h1>
          <p className="where">
            {flag.block_name} · {t(lang, `flag.sev.${flag.severity}` as MessageKey)}
          </p>

          {/* Unpinned is not closed. Saying so here stops "it vanished from
              the map" being read as "somebody dealt with it". */}
          {flag.status === "open" && !flag.is_pinned ? (
            <p className="hint">{t(lang, "flag.unpinned")}</p>
          ) : null}

          {flag.photos.length > 0 ? (
            <div className="thumbs">
              {flag.photos.map((p) =>
                p.download_url ? <img key={p.id} className="thumb" src={p.download_url} alt="" /> : null,
              )}
            </div>
          ) : null}

          {flag.close_reason ? (
            <div className="why">
              <h2>{t(lang, "flag.outcome")}</h2>
              <p>{t(lang, REASON_LABEL[flag.close_reason])}</p>
            </div>
          ) : null}

          <div className="thread">
            {flag.comments.map((c) => (
              <div key={c.id} className={`msg ${c.author_id === meId ? "mine" : "them"}`}>
                <div className="who">
                  {c.author_name ?? t(lang, "flag.someone")}
                  {c.kind !== "comment" ? ` · ${t(lang, `flag.kind.${c.kind}` as MessageKey)}` : ""}
                </div>
                {c.body}
              </div>
            ))}
          </div>

          <textarea
            value={reply}
            onChange={(e) => setReply(e.target.value)}
            rows={3}
            placeholder={t(lang, "flag.replyPlaceholder")}
          />
          <div className="row">
            <button type="button" disabled={busy} onClick={() => void send("comment")}>
              {t(lang, "flag.reply")}
            </button>
            {/* Re-opening is how a scout says "it is still there" after a
                close they disagree with. It needs the same comment a close
                does, and it puts the pin back on the supervisor's map. */}
            {flag.status === "closed" ? (
              <button type="button" className="link" disabled={busy} onClick={() => void send("reopen")}>
                {t(lang, "flag.reopen")}
              </button>
            ) : null}
          </div>
        </>
      )}
    </div>
  );
}
