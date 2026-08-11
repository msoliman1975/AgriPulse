import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import { listFarms } from "@/api/farms";
import type { EnrolmentResult, WorkerBrief } from "@/api/fieldAccess";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import { Toolbar } from "@/components/Toolbar";
import { queryState } from "@/components/asyncState";
import { useCapability } from "@/rbac/useCapability";
import {
  useEnrolFieldWorker,
  useFieldEnrolmentAudit,
  useReRoleFieldWorkers,
  useReissueFieldPin,
} from "@/queries/fieldAccess";

/**
 * /settings/field-access — hand a field worker the app.
 *
 * This is a worklist, not a directory. The four buckets it renders each imply
 * a different next action, and two of them are silent failures rather than
 * errors: a `FieldWorker` can be scheduled but holds no capabilities and can
 * never sign in, and someone with no phone number cannot have an account at
 * all because the phone *is* the username.
 *
 * Everything is farm-scoped. `user.field_enrol` resolves against the farm in
 * each request, so the manager standing with the crew can do this without
 * tenant-wide user administration.
 */
export function FieldAccessPage(): ReactNode {
  const { t } = useTranslation("fieldAccess");
  const canEnrol = useCapability("user.field_enrol");

  const farmsQ = useQuery({
    queryKey: ["farms", "list-tenant"],
    queryFn: () => listFarms({ limit: 100 }),
    staleTime: 60_000,
  });

  const [farmId, setFarmId] = useState<string | null>(null);
  const effectiveFarmId = useMemo(
    () => farmId ?? farmsQ.data?.items[0]?.id ?? null,
    [farmId, farmsQ.data],
  );

  const auditQ = useFieldEnrolmentAudit(effectiveFarmId);

  // The PIN is returned once, by design — nothing stores it and nothing can
  // look it up again. Held here only until the operator dismisses it.
  const [issued, setIssued] = useState<{ name: string; result: EnrolmentResult } | null>(null);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={t("title")} subtitle={t("subtitle")} />

      <Toolbar
        right={
          <label className="flex items-center gap-2 text-sm">
            <span className="text-ap-muted">{t("pickFarm")}</span>
            <select
              className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-sm text-ap-ink"
              value={effectiveFarmId ?? ""}
              onChange={(e) => setFarmId(e.target.value || null)}
            >
              <option value="">{t("noFarm")}</option>
              {(farmsQ.data?.items ?? []).map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
          </label>
        }
      />

      {issued ? (
        <PinCallout
          name={issued.name}
          phone={issued.result.phone}
          pin={issued.result.pin}
          onDismiss={() => setIssued(null)}
        />
      ) : null}

      {!effectiveFarmId ? (
        <EmptyState message={t("noFarmSelected")} action={null} />
      ) : (
        <AsyncBoundary
          state={queryState(auditQ)}
          errorMessage={t("loadFailed")}
          isEmpty={() => false}
          empty={<EmptyState message={t("empty")} action={null} />}
        >
          {(audit) => (
            <div className="flex flex-col gap-6">
              <ReadyToEnrol
                rows={audit.ready_to_enrol}
                farmId={effectiveFarmId}
                canEnrol={canEnrol}
                onIssued={setIssued}
              />
              <BlockedByRole
                rows={audit.blocked_by_role}
                farmId={effectiveFarmId}
                canEnrol={canEnrol}
              />
              <MissingPhone rows={audit.missing_phone} />
              <Enrolled
                rows={audit.enrolled}
                farmId={effectiveFarmId}
                canEnrol={canEnrol}
                onIssued={setIssued}
              />
            </div>
          )}
        </AsyncBoundary>
      )}
    </div>
  );
}

/**
 * The PIN, shown once and read aloud. There is no delivery channel: the email
 * address is synthetic and nothing can be sent to it, and no SMS goes out.
 * Spoken handover is the whole ceremony, so this has to be impossible to miss
 * and has to say plainly that it will not be shown again.
 */
function PinCallout({
  name,
  phone,
  pin,
  onDismiss,
}: {
  name: string;
  phone: string;
  pin: string;
  onDismiss: () => void;
}): ReactNode {
  const { t } = useTranslation("fieldAccess");
  return (
    <Card title={t("pin.heading", { name })}>
      <div className="flex flex-col gap-3">
        <p className="text-sm text-ap-muted">{t("pin.readAloud")}</p>
        <div className="flex items-baseline gap-4">
          <span className="font-mono text-3xl tracking-[0.3em] tabular-nums text-ap-ink">
            {pin}
          </span>
          <span className="font-mono text-sm text-ap-muted">{phone}</span>
        </div>
        <p className="text-sm text-ap-warn">{t("pin.onceOnly")}</p>
        <div>
          <Button size="sm" variant="secondary" onClick={onDismiss}>
            {t("pin.dismiss")}
          </Button>
        </div>
      </div>
    </Card>
  );
}

function ReadyToEnrol({
  rows,
  farmId,
  canEnrol,
  onIssued,
}: {
  rows: WorkerBrief[];
  farmId: string;
  canEnrol: boolean;
  onIssued: (v: { name: string; result: EnrolmentResult }) => void;
}): ReactNode {
  const { t } = useTranslation("fieldAccess");
  const enrol = useEnrolFieldWorker(farmId);
  const [busyId, setBusyId] = useState<string | null>(null);

  return (
    <Card noPadding title={t("ready.heading")}>
      <p className="px-4 pt-3 text-sm text-ap-muted">{t("ready.hint")}</p>
      {rows.length === 0 ? (
        <p className="px-4 py-6 text-sm text-ap-muted">{t("ready.none")}</p>
      ) : (
        <Table>
          <Thead>
            <Tr>
              <Th>{t("col.name")}</Th>
              <Th>{t("col.role")}</Th>
              {canEnrol ? <Th className="w-40" /> : null}
            </Tr>
          </Thead>
          <Tbody>
            {rows.map((w) => (
              <Tr key={w.id}>
                <Td>{w.name}</Td>
                <Td>{w.role}</Td>
                {canEnrol ? (
                  <Td>
                    <Button
                      size="sm"
                      disabled={busyId === w.id}
                      onClick={() => {
                        setBusyId(w.id);
                        enrol.mutate(
                          {
                            // The worker already exists, so adopt that row
                            // rather than creating a second person.
                            worker_id: w.id,
                            farm_id: farmId,
                            full_name: w.name,
                            // The number the farm already recorded. Retyping
                            // it would let a typo mint a second account under
                            // a different username instead of failing.
                            phone: w.phone ?? "",
                            role: w.role === "FieldOperator" ? "FieldOperator" : "Scout",
                          },
                          {
                            onSuccess: (result) => onIssued({ name: w.name, result }),
                            onSettled: () => setBusyId(null),
                          },
                        );
                      }}
                    >
                      {busyId === w.id ? t("ready.working") : t("ready.giveAccess")}
                    </Button>
                  </Td>
                ) : null}
              </Tr>
            ))}
          </Tbody>
        </Table>
      )}
    </Card>
  );
}

/**
 * `FieldWorker` holds zero capabilities. Someone recorded that way can be put
 * on the board and can never sign in, and nothing says so until you try — so
 * this bucket exists to say it before the pilot rather than during it.
 */
function BlockedByRole({
  rows,
  farmId,
  canEnrol,
}: {
  rows: WorkerBrief[];
  farmId: string;
  canEnrol: boolean;
}): ReactNode {
  const { t } = useTranslation("fieldAccess");
  const reRole = useReRoleFieldWorkers(farmId);
  if (rows.length === 0) return null;

  return (
    <Card
      noPadding
      title={t("blocked.heading")}
      actions={
        canEnrol ? (
          <Button
            size="sm"
            disabled={reRole.isPending}
            onClick={() => reRole.mutate(rows.map((r) => r.id))}
          >
            {reRole.isPending ? t("blocked.working") : t("blocked.promoteAll", { n: rows.length })}
          </Button>
        ) : null
      }
    >
      <p className="px-4 pt-3 text-sm text-ap-muted">{t("blocked.hint")}</p>
      <Table>
        <Thead>
          <Tr>
            <Th>{t("col.name")}</Th>
            <Th>{t("col.phone")}</Th>
          </Tr>
        </Thead>
        <Tbody>
          {rows.map((w) => (
            <Tr key={w.id}>
              <Td>{w.name}</Td>
              <Td>{w.has_phone ? t("phone.on") : t("phone.off")}</Td>
            </Tr>
          ))}
        </Tbody>
      </Table>
    </Card>
  );
}

/** No phone means no username, so there is nothing to do here but go and get
 *  the number — hence no action button. */
function MissingPhone({ rows }: { rows: WorkerBrief[] }): ReactNode {
  const { t } = useTranslation("fieldAccess");
  if (rows.length === 0) return null;
  return (
    <Card noPadding title={t("noPhone.heading")}>
      <p className="px-4 pt-3 text-sm text-ap-muted">{t("noPhone.hint")}</p>
      <Table>
        <Thead>
          <Tr>
            <Th>{t("col.name")}</Th>
            <Th>{t("col.role")}</Th>
          </Tr>
        </Thead>
        <Tbody>
          {rows.map((w) => (
            <Tr key={w.id}>
              <Td>{w.name}</Td>
              <Td>{w.role}</Td>
            </Tr>
          ))}
        </Tbody>
      </Table>
    </Card>
  );
}

function Enrolled({
  rows,
  farmId,
  canEnrol,
  onIssued,
}: {
  rows: WorkerBrief[];
  farmId: string;
  canEnrol: boolean;
  onIssued: (v: { name: string; result: EnrolmentResult }) => void;
}): ReactNode {
  const { t } = useTranslation("fieldAccess");
  return (
    <Card noPadding title={t("enrolled.heading")}>
      <p className="px-4 pt-3 text-sm text-ap-muted">{t("enrolled.hint")}</p>
      {rows.length === 0 ? (
        <p className="px-4 py-6 text-sm text-ap-muted">{t("enrolled.none")}</p>
      ) : (
        <Table>
          <Thead>
            <Tr>
              <Th>{t("col.name")}</Th>
              <Th>{t("col.role")}</Th>
              {canEnrol ? <Th className="w-40" /> : null}
            </Tr>
          </Thead>
          <Tbody>
            {rows.map((w) => (
              <Tr key={w.id}>
                <Td>{w.name}</Td>
                <Td>{w.role}</Td>
                {canEnrol ? (
                  <Td>
                    <ReissueButton worker={w} farmId={farmId} onIssued={onIssued} />
                  </Td>
                ) : null}
              </Tr>
            ))}
          </Tbody>
        </Table>
      )}
    </Card>
  );
}

/**
 * Recovery is replacement: a PIN cannot be looked up because Keycloak stores
 * only its hash. The old one stops working the moment this succeeds, so the
 * new one has to reach the person — which is why the result goes straight to
 * the read-aloud callout at the top of the page.
 *
 * Disabled when the worker row has no linked user. That happens when someone
 * was linked to a membership by hand on the workers screen without going
 * through enrolment, and there is genuinely no account to re-credential.
 */
function ReissueButton({
  worker,
  farmId,
  onIssued,
}: {
  worker: WorkerBrief;
  farmId: string;
  onIssued: (v: { name: string; result: EnrolmentResult }) => void;
}): ReactNode {
  const { t } = useTranslation("fieldAccess");
  const reissue = useReissueFieldPin(farmId);
  if (!worker.user_id) {
    return (
      <Button size="sm" variant="secondary" disabled title={t("enrolled.noAccount")}>
        {t("enrolled.reissue")}
      </Button>
    );
  }
  return (
    <Button
      size="sm"
      variant="secondary"
      disabled={reissue.isPending}
      onClick={() =>
        reissue.mutate(worker.user_id as string, {
          onSuccess: (result) =>
            onIssued({
              name: worker.name,
              result: {
                user_id: result.user_id,
                pin: result.pin,
                phone: worker.phone ?? "",
                membership_id: "",
                worker_id: worker.id,
              },
            }),
        })
      }
    >
      {reissue.isPending ? t("enrolled.working") : t("enrolled.reissue")}
    </Button>
  );
}
