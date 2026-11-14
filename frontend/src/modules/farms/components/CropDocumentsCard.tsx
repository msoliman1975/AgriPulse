// "Documents" on the block page (decision D29).
//
// The manuals and guides the block's current crop path inherits: a document
// on `date_palm` shows on a `date_palm.medjool` block. Rendered only for
// holders of `crop_document.download`; each click mints a short-lived link,
// so nothing here holds a URL that could go stale or be shared.

import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
  blockCropDocumentLink,
  formatBytes,
  listBlockCropDocuments,
  openCropDocumentLink,
  type CropDocument,
  type CropDocumentDisposition,
} from "@/api/cropDocuments";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";

export function CropDocumentsCard({ blockId }: { blockId: string }): ReactNode {
  const { t } = useTranslation("farms");
  const query = useQuery({
    queryKey: ["crop-documents", "block", blockId],
    queryFn: () => listBlockCropDocuments(blockId),
  });

  return (
    <Card>
      <h2 className="text-lg font-semibold text-ap-ink">{t("cropDocuments.heading")}</h2>
      {query.isLoading ? (
        <p className="mt-2 text-sm text-ap-muted">{t("cropDocuments.loading")}</p>
      ) : query.isError || !query.data ? (
        <p className="mt-2 text-sm text-ap-crit">{t("cropDocuments.loadFailed")}</p>
      ) : query.data.documents.length === 0 ? (
        <p className="mt-2 text-sm text-ap-muted">
          {query.data.crop_path ? t("cropDocuments.empty") : t("cropDocuments.noCrop")}
        </p>
      ) : (
        <ul className="mt-3 divide-y divide-ap-line">
          {query.data.documents.map((doc) => (
            <DocumentItem key={doc.id} blockId={blockId} doc={doc} />
          ))}
        </ul>
      )}
    </Card>
  );
}

function DocumentItem({ blockId, doc }: { blockId: string; doc: CropDocument }): ReactNode {
  const { t, i18n } = useTranslation("farms");
  const [failed, setFailed] = useState(false);
  const title = i18n.language.startsWith("ar") ? doc.title_ar : doc.title_en;
  const open = (disposition: CropDocumentDisposition): void => {
    setFailed(false);
    openCropDocumentLink(() => blockCropDocumentLink(blockId, doc.id, disposition)).catch(() =>
      setFailed(true),
    );
  };

  return (
    <li className="flex flex-col gap-1 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-ap-ink">{title}</span>
        <span className="text-xs text-ap-muted">
          {t(`cropDocuments.kind.${doc.kind}`)} · {t(`cropDocuments.language.${doc.language}`)} ·{" "}
          {t("cropDocuments.edition", { edition: doc.edition })} · {formatBytes(doc.size_bytes)}
        </span>
        <span className="ms-auto flex gap-1">
          <Button variant="ghost" size="sm" onClick={() => open("inline")}>
            {t("cropDocuments.view")}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => open("attachment")}>
            {t("cropDocuments.download")}
          </Button>
        </span>
      </div>
      <p className="text-xs text-ap-muted">
        {t("cropDocuments.appliesTo", { path: doc.crop_path })}
      </p>
      {failed ? <p className="text-xs text-ap-crit">{t("cropDocuments.linkFailed")}</p> : null}
    </li>
  );
}
