import type { ReactNode } from "react";

import { t, type Lang } from "@/i18n";

export function UpdateRequiredScreen({ lang, url }: { lang: Lang; url: string | null }): ReactNode {
  return (
    <main className="signin">
      <div className="signin-body">
        <h1>{t(lang, "update.title")}</h1>
        <p>{t(lang, "update.body")}</p>
        {url ? (
          <a className="btn btn-primary btn-block" href={url} target="_blank" rel="noreferrer">
            {t(lang, "update.download")}
          </a>
        ) : (
          <p className="muted">{t(lang, "update.noLink")}</p>
        )}
      </div>
    </main>
  );
}
