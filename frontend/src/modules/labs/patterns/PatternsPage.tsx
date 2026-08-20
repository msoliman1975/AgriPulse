import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Breadcrumb } from "@/components/Breadcrumb";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { DataTable, RowActions, type Column } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { Field, FIELD_CONTROL_CLASS } from "@/components/Field";
import { FormFooter } from "@/components/FormFooter";
import { KPICard } from "@/components/KPICard";
import { KPIRow } from "@/components/KPIRow";
import { LinkButton } from "@/components/LinkButton";
import { Page, type PageWidth } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { Pill } from "@/components/Pill";
import { RowList } from "@/components/RowList";
import { SegmentedControl } from "@/components/SegmentedControl";
import { StatusBanner } from "@/components/StatusBanner";
import { Toolbar, ToolbarChips, type FilterAxis, type FilterValues } from "@/components/Toolbar";
import type { AsyncState } from "@/components/asyncState";

/*
 * /labs/patterns — the page-template gallery.
 *
 * This repo has no Storybook and adding one is disproportionate tooling for
 * the problem. An in-app route is cheaper and strictly better here: it
 * exercises the real router, the real i18n bundle, and real RTL, which is
 * where the interesting bugs in these primitives actually live.
 *
 * It is the thing to point at in code review when someone asks "what does an
 * index page look like".
 */

type DemoState = "loading" | "error" | "empty" | "noResults" | "data";

interface DemoFarm {
  id: string;
  code: string;
  name: string;
  governorate: string;
  areaHa: number;
  active: boolean;
}

const DEMO_FARMS: DemoFarm[] = [
  {
    id: "f1",
    code: "BSH-01",
    name: "Bashayer",
    governorate: "Sharqia",
    areaHa: 412.6,
    active: true,
  },
  {
    id: "f2",
    code: "AGR-01",
    name: "Agrosina",
    governorate: "Ismailia",
    areaHa: 188.0,
    active: true,
  },
  { id: "f3", code: "SUZ-02", name: "Suez East", governorate: "Suez", areaHa: 96.4, active: false },
];

const DEMO_AXES: FilterAxis[] = [
  {
    key: "governorate",
    label: "Governorate",
    options: [
      { value: "sharqia", label: "Sharqia" },
      { value: "ismailia", label: "Ismailia" },
      { value: "suez", label: "Suez" },
    ],
  },
  {
    key: "crop",
    label: "Crop",
    options: [
      { value: "mango", label: "Mango" },
      { value: "citrus", label: "Citrus" },
    ],
  },
];

function demoState<T>(kind: DemoState, data: T, empty: T): AsyncState<T> {
  switch (kind) {
    case "loading":
      return { status: "loading" };
    case "error":
      return { status: "error", error: new Error("Demo failure"), retry: () => undefined };
    case "empty":
    case "noResults":
      return { status: "success", data: empty };
    case "data":
      return { status: "success", data };
  }
}

function Section({
  id,
  title,
  note,
  children,
}: {
  id: string;
  title: string;
  note?: string;
  children: ReactNode;
}): ReactNode {
  return (
    <section id={id} className="flex flex-col gap-3">
      <div>
        <h2 className="text-lg font-semibold text-ap-ink">{title}</h2>
        {note ? <p className="mt-0.5 text-sm text-ap-muted">{note}</p> : null}
      </div>
      {children}
    </section>
  );
}

export function PatternsPage(): ReactNode {
  const { t, i18n } = useTranslation("common");
  const [state, setState] = useState<DemoState>("data");
  const [width, setWidth] = useState<PageWidth>("wide");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<string | null>("active");
  const [filters, setFilters] = useState<FilterValues>({});
  const [page, setPage] = useState(0);

  const filtered = state === "noResults";
  const farmState = demoState<readonly DemoFarm[]>(state, DEMO_FARMS, []);

  const columns: Column<DemoFarm>[] = [
    { key: "code", header: "Code", cell: (f) => f.code },
    { key: "name", header: "Name", cell: (f) => f.name },
    { key: "governorate", header: "Governorate", cell: (f) => f.governorate },
    { key: "area", header: "Area", align: "end", cell: (f) => `${f.areaHa.toFixed(1)} ha` },
    {
      key: "status",
      header: "Status",
      cell: (f) => (
        <Pill kind={f.active ? "ok" : "neutral"}>{f.active ? "Active" : "Archived"}</Pill>
      ),
    },
    {
      key: "actions",
      header: "Actions",
      align: "end",
      cell: () => (
        <RowActions>
          <Button size="sm" variant="secondary">
            Edit
          </Button>
        </RowActions>
      ),
    },
  ];

  return (
    <Page width={width}>
      <PageHeader
        above={<Breadcrumb items={[{ label: "Labs", to: "/labs/map-v2" }, { label: "Patterns" }]} />}
        title="Page patterns"
        badge={<Pill kind="info">internal</Pill>}
        subtitle="Every standard template in every state. Switch the state to see the ladder; switch the language in the top bar to check RTL."
        actions={
          <>
            <Button
              variant="secondary"
              onClick={() => void i18n.changeLanguage(i18n.language === "ar" ? "en" : "ar")}
            >
              {i18n.language === "ar" ? "English" : "العربية"}
            </Button>
            <LinkButton to="/labs/map-v2">Farm console</LinkButton>
          </>
        }
      />

      <Card className="flex flex-wrap items-center gap-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-ap-muted">
            State
          </span>
          <SegmentedControl
            ariaLabel="Demo state"
            value={state}
            onChange={setState}
            items={[
              { value: "loading" as const, label: "Loading" },
              { value: "error" as const, label: "Error" },
              { value: "empty" as const, label: "Empty" },
              { value: "noResults" as const, label: "No results" },
              { value: "data" as const, label: "Data" },
            ]}
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-ap-muted">
            Frame
          </span>
          <SegmentedControl
            ariaLabel="Page width"
            value={width}
            onChange={setWidth}
            items={[
              { value: "wide" as const, label: "Wide" },
              { value: "standard" as const, label: "Standard" },
              { value: "full" as const, label: "Full" },
            ]}
          />
        </div>
      </Card>

      <Section
        id="index"
        title="IndexPage"
        note="18 pages. Toolbar + DataTable + Pagination. Headers stay mounted while rows load (decision 3B); the identity cell is a real link and the whole row is clickable (decision 1C)."
      >
        <Toolbar
          search={{ value: search, onChange: setSearch, placeholder: "Search farms…" }}
          chips={
            <ToolbarChips
              allLabel="All"
              value={status}
              onChange={setStatus}
              options={[
                { value: "active", label: "Active" },
                { value: "archived", label: "Archived" },
              ]}
            />
          }
          axes={DEMO_AXES}
          values={filters}
          onValuesChange={setFilters}
          resultCount={{ shown: state === "data" ? DEMO_FARMS.length : 0, total: 14 }}
        />
        <DataTable<DemoFarm>
          columns={columns}
          rowKey={(f) => f.id}
          state={farmState}
          filtered={filtered}
          rowHref={(f) => `/farms/${f.id}`}
          caption="Demo farms"
          empty={
            <EmptyState
              message="No farms yet. Create the first one to get started."
              action={<LinkButton to="/labs/map-v2?create=farm">Create farm</LinkButton>}
            />
          }
          noResults={
            <EmptyState
              message="No farms match your filters."
              action={
                <Button variant="secondary" onClick={() => setFilters({})}>
                  {t("toolbar.clearAll")}
                </Button>
              }
            />
          }
        />
        <Pagination page={page} pageSize={25} total={60} onPageChange={setPage} />
      </Section>

      <Section
        id="rowlist"
        title="RowList"
        note="The P2 body — alerts, recommendations, signals. Same ladder, taller rows, inline actions."
      >
        <RowList<DemoFarm>
          state={farmState}
          filtered={filtered}
          rowKey={(f) => f.id}
          rail={(f) => (f.active ? "bg-ap-good" : "bg-ap-line")}
          title={(f) => (
            <>
              {f.name}
              <Pill kind={f.active ? "ok" : "neutral"}>{f.active ? "Active" : "Archived"}</Pill>
            </>
          )}
          subtitle={(f) => `${f.governorate} · ${f.areaHa.toFixed(1)} ha under management`}
          meta={(f) => (
            <>
              <span className="font-mono">{f.code}</span>
              <span>·</span>
              <span>updated 2 hours ago</span>
            </>
          )}
          actions={() => (
            <>
              <Button size="sm" variant="secondary">
                Acknowledge
              </Button>
              <Button size="sm" variant="ghost">
                Resolve
              </Button>
            </>
          )}
          empty={<EmptyState message="Nothing to review." action={null} />}
        />
      </Section>

      <Section
        id="detail"
        title="DetailPage"
        note="5 pages. Breadcrumb + one title scale + inline status + actions with the destructive one last (decision 4C). Tabs appear once a page carries more than three panels."
      >
        <Card noPadding className="p-4">
          <PageHeader
            above={
              <Breadcrumb
                items={[
                  { label: "Farms", to: "/farms" },
                  { label: "Bashayer", to: "/farms/f1" },
                  { label: "Block B-14" },
                ]}
              />
            }
            title="Block B-14"
            badge={<Pill kind="warn">Water stress</Pill>}
            subtitle="18.4 ha · drip · Mango, Keitt"
            actions={
              <>
                <Button variant="ghost">Edit</Button>
                <Button variant="secondary">Re-zone grid</Button>
                <Button variant="danger">Archive</Button>
              </>
            }
          />
          <div className="mt-4 flex flex-col gap-4">
            <StatusBanner kind="warn" detail="One open recommendation is waiting for approval.">
              NDMI has been below baseline for 6 consecutive days.
            </StatusBanner>
            <KPIRow>
              <KPICard title="NDVI" value="0.61" hint="−0.04 vs 30-day" />
              <KPICard title="NDMI" value="0.18" hint="−0.19 vs baseline" />
              <KPICard title="Last scene" value="25 Jul" hint="12% cloud" />
            </KPIRow>
            <Card
              title="Block details"
              actions={
                <Button size="sm" variant="ghost">
                  Edit
                </Button>
              }
            >
              <dl className="flex flex-col">
                {[
                  ["Code", "B-14"],
                  ["Area", "18.4 ha"],
                  ["Irrigation", "Drip"],
                  ["Grid", "24 cells · 30 m"],
                ].map(([k, v]) => (
                  <div
                    key={k}
                    className="flex justify-between gap-4 border-t border-ap-line py-2 text-sm first:border-t-0"
                  >
                    <dt className="text-xs uppercase tracking-wide text-ap-muted">{k}</dt>
                    <dd className="text-ap-ink">{v}</dd>
                  </div>
                ))}
              </dl>
            </Card>
          </div>
        </Card>
      </Section>

      <Section
        id="form"
        title="FormPage"
        note="5 pages. One Field with label / help / error wiring, and a footer that puts cancel before submit."
      >
        <Card
          title="Identity"
          footer={
            <FormFooter
              message="Area must be greater than zero."
              cancel={<Button variant="ghost">Cancel</Button>}
              submit={<Button>Save changes</Button>}
            />
          }
          bodyClassName="grid gap-4 sm:grid-cols-2"
        >
          <Field label="Code" required help="Unique within the tenant.">
            {(props) => <input {...props} className={FIELD_CONTROL_CLASS} defaultValue="BSH-01" />}
          </Field>
          <Field label="Name" required>
            {(props) => (
              <input {...props} className={FIELD_CONTROL_CLASS} defaultValue="Bashayer" />
            )}
          </Field>
          <Field label="Governorate">
            {(props) => (
              <select {...props} className={FIELD_CONTROL_CLASS} defaultValue="sharqia">
                <option value="sharqia">Sharqia</option>
                <option value="ismailia">Ismailia</option>
              </select>
            )}
          </Field>
          <Field label="Area (ha)" error="Area must be greater than zero.">
            {(props) => <input {...props} className={FIELD_CONTROL_CLASS} defaultValue="-12" />}
          </Field>
        </Card>
      </Section>

      <Section
        id="states"
        title="AsyncBoundary"
        note="The non-table ladder, for panels and detail surfaces."
      >
        <AsyncBoundary
          state={farmState}
          skeleton="lines"
          filtered={filtered}
          empty={
            <Card>
              <EmptyState message="Nothing here yet." action={<Button>Create one</Button>} />
            </Card>
          }
          noResults={
            <Card>
              <EmptyState message="Nothing matches your filters." action={null} />
            </Card>
          }
        >
          {(farms) => (
            <Card>
              <p className="text-sm text-ap-ink">{farms.length} farms resolved.</p>
            </Card>
          )}
        </AsyncBoundary>
      </Section>

      <Section
        id="primitives"
        title="Primitives"
        note="Buttons, pills, and banners at their real sizes."
      >
        <Card className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-2">
            <Button>Primary</Button>
            <Button variant="secondary">Secondary</Button>
            <Button variant="ghost">Ghost</Button>
            <Button variant="danger">Danger</Button>
            <Button disabled>Disabled</Button>
            <LinkButton to="/labs/patterns" variant="secondary">
              LinkButton
            </LinkButton>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Pill kind="ok">Healthy</Pill>
            <Pill kind="warn">Stale</Pill>
            <Pill kind="crit">Failed</Pill>
            <Pill kind="info">Info</Pill>
            <Pill kind="neutral">Draft</Pill>
          </div>
          <div className="flex flex-col gap-2">
            <StatusBanner kind="info">Informational standing state.</StatusBanner>
            <StatusBanner kind="warn">Something needs attention soon.</StatusBanner>
            <StatusBanner kind="crit">Something is wrong right now.</StatusBanner>
          </div>
        </Card>
      </Section>
    </Page>
  );
}
