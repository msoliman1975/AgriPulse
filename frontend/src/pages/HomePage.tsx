import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { listFarms } from "@/api/farms";
import { Card } from "@/components/Card";
import { ExternalLinkButton } from "@/components/ExternalLinkButton";
import { LinkButton } from "@/components/LinkButton";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { docsUrl, type DocsPage } from "@/lib/docs";
import { useCapability } from "@/rbac/useCapability";

// The six setup steps, in the order the documentation site teaches them.
// `key` indexes home.setup.steps.* in common.json; `page` indexes the docs
// guide that covers the step.
const SETUP_STEPS: { key: string; page: DocsPage }[] = [
  { key: "createFarm", page: "guideCreateFarm" },
  { key: "addBlocks", page: "guideAddBlocks" },
  { key: "gridCellSize", page: "guideGridCellSize" },
  { key: "imageryWeather", page: "guideImageryWeather" },
  { key: "attachPeople", page: "guideAttachPeople" },
  { key: "checkArrived", page: "guideCheckArrived" },
];

// The eight processes the platform is organised around. Same list as the
// documentation site's landing tiles — keep the two in step.
const CAPABILITIES: { key: string; page: DocsPage }[] = [
  { key: "mapTheFarm", page: "processMapTheFarm" },
  { key: "planTheSeason", page: "processPlanTheSeason" },
  { key: "connectTheData", page: "processConnectTheData" },
  { key: "readTheField", page: "processReadTheField" },
  { key: "authorTheAgronomy", page: "processAuthorTheAgronomy" },
  { key: "runTheFieldTeam", page: "processRunTheFieldTeam" },
  { key: "closeTheLoop", page: "processCloseTheLoop" },
  { key: "operateThePlatform", page: "processOperateThePlatform" },
];

const LEARN_LINKS: { key: string; page: DocsPage }[] = [
  { key: "docsHome", page: "home" },
  { key: "concepts", page: "concepts" },
  { key: "kb", page: "knowledgeBase" },
  { key: "support", page: "support" },
];

export function HomePage(): ReactNode {
  const { t } = useTranslation("common");
  const canCreateFarm = useCapability("farm.create");
  // Redirect to /insights/<first-farm-id> when the user has at least one
  // farm — that's the AgriPulse landing convention. Users with no farms get
  // the onboarding page below: what the platform does, how to set a farm up,
  // and where the written guides are.
  const { data, isLoading, isError } = useQuery({
    queryKey: ["farms", "list", "home-redirect"] as const,
    queryFn: () => listFarms(),
    staleTime: 60_000,
  });
  if (isLoading) {
    return (
      <Page width="standard">
        <Card className="max-w-2xl" role="status">
          <p className="text-ap-muted">{t("actions.loading")}</p>
        </Card>
      </Page>
    );
  }
  if (!isError && data && data.items.length > 0) {
    return <Navigate to={`/insights/${data.items[0].id}`} replace />;
  }
  // Arabic docs pages do not exist yet, so the links go to English pages.
  // Say so rather than letting the reader discover it by clicking.
  const englishOnlyNote = t("home.docsEnglishOnly");
  return (
    <Page>
      <PageHeader
        title={canCreateFarm ? t("home.noFarmsTitle") : t("home.welcome")}
        subtitle={canCreateFarm ? t("home.noFarmsBody") : t("home.comingSoon")}
        actions={
          <>
            {canCreateFarm ? (
              <LinkButton to="/labs/map?create=farm">{t("home.createFirstFarm")}</LinkButton>
            ) : null}
            <ExternalLinkButton href={docsUrl("guideCreateFarm")}>
              {t("home.readTheGuide")}
            </ExternalLinkButton>
          </>
        }
      />

      {canCreateFarm ? (
        <Card title={t("home.setup.title")}>
          <p className="text-sm text-ap-muted">{t("home.setup.note")}</p>
          <ol className="mt-3 grid gap-2 sm:grid-cols-2">
            {SETUP_STEPS.map((step, index) => (
              <li
                key={step.key}
                className="flex gap-3 rounded-md border border-ap-line px-3 py-2.5"
              >
                <span
                  aria-hidden="true"
                  className="mt-0.5 flex h-6 w-6 flex-none items-center justify-center rounded-full bg-ap-line/60 text-xs font-semibold text-ap-ink"
                >
                  {index + 1}
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-ap-ink">
                    {t(`home.setup.steps.${step.key}.title`)}
                  </p>
                  <p className="mt-0.5 text-sm text-ap-muted">
                    {t(`home.setup.steps.${step.key}.body`)}
                  </p>
                  <a
                    href={docsUrl(step.page)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-1 inline-block text-sm font-medium text-ap-primary hover:underline"
                  >
                    {t("home.setup.guideLink")}
                  </a>
                </div>
              </li>
            ))}
          </ol>
        </Card>
      ) : null}

      <Card title={t("home.capabilities.title")}>
        <p className="text-sm text-ap-muted">{t("home.capabilities.body")}</p>
        <ul className="mt-3 grid gap-2 sm:grid-cols-2">
          {CAPABILITIES.map((item) => (
            <li key={item.key}>
              <a
                href={docsUrl(item.page)}
                target="_blank"
                rel="noopener noreferrer"
                className="block h-full rounded-md border border-ap-line px-3 py-2.5 hover:bg-ap-line/30"
              >
                <span className="block text-sm font-medium text-ap-ink">
                  {t(`home.capabilities.items.${item.key}.title`)}
                </span>
                <span className="mt-0.5 block text-sm text-ap-muted">
                  {t(`home.capabilities.items.${item.key}.body`)}
                </span>
              </a>
            </li>
          ))}
        </ul>
      </Card>

      <Card title={t("home.learn.title")}>
        <div className="flex flex-wrap gap-2">
          {LEARN_LINKS.map((link) => (
            <ExternalLinkButton key={link.key} href={docsUrl(link.page)} size="sm">
              {t(`home.learn.${link.key}`)}
            </ExternalLinkButton>
          ))}
        </div>
        {englishOnlyNote ? <p className="mt-2 text-xs text-ap-muted">{englishOnlyNote}</p> : null}
      </Card>
    </Page>
  );
}
