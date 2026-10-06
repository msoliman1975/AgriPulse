import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  IdType,
  Investor,
  InvestorLanguage,
  InvestorPayload,
  InvestorType,
} from "@/api/investors";
import { Button } from "@/components/Button";
import { FIELD_CONTROL_CLASS, Field } from "@/components/Field";
import { Modal } from "@/components/Modal";

const ID_TYPES: IdType[] = ["national_id", "passport", "commercial_register", "other"];

interface Props {
  /** null = create. */
  investor: Investor | null;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (payload: InvestorPayload) => void;
}

/** Create or edit an investor. The same fields both ways; the code only on create. */
export function InvestorFormDialog({
  investor,
  busy,
  error,
  onClose,
  onSubmit,
}: Props): JSX.Element {
  const { t } = useTranslation("investors");
  const [code, setCode] = useState("");
  const [type, setType] = useState<InvestorType>(investor?.investor_type ?? "person");
  const [fullName, setFullName] = useState(investor?.full_name ?? "");
  const [fullNameAr, setFullNameAr] = useState(investor?.full_name_ar ?? "");
  const [contact, setContact] = useState(investor?.contact_person ?? "");
  const [email, setEmail] = useState(investor?.email ?? "");
  const [phone, setPhone] = useState(investor?.phone ?? "");
  const [idType, setIdType] = useState<IdType | "">(investor?.national_id_type ?? "");
  const [idLast4, setIdLast4] = useState(investor?.national_id_last4 ?? "");
  const [nationality, setNationality] = useState(investor?.nationality ?? "");
  const [country, setCountry] = useState(investor?.country ?? "");
  const [city, setCity] = useState(investor?.city ?? "");
  const [language, setLanguage] = useState<InvestorLanguage>(investor?.preferred_language ?? "ar");
  const [notes, setNotes] = useState(investor?.notes_internal ?? "");

  const text = (
    label: string,
    value: string,
    set: (v: string) => void,
    opts: { required?: boolean; help?: string; type?: string; max?: number; dir?: "rtl" } = {},
  ) => (
    <Field label={label} required={opts.required} help={opts.help}>
      {(p) => (
        <input
          {...p}
          type={opts.type ?? "text"}
          dir={opts.dir}
          required={opts.required}
          maxLength={opts.max ?? 200}
          className={FIELD_CONTROL_CLASS}
          value={value}
          onChange={(e) => set(e.target.value)}
        />
      )}
    </Field>
  );

  return (
    <Modal open onClose={onClose} labelledBy="investor-form-title" className="max-w-2xl">
      <h2 id="investor-form-title" className="text-lg font-semibold text-ap-ink">
        {investor ? t("form.editTitle") : t("form.createTitle")}
      </h2>
      <form
        className="mt-4 flex max-h-[70vh] flex-col gap-3 overflow-y-auto pe-1"
        onSubmit={(e) => {
          e.preventDefault();
          onSubmit({
            ...(investor ? {} : { code: code.trim() || null }),
            investor_type: type,
            full_name: fullName.trim(),
            full_name_ar: fullNameAr.trim() || null,
            contact_person: contact.trim() || null,
            email: email.trim(),
            phone: phone.trim() || null,
            national_id_type: idType || null,
            national_id_last4: idLast4.trim() || null,
            nationality: nationality.trim() || null,
            country: country.trim() || null,
            city: city.trim() || null,
            preferred_language: language,
            notes_internal: notes.trim() || null,
          });
        }}
      >
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {investor
            ? null
            : text(t("form.code"), code, setCode, { help: t("form.codeHelp"), max: 32 })}
          <Field label={t("form.type")}>
            {(p) => (
              <select
                {...p}
                className={FIELD_CONTROL_CLASS}
                value={type}
                onChange={(e) => setType(e.target.value as InvestorType)}
              >
                <option value="person">{t("type.person")}</option>
                <option value="company">{t("type.company")}</option>
              </select>
            )}
          </Field>
          {text(t("form.fullName"), fullName, setFullName, { required: true })}
          {text(t("form.fullNameAr"), fullNameAr, setFullNameAr, { dir: "rtl" })}
          {type === "company"
            ? text(t("form.contactPerson"), contact, setContact, {
                help: t("form.contactPersonHelp"),
              })
            : null}
          {text(t("form.email"), email, setEmail, {
            required: true,
            type: "email",
            help: t("form.emailHelp"),
          })}
          {text(t("form.phone"), phone, setPhone, { type: "tel", max: 32 })}
          <Field label={t("form.idType")}>
            {(p) => (
              <select
                {...p}
                className={FIELD_CONTROL_CLASS}
                value={idType}
                onChange={(e) => setIdType(e.target.value as IdType | "")}
              >
                <option value="">{t("form.none")}</option>
                {ID_TYPES.map((v) => (
                  <option key={v} value={v}>
                    {t(`idType.${v}`)}
                  </option>
                ))}
              </select>
            )}
          </Field>
          {text(t("form.idLast4"), idLast4, setIdLast4, { help: t("form.idLast4Help"), max: 4 })}
          {text(t("form.nationality"), nationality, setNationality, { max: 80 })}
          {text(t("form.country"), country, setCountry, { max: 80 })}
          {text(t("form.city"), city, setCity, { max: 80 })}
          <Field label={t("form.language")}>
            {(p) => (
              <select
                {...p}
                className={FIELD_CONTROL_CLASS}
                value={language}
                onChange={(e) => setLanguage(e.target.value as InvestorLanguage)}
              >
                <option value="ar">{t("language.ar")}</option>
                <option value="en">{t("language.en")}</option>
              </select>
            )}
          </Field>
          <Field label={t("form.notes")} help={t("form.notesHelp")} className="sm:col-span-2">
            {(p) => (
              <textarea
                {...p}
                rows={2}
                maxLength={4000}
                className={FIELD_CONTROL_CLASS}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
              />
            )}
          </Field>
        </div>
        {error ? (
          <p role="alert" className="text-sm text-ap-crit">
            {error}
          </p>
        ) : null}
        <div className="mt-2 flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            {t("form.cancel")}
          </Button>
          <Button type="submit" disabled={busy || !fullName.trim() || !email.trim()}>
            {investor ? t("form.save") : t("form.create")}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
