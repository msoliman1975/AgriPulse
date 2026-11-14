// The catalogue's Documents tab (decision D29).
//
// Manuals, guides and standards attached to a crop path. A document set on a
// crop shows on every variety and strain below it, so this tab lists what the
// path inherits beside what it sets. Uploading with an existing code makes a
// new edition: the previous one stays as history, it is never deleted.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
  adminCropDocumentLink,
  CROP_DOCUMENT_ACCEPT,
  CROP_DOCUMENT_KINDS,
  CROP_DOCUMENT_LANGUAGES,
  CROP_DOCUMENT_MAX_BYTES,
  formatBytes,
  listAdminCropDocuments,
  openCropDocumentLink,
  updateCropDocument,
  uploadCropDocument,
  type CropDocument,
  type CropDocumentDisposition,
  type CropDocumentKind,
  type CropDocumentLanguage,
} from "@/api/cropDocuments";
import { isApiError } from "@/api/errors";
import { Button } from "@/components/Button";
import { FIELD_CONTROL_CLASS } from "@/components/Field";
import { Pill } from "@/components/Pill";
import { StatusBanner } from "@/components/StatusBanner";

const CODE_RE = /^[a-z0-9][a-z0-9_.-]{0,99}$/;

export function DocumentsPanel({
  cropPath,
  canManage,
}: {
  cropPath: string;
  canManage: boolean;
}): ReactNode {
  const { t } = useTranslation("admin");
  const docs = useQuery({
    queryKey: ["crop-documents", "admin", cropPath],
    queryFn: () => listAdminCropDocuments(cropPath),
  });
  // Seeds the upload form when "New edition" is clicked on a row.
  const [editionOf, setEditionOf] = useState<CropDocument | null>(null);

  if (docs.isLoading) {
    return <p className="text-xs text-ap-muted">{t("crops.loading")}</p>;
  }
  if (docs.isError || !docs.data) {
    return <StatusBanner kind="crit">{t("catalog.documents.loadFailed")}</StatusBanner>;
  }

  const own = docs.data.filter((d) => d.crop_path === cropPath);
  const current = own.filter((d) => d.is_current);
  const history = own.filter((d) => !d.is_current);
  const inherited = docs.data.filter((d) => d.crop_path !== cropPath);

  return (
    <section className="space-y-5">
      <p className="text-[11px] text-ap-muted">{t("catalog.documents.intro")}</p>

      <DocumentList
        heading={t("catalog.documents.here")}
        empty={t("catalog.documents.noneHere")}
        docs={current}
        cropPath={cropPath}
        canManage={canManage}
        onNewEdition={setEditionOf}
      />
      {inherited.length > 0 ? (
        <DocumentList
          heading={t("catalog.documents.inheritedHeading")}
          docs={inherited}
          cropPath={cropPath}
          canManage={false}
          onNewEdition={setEditionOf}
        />
      ) : null}
      {history.length > 0 ? (
        <details className="rounded-md border border-ap-line px-3 py-2">
          <summary className="cursor-pointer text-xs font-medium text-ap-ink">
            {t("catalog.documents.history", { count: history.length })}
          </summary>
          <div className="mt-2">
            <DocumentList
              docs={history}
              cropPath={cropPath}
              canManage={canManage}
              onNewEdition={setEditionOf}
            />
          </div>
        </details>
      ) : null}

      {canManage ? (
        <UploadForm
          // Re-mounted per seed so the form's fields take the new defaults.
          key={editionOf?.id ?? "new"}
          cropPath={cropPath}
          seed={editionOf}
          onDone={() => setEditionOf(null)}
        />
      ) : null}
    </section>
  );
}

function DocumentList({
  heading,
  empty,
  docs,
  cropPath,
  canManage,
  onNewEdition,
}: {
  heading?: string;
  empty?: string;
  docs: CropDocument[];
  cropPath: string;
  canManage: boolean;
  onNewEdition: (doc: CropDocument) => void;
}): ReactNode {
  return (
    <div className="space-y-2">
      {heading ? <h3 className="text-xs font-medium text-ap-ink">{heading}</h3> : null}
      {docs.length === 0 ? (
        empty ? (
          <p className="text-xs text-ap-muted">{empty}</p>
        ) : null
      ) : (
        <ul className="divide-y divide-ap-line rounded-md border border-ap-line">
          {docs.map((doc) => (
            <DocumentRow
              key={doc.id}
              doc={doc}
              cropPath={cropPath}
              canManage={canManage}
              onNewEdition={onNewEdition}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function DocumentRow({
  doc,
  cropPath,
  canManage,
  onNewEdition,
}: {
  doc: CropDocument;
  cropPath: string;
  canManage: boolean;
  onNewEdition: (doc: CropDocument) => void;
}): ReactNode {
  const { t, i18n } = useTranslation("admin");
  const client = useQueryClient();
  const [linkError, setLinkError] = useState(false);
  const retire = useMutation({
    mutationFn: (retired: boolean) => updateCropDocument(doc.id, { retired }),
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: ["crop-documents", "admin", cropPath] }),
  });
  const open = (disposition: CropDocumentDisposition): void => {
    setLinkError(false);
    openCropDocumentLink(() => adminCropDocumentLink(doc.id, disposition)).catch(() =>
      setLinkError(true),
    );
  };
  const title = i18n.language.startsWith("ar") ? doc.title_ar : doc.title_en;

  return (
    <li className="flex flex-col gap-1 px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-ap-ink">{title}</span>
        <Pill kind="neutral">{t(`catalog.documents.kind.${doc.kind}`)}</Pill>
        <Pill kind="info">{t(`catalog.documents.language.${doc.language}`)}</Pill>
        <span className="text-[11px] text-ap-muted">
          {t("catalog.documents.edition", { edition: doc.edition })}
        </span>
        {doc.crop_path !== cropPath ? (
          <Pill kind="neutral">{t("catalog.documents.inherited", { path: doc.crop_path })}</Pill>
        ) : null}
        {doc.superseded_at ? (
          <Pill kind="warn">{t("catalog.documents.superseded")}</Pill>
        ) : doc.retired_at ? (
          <Pill kind="crit">{t("catalog.documents.retired")}</Pill>
        ) : null}
        <span className="ms-auto flex flex-wrap gap-1">
          <Button variant="ghost" size="sm" onClick={() => open("inline")}>
            {t("catalog.documents.view")}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => open("attachment")}>
            {t("catalog.documents.download")}
          </Button>
          {canManage && doc.is_current ? (
            <Button variant="ghost" size="sm" onClick={() => onNewEdition(doc)}>
              {t("catalog.documents.newEdition")}
            </Button>
          ) : null}
          {canManage && !doc.superseded_at ? (
            <Button
              variant="ghost"
              size="sm"
              disabled={retire.isPending}
              onClick={() => retire.mutate(!doc.retired_at)}
            >
              {doc.retired_at ? t("catalog.documents.restore") : t("catalog.documents.retire")}
            </Button>
          ) : null}
        </span>
      </div>
      <p className="text-[11px] text-ap-muted">
        <span className="font-mono">{doc.document_code}</span> · {doc.original_filename} ·{" "}
        {formatBytes(doc.size_bytes)}
      </p>
      {linkError ? (
        <StatusBanner kind="crit">{t("catalog.documents.linkFailed")}</StatusBanner>
      ) : null}
      {retire.isError ? (
        <StatusBanner kind="crit">{t("catalog.documents.saveFailed")}</StatusBanner>
      ) : null}
    </li>
  );
}

function UploadForm({
  cropPath,
  seed,
  onDone,
}: {
  cropPath: string;
  seed: CropDocument | null;
  onDone: () => void;
}): ReactNode {
  const { t } = useTranslation("admin");
  const client = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [code, setCode] = useState(seed?.document_code ?? "");
  const [titleEn, setTitleEn] = useState(seed?.title_en ?? "");
  const [titleAr, setTitleAr] = useState(seed?.title_ar ?? "");
  const [language, setLanguage] = useState<CropDocumentLanguage>(seed?.language ?? "en");
  const [kind, setKind] = useState<CropDocumentKind>(seed?.kind ?? "manual");
  const [edition, setEdition] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: (f: File) =>
      uploadCropDocument({
        crop_path: cropPath,
        document_code: code.trim(),
        title_en: titleEn.trim(),
        title_ar: titleAr.trim(),
        language,
        kind,
        edition: edition.trim(),
        file: f,
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["crop-documents", "admin", cropPath] });
      onDone();
    },
    onError: (err) =>
      setFormError(
        isApiError(err)
          ? (err.problem.detail ?? err.problem.title)
          : t("catalog.documents.uploadFailed"),
      ),
  });

  const submit = (e: FormEvent): void => {
    e.preventDefault();
    setFormError(null);
    if (!file) return;
    if (file.size > CROP_DOCUMENT_MAX_BYTES) {
      setFormError(t("catalog.documents.tooLarge"));
      return;
    }
    if (!CODE_RE.test(code.trim())) {
      setFormError(t("catalog.documents.codeInvalid"));
      return;
    }
    upload.mutate(file);
  };

  const ready = file !== null && code.trim() && titleEn.trim() && titleAr.trim() && edition.trim();

  return (
    <form
      className="space-y-3 rounded-md border border-dashed border-ap-line p-3"
      onSubmit={submit}
      noValidate
      aria-label={t("catalog.documents.uploadHeading")}
    >
      <h3 className="text-xs font-medium text-ap-ink">
        {seed
          ? t("catalog.documents.newEditionHeading", { code: seed.document_code })
          : t("catalog.documents.uploadHeading")}
      </h3>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-[11px] text-ap-muted">
          {t("catalog.documents.code")}
          <input
            className={`${FIELD_CONTROL_CLASS} font-mono`}
            value={code}
            readOnly={seed !== null}
            onChange={(e) => setCode(e.target.value)}
            required
          />
          <span>{t("catalog.documents.codeHint")}</span>
        </label>
        <label className="flex flex-col gap-1 text-[11px] text-ap-muted">
          {t("catalog.documents.editionLabel")}
          <input
            className={FIELD_CONTROL_CLASS}
            value={edition}
            onChange={(e) => setEdition(e.target.value)}
            placeholder="1.7"
            required
          />
        </label>
        <label className="flex flex-col gap-1 text-[11px] text-ap-muted">
          {t("catalog.documents.titleEn")}
          <input
            className={FIELD_CONTROL_CLASS}
            dir="ltr"
            value={titleEn}
            onChange={(e) => setTitleEn(e.target.value)}
            required
          />
        </label>
        <label className="flex flex-col gap-1 text-[11px] text-ap-muted">
          {t("catalog.documents.titleAr")}
          <input
            className={FIELD_CONTROL_CLASS}
            dir="rtl"
            lang="ar"
            value={titleAr}
            onChange={(e) => setTitleAr(e.target.value)}
            required
          />
        </label>
        <label className="flex flex-col gap-1 text-[11px] text-ap-muted">
          {t("catalog.documents.languageLabel")}
          <select
            className={FIELD_CONTROL_CLASS}
            value={language}
            onChange={(e) => setLanguage(e.target.value as CropDocumentLanguage)}
          >
            {CROP_DOCUMENT_LANGUAGES.map((l) => (
              <option key={l} value={l}>
                {t(`catalog.documents.language.${l}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[11px] text-ap-muted">
          {t("catalog.documents.kindLabel")}
          <select
            className={FIELD_CONTROL_CLASS}
            value={kind}
            onChange={(e) => setKind(e.target.value as CropDocumentKind)}
          >
            {CROP_DOCUMENT_KINDS.map((k) => (
              <option key={k} value={k}>
                {t(`catalog.documents.kind.${k}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[11px] text-ap-muted sm:col-span-2">
          {t("catalog.documents.file")}
          <input
            type="file"
            accept={CROP_DOCUMENT_ACCEPT}
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            required
          />
        </label>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" size="sm" disabled={!ready || upload.isPending}>
          {upload.isPending ? t("catalog.documents.uploading") : t("catalog.documents.upload")}
        </Button>
        {seed ? (
          <Button type="button" variant="ghost" size="sm" onClick={onDone}>
            {t("catalog.documents.cancel")}
          </Button>
        ) : null}
      </div>
      {seed ? (
        <p className="text-[11px] text-ap-muted">{t("catalog.documents.supersedeNote")}</p>
      ) : null}
      {formError ? <StatusBanner kind="crit">{formError}</StatusBanner> : null}
    </form>
  );
}
