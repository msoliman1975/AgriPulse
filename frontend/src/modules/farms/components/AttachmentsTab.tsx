import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
  deleteBlockAttachment,
  deleteFarmAttachment,
  finalizeBlockAttachment,
  finalizeFarmAttachment,
  initBlockAttachment,
  initFarmAttachment,
  listBlockAttachments,
  listFarmAttachments,
  type Attachment,
  type AttachmentKind,
} from "@/api/attachments";
import { isApiError } from "@/api/errors";
import { uploadToPresignedUrl } from "@/lib/upload";
import { useCapability } from "@/rbac/useCapability";
import { ArchiveButton } from "./ArchiveButton";

const ATTACHMENT_KINDS: AttachmentKind[] = ["photo", "deed", "soil_test_report", "map", "other"];

const MAX_BYTES = 25 * 1024 * 1024;

interface Props {
  ownerKind: "farm" | "block";
  ownerId: string;
  farmId: string;
}

export function AttachmentsTab({ ownerKind, ownerId, farmId }: Props): ReactNode {
  const { t, i18n } = useTranslation("farms");
  const canRead = useCapability(`${ownerKind}.attachment.read`, { farmId });
  const canWrite = useCapability(`${ownerKind}.attachment.write`, { farmId });

  const [items, setItems] = useState<Attachment[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState<AttachmentKind>("photo");
  const [caption, setCaption] = useState("");

  const api = useMemo(
    () =>
      ownerKind === "farm"
        ? {
            init: initFarmAttachment,
            finalize: finalizeFarmAttachment,
            list: listFarmAttachments,
            del: deleteFarmAttachment,
          }
        : {
            init: initBlockAttachment,
            finalize: finalizeBlockAttachment,
            list: listBlockAttachments,
            del: deleteBlockAttachment,
          },
    [ownerKind],
  );

  useEffect(() => {
    if (!canRead) return;
    let cancelled = false;
    setError(null);
    api
      .list(ownerId)
      .then((data) => {
        if (!cancelled) setItems(data);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [api, ownerId, canRead]);

  if (!canRead) return null;

  const handleSubmit = async (event: FormEvent): Promise<void> => {
    event.preventDefault();
    setError(null);
    if (!file) {
      setError(t("attachments.errors.fileRequired"));
      return;
    }
    if (file.size > MAX_BYTES) {
      setError(t("attachments.errors.tooLarge"));
      return;
    }
    setBusy(true);
    try {
      const init = await api.init(ownerId, {
        kind,
        original_filename: file.name,
        content_type: file.type || "application/octet-stream",
        size_bytes: file.size,
      });
      await uploadToPresignedUrl(file, init.upload_url, init.upload_headers);
      const created = await api.finalize(ownerId, {
        attachment_id: init.attachment_id,
        s3_key: init.s3_key,
        kind,
        original_filename: file.name,
        content_type: file.type || "application/octet-stream",
        size_bytes: file.size,
        caption: caption || null,
      });
      setItems((prev) => [created, ...(prev ?? [])]);
      setFile(null);
      setCaption("");
      // Reset the <input type="file"> via its DOM node — controlled file
      // inputs aren't a thing in React, so we clear by id.
      const input = document.getElementById("attachment-file-input") as HTMLInputElement | null;
      if (input) input.value = "";
    } catch (err) {
      setError(
        isApiError(err)
          ? (err.problem.detail ?? err.problem.title)
          : err instanceof Error
            ? `${t("attachments.errors.uploadFailed")} ${err.message}`
            : t("attachments.errors.uploadFailed"),
      );
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (attachmentId: string): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      await api.del(attachmentId);
      setItems((prev) => (prev ?? []).filter((a) => a.id !== attachmentId));
    } catch (err) {
      setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <h2 className="text-lg font-semibold text-slate-800">{t("attachments.heading")}</h2>

      {error ? (
        <p role="alert" className="mt-2 text-sm text-red-700">
          {error}
        </p>
      ) : null}

      {items === null ? (
        <p role="status" className="mt-2 text-sm text-slate-600">
          {t("detail.loading")}
        </p>
      ) : items.length === 0 ? (
        <p className="mt-2 text-sm text-slate-600">{t("attachments.empty")}</p>
      ) : (
        <ul className="mt-3 space-y-3">
          {items.map((a) => (
            <li
              key={a.id}
              className="flex items-start justify-between gap-3 border-t border-slate-100 pt-3 first:border-0 first:pt-0"
            >
              <div className="flex items-start gap-3">
                {a.content_type.startsWith("image/") ? (
                  <img
                    src={a.download_url}
                    alt={a.caption ?? a.original_filename}
                    className="h-16 w-16 flex-shrink-0 rounded object-cover"
                  />
                ) : null}
                <div className="text-sm">
                  <a
                    href={a.download_url}
                    target="_blank"
                    rel="noreferrer"
                    className="font-medium text-brand-700 underline"
                  >
                    {a.original_filename}
                  </a>
                  <p className="text-xs text-slate-500">
                    {t(`attachments.kind.${a.kind}`)} · {formatSize(a.size_bytes, t)}
                  </p>
                  {a.caption ? <p className="mt-1 text-xs text-slate-700">{a.caption}</p> : null}
                  <p className="text-xs text-slate-400">
                    {new Date(a.created_at).toLocaleString(i18n.language)}
                  </p>
                </div>
              </div>
              {canWrite ? (
                <ArchiveButton
                  label={t("attachments.delete")}
                  busy={busy}
                  onConfirm={() => handleDelete(a.id)}
                />
              ) : null}
            </li>
          ))}
        </ul>
      )}

      {canWrite ? (
        <form onSubmit={handleSubmit} className="mt-6 space-y-3 border-t border-slate-100 pt-4">
          <h3 className="text-sm font-semibold text-slate-700">{t("attachments.uploadHeading")}</h3>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className="label" htmlFor="attachment-file-input">
                {t("attachments.fileLabel")}
              </label>
              <input
                id="attachment-file-input"
                type="file"
                className="input"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                required
              />
            </div>
            <div>
              <label className="label" htmlFor="attachment-kind">
                {t("attachments.kindLabel")}
              </label>
              <select
                id="attachment-kind"
                className="input"
                value={kind}
                onChange={(e) => setKind(e.target.value as AttachmentKind)}
              >
                {ATTACHMENT_KINDS.map((k) => (
                  <option key={k} value={k}>
                    {t(`attachments.kind.${k}`)}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div>
            <label className="label" htmlFor="attachment-caption">
              {t("attachments.captionLabel")}
            </label>
            <input
              id="attachment-caption"
              className="input"
              value={caption}
              onChange={(e) => setCaption(e.target.value)}
            />
          </div>
          <button type="submit" className="btn btn-primary" disabled={busy || !file}>
            {busy ? t("attachments.uploading") : t("attachments.submit")}
          </button>
        </form>
      ) : null}
    </div>
  );
}

function formatSize(
  bytes: number,
  t: (key: string, opts: Record<string, unknown>) => string,
): string {
  if (bytes < 1024 * 1024) {
    return t("attachments.size.kb", { value: (bytes / 1024).toFixed(1) });
  }
  return t("attachments.size.mb", { value: (bytes / (1024 * 1024)).toFixed(1) });
}
