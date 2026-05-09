import type { ReactNode } from "react";
import { useId, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import {
  type CreateAdminTenantPayload,
  type TenantStatus,
  type TenantTier,
} from "@/api/adminTenants";
import { isApiError } from "@/api/errors";
import { useAdminTenantMeta, useCreateAdminTenant } from "@/queries/admin/tenants";

const SLUG_RE = /^[a-z0-9-]{3,32}$/;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

interface FormState {
  slug: string;
  name: string;
  legal_name: string;
  tax_id: string;
  contact_email: string;
  contact_phone: string;
  default_locale: "en" | "ar";
  default_unit_system: "feddan" | "acre" | "hectare";
  initial_tier: TenantTier;
  owner_email: string;
  owner_full_name: string;
}

const INITIAL: FormState = {
  slug: "",
  name: "",
  legal_name: "",
  tax_id: "",
  contact_email: "",
  contact_phone: "",
  default_locale: "en",
  default_unit_system: "feddan",
  initial_tier: "free",
  owner_email: "",
  owner_full_name: "",
};

type Step = "profile" | "owner" | "review";
const STEPS: Step[] = ["profile", "owner", "review"];

interface SuccessState {
  tenantId: string;
  ownerEmail: string | null;
  status: TenantStatus;
}

export function TenantCreatePage(): ReactNode {
  const { t } = useTranslation("admin");
  const navigate = useNavigate();
  const meta = useAdminTenantMeta();
  const create = useCreateAdminTenant();

  const [step, setStep] = useState<Step>("profile");
  const [form, setForm] = useState<FormState>(INITIAL);
  const [errors, setErrors] = useState<Partial<Record<keyof FormState, string>>>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [success, setSuccess] = useState<SuccessState | null>(null);

  function set<K extends keyof FormState>(key: K, value: FormState[K]): void {
    setForm((prev) => ({ ...prev, [key]: value }));
    setErrors((prev) => ({ ...prev, [key]: undefined }));
  }

  function validateProfile(): boolean {
    const next: Partial<Record<keyof FormState, string>> = {};
    if (!SLUG_RE.test(form.slug)) {
      next.slug = t("tenants.create.errors.slugFormat");
    }
    if (!form.name.trim()) {
      next.name = t("tenants.create.errors.nameRequired");
    }
    if (!form.contact_email.trim()) {
      next.contact_email = t("tenants.create.errors.contactEmailRequired");
    } else if (!EMAIL_RE.test(form.contact_email)) {
      next.contact_email = t("tenants.create.errors.contactEmailInvalid");
    }
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  function validateOwner(): boolean {
    const next: Partial<Record<keyof FormState, string>> = {};
    if (form.owner_email && !EMAIL_RE.test(form.owner_email)) {
      next.owner_email = t("tenants.create.errors.ownerEmailInvalid");
    }
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  function buildPayload(): CreateAdminTenantPayload {
    return {
      slug: form.slug,
      name: form.name.trim(),
      contact_email: form.contact_email.trim(),
      legal_name: form.legal_name.trim() || null,
      tax_id: form.tax_id.trim() || null,
      contact_phone: form.contact_phone.trim() || null,
      default_locale: form.default_locale,
      default_unit_system: form.default_unit_system,
      initial_tier: form.initial_tier,
      owner_email: form.owner_email.trim() || null,
      owner_full_name: form.owner_full_name.trim() || null,
    };
  }

  function handleSubmit(): void {
    setSubmitError(null);
    create.mutate(buildPayload(), {
      onSuccess: (data) => {
        setSuccess({
          tenantId: data.id,
          ownerEmail: form.owner_email.trim() || null,
          status: data.status,
        });
      },
      onError: (err) => {
        if (isApiError(err) && err.status === 409) {
          setErrors({ slug: t("tenants.create.errors.slugConflict") });
          setStep("profile");
          return;
        }
        setSubmitError(t("tenants.create.errors.createFailed"));
      },
    });
  }

  if (success) {
    return <SuccessPanel state={success} onDone={() => navigate(`/platform/tenants/${success.tenantId}`)} />;
  }

  return (
    <section className="mx-auto max-w-2xl">
      <header className="border-b border-ap-line pb-4">
        <h1 className="text-lg font-semibold text-ap-ink">{t("tenants.create.title")}</h1>
        <p className="mt-1 text-sm text-ap-muted">{t("tenants.create.subtitle")}</p>
        <p className="mt-1 text-xs uppercase tracking-wider text-ap-muted">
          {t("tenants.create.step", {
            current: STEPS.indexOf(step) + 1,
            total: STEPS.length,
          })}
          {" — "}
          {t(`tenants.create.steps.${step}`)}
        </p>
      </header>

      {submitError ? (
        <p
          role="alert"
          className="mt-4 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800"
        >
          {submitError}
        </p>
      ) : null}

      {step === "profile" ? (
        <ProfileStep
          form={form}
          errors={errors}
          onChange={set}
          locales={meta.data?.locales ?? ["en", "ar"]}
          unitSystems={meta.data?.unit_systems ?? ["feddan", "acre", "hectare"]}
        />
      ) : null}
      {step === "owner" ? (
        <OwnerStep
          form={form}
          errors={errors}
          onChange={set}
          tiers={meta.data?.tiers ?? ["free", "standard", "premium", "enterprise"]}
        />
      ) : null}
      {step === "review" ? <ReviewStep form={form} /> : null}

      <footer className="mt-6 flex justify-between">
        <button
          type="button"
          onClick={() => navigate("/platform/tenants")}
          className="rounded-md border border-ap-line bg-ap-panel px-3 py-2 text-sm font-medium text-ap-muted hover:bg-ap-line/40"
        >
          {t("tenants.create.actions.cancel")}
        </button>
        <div className="flex gap-2">
          {step !== "profile" ? (
            <button
              type="button"
              onClick={() => setStep(STEPS[STEPS.indexOf(step) - 1])}
              disabled={create.isPending}
              className="rounded-md border border-ap-line bg-ap-panel px-3 py-2 text-sm font-medium text-ap-ink hover:bg-ap-line/40 disabled:opacity-60"
            >
              {t("tenants.create.actions.back")}
            </button>
          ) : null}
          {step !== "review" ? (
            <button
              type="button"
              onClick={() => {
                if (step === "profile" && !validateProfile()) return;
                if (step === "owner" && !validateOwner()) return;
                setStep(STEPS[STEPS.indexOf(step) + 1]);
              }}
              className="rounded-md bg-ap-primary px-3 py-2 text-sm font-medium text-white hover:bg-ap-primary/90"
            >
              {t("tenants.create.actions.next")}
            </button>
          ) : (
            <button
              type="button"
              onClick={handleSubmit}
              disabled={create.isPending}
              className="rounded-md bg-ap-primary px-3 py-2 text-sm font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
            >
              {create.isPending
                ? t("tenants.create.actions.creating")
                : t("tenants.create.actions.submit")}
            </button>
          )}
        </div>
      </footer>
    </section>
  );
}

interface StepProps {
  form: FormState;
  errors: Partial<Record<keyof FormState, string>>;
  onChange: <K extends keyof FormState>(key: K, value: FormState[K]) => void;
}

function ProfileStep({
  form,
  errors,
  onChange,
  locales,
  unitSystems,
}: StepProps & { locales: readonly string[]; unitSystems: readonly string[] }): ReactNode {
  const { t } = useTranslation("admin");
  return (
    <div className="mt-6 space-y-4">
      <Field
        label={t("tenants.create.fields.slug")}
        help={t("tenants.create.fields.slugHelp")}
        error={errors.slug}
      >
        {(id) => (
          <input
            id={id}
            type="text"
            value={form.slug}
            onChange={(e) => onChange("slug", e.target.value.toLowerCase())}
            autoComplete="off"
            className="w-full rounded-md border border-ap-line bg-ap-panel px-3 py-2 font-mono text-sm shadow-sm"
          />
        )}
      </Field>
      <Field label={t("tenants.create.fields.name")} error={errors.name}>
        {(id) => (
          <input
            id={id}
            type="text"
            value={form.name}
            onChange={(e) => onChange("name", e.target.value)}
            className="w-full rounded-md border border-ap-line bg-ap-panel px-3 py-2 text-sm shadow-sm"
          />
        )}
      </Field>
      <div className="grid gap-4 md:grid-cols-2">
        <Field label={t("tenants.create.fields.legalName")}>
          {(id) => (
            <input
              id={id}
              type="text"
              value={form.legal_name}
              onChange={(e) => onChange("legal_name", e.target.value)}
              className="w-full rounded-md border border-ap-line bg-ap-panel px-3 py-2 text-sm shadow-sm"
            />
          )}
        </Field>
        <Field label={t("tenants.create.fields.taxId")}>
          {(id) => (
            <input
              id={id}
              type="text"
              value={form.tax_id}
              onChange={(e) => onChange("tax_id", e.target.value)}
              className="w-full rounded-md border border-ap-line bg-ap-panel px-3 py-2 text-sm shadow-sm"
            />
          )}
        </Field>
      </div>
      <Field
        label={t("tenants.create.fields.contactEmail")}
        error={errors.contact_email}
      >
        {(id) => (
          <input
            id={id}
            type="email"
            value={form.contact_email}
            onChange={(e) => onChange("contact_email", e.target.value)}
            className="w-full rounded-md border border-ap-line bg-ap-panel px-3 py-2 text-sm shadow-sm"
          />
        )}
      </Field>
      <Field label={t("tenants.create.fields.contactPhone")}>
        {(id) => (
          <input
            id={id}
            type="tel"
            value={form.contact_phone}
            onChange={(e) => onChange("contact_phone", e.target.value)}
            className="w-full rounded-md border border-ap-line bg-ap-panel px-3 py-2 text-sm shadow-sm"
          />
        )}
      </Field>
      <div className="grid gap-4 md:grid-cols-2">
        <Field label={t("tenants.create.fields.locale")}>
          {(id) => (
            <select
              id={id}
              value={form.default_locale}
              onChange={(e) =>
                onChange("default_locale", e.target.value as FormState["default_locale"])
              }
              className="w-full rounded-md border border-ap-line bg-ap-panel px-3 py-2 text-sm shadow-sm"
            >
              {locales.map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label={t("tenants.create.fields.unitSystem")}>
          {(id) => (
            <select
              id={id}
              value={form.default_unit_system}
              onChange={(e) =>
                onChange(
                  "default_unit_system",
                  e.target.value as FormState["default_unit_system"],
                )
              }
              className="w-full rounded-md border border-ap-line bg-ap-panel px-3 py-2 text-sm shadow-sm"
            >
              {unitSystems.map((u) => (
                <option key={u} value={u}>
                  {u}
                </option>
              ))}
            </select>
          )}
        </Field>
      </div>
    </div>
  );
}

function OwnerStep({
  form,
  errors,
  onChange,
  tiers,
}: StepProps & { tiers: readonly TenantTier[] }): ReactNode {
  const { t } = useTranslation("admin");
  return (
    <div className="mt-6 space-y-4">
      <Field
        label={t("tenants.create.fields.tier")}
        help={t("tenants.create.fields.tierHelp")}
      >
        {(id) => (
          <select
            id={id}
            value={form.initial_tier}
            onChange={(e) => onChange("initial_tier", e.target.value as TenantTier)}
            className="w-full rounded-md border border-ap-line bg-ap-panel px-3 py-2 text-sm shadow-sm"
          >
            {tiers.map((tier) => (
              <option key={tier} value={tier}>
                {tier}
              </option>
            ))}
          </select>
        )}
      </Field>
      <Field
        label={t("tenants.create.fields.ownerEmail")}
        help={t("tenants.create.fields.ownerEmailHelp")}
        error={errors.owner_email}
      >
        {(id) => (
          <input
            id={id}
            type="email"
            value={form.owner_email}
            onChange={(e) => onChange("owner_email", e.target.value)}
            className="w-full rounded-md border border-ap-line bg-ap-panel px-3 py-2 text-sm shadow-sm"
          />
        )}
      </Field>
      <Field label={t("tenants.create.fields.ownerFullName")}>
        {(id) => (
          <input
            id={id}
            type="text"
            value={form.owner_full_name}
            onChange={(e) => onChange("owner_full_name", e.target.value)}
            className="w-full rounded-md border border-ap-line bg-ap-panel px-3 py-2 text-sm shadow-sm"
          />
        )}
      </Field>
    </div>
  );
}

function ReviewStep({ form }: { form: FormState }): ReactNode {
  const { t } = useTranslation("admin");
  return (
    <div className="mt-6 space-y-3 rounded-md border border-ap-line bg-ap-panel p-4 text-sm">
      <ReviewRow label={t("tenants.create.fields.slug")} value={form.slug} mono />
      <ReviewRow label={t("tenants.create.fields.name")} value={form.name} />
      <ReviewRow
        label={t("tenants.create.fields.contactEmail")}
        value={form.contact_email}
      />
      <ReviewRow
        label={t("tenants.create.fields.locale")}
        value={form.default_locale}
      />
      <ReviewRow
        label={t("tenants.create.fields.unitSystem")}
        value={form.default_unit_system}
      />
      <ReviewRow label={t("tenants.create.fields.tier")} value={form.initial_tier} />
      {form.owner_email ? (
        <>
          <ReviewRow
            label={t("tenants.create.fields.ownerEmail")}
            value={form.owner_email}
          />
          <p className="rounded-md bg-emerald-50 p-2 text-xs text-emerald-800">
            {t("tenants.create.review.ownerNote", { email: form.owner_email })}
          </p>
        </>
      ) : (
        <p className="rounded-md bg-amber-50 p-2 text-xs text-amber-900">
          {t("tenants.create.review.noOwnerNote")}
        </p>
      )}
    </div>
  );
}

function SuccessPanel({
  state,
  onDone,
}: {
  state: SuccessState;
  onDone: () => void;
}): ReactNode {
  const { t } = useTranslation("admin");
  let body: string;
  if (state.status === "pending_provision") {
    body = t("tenants.create.success.pendingProvision");
  } else if (state.ownerEmail) {
    body = t("tenants.create.success.withOwner", { email: state.ownerEmail });
  } else {
    body = t("tenants.create.success.noOwner");
  }
  return (
    <section
      role="status"
      className="mx-auto max-w-lg rounded-md border border-emerald-200 bg-emerald-50 p-6 shadow-card"
    >
      <h1 className="text-base font-semibold text-emerald-900">
        {t("tenants.create.success.title")}
      </h1>
      <p className="mt-2 text-sm text-emerald-800">{body}</p>
      <button
        type="button"
        onClick={onDone}
        className="mt-4 rounded-md bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-700"
      >
        {t("tenants.detail.title")}
      </button>
    </section>
  );
}

interface FieldProps {
  label: string;
  help?: string;
  error?: string;
  children: (id: string) => ReactNode;
}

function Field({ label, help, error, children }: FieldProps): ReactNode {
  const id = useId();
  return (
    <div className="text-sm">
      <label
        htmlFor={id}
        className="block text-xs font-semibold uppercase tracking-wide text-ap-muted"
      >
        {label}
      </label>
      <div className="mt-1">{children(id)}</div>
      {help && !error ? <p className="mt-1 text-xs text-ap-muted">{help}</p> : null}
      {error ? <p className="mt-1 text-xs text-rose-700">{error}</p> : null}
    </div>
  );
}

function ReviewRow({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}): ReactNode {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-xs uppercase tracking-wide text-ap-muted">{label}</dt>
      <dd className={mono ? "font-mono text-xs text-ap-ink" : "text-sm text-ap-ink"}>
        {value || "—"}
      </dd>
    </div>
  );
}
