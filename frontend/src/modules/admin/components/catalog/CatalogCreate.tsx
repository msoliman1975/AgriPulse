// Creating nodes in the catalog console.
//
// The form is small on purpose: a node needs a code and its names, and every
// richer thing it can hold — stage ladder, size classes, agronomic settings —
// is authored afterwards on the inspector tab that can also show whether the
// node owns that value or inherits it. Asking for a stage calendar inside a
// create dialog would be asking before there is anything to inherit from.
//
// The code is the one field that can never be changed later: it anchors the
// canonical path on every descendant and on the denormalized crop_path that
// block assignments carry. So it is asked for once, here, and shown locked
// everywhere after.

import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { Field, FIELD_CONTROL_CLASS } from "@/components/Field";
import { apiMsg } from "@/modules/admin/lib/apiMsg";
import { useCreateCrop, useCreateStrain, useCreateVariety } from "@/queries/cropCatalog";

export function CreateCropForm({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  /** Receives the new crop's code so the caller can select it. */
  onCreated: (code: string) => void;
}): ReactNode {
  const { t } = useTranslation("admin");
  const createCrop = useCreateCrop();
  const [code, setCode] = useState("");
  const [nameEn, setNameEn] = useState("");
  const [nameAr, setNameAr] = useState("");

  return (
    <Card
      as="form"
      title={t("crops.addCrop")}
      onSubmit={(e) => {
        e.preventDefault();
        createCrop.mutate(
          {
            code: code.trim(),
            name_en: nameEn.trim(),
            name_ar: nameAr.trim(),
            // Deliberately the safest defaults: a crop-only annual with no
            // calendar. Everything else is set on the Details tab, where the
            // cycle rules and the GDD prerequisite are explained.
            category: "fruit_tree",
            is_perennial: false,
            classification_depth: "crop_only",
          },
          { onSuccess: (crop) => onCreated(crop.code) },
        );
      }}
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label={t("crops.form.code")} help={t("catalog.codeLocked")}>
          {(props) => (
            <input
              {...props}
              className={FIELD_CONTROL_CLASS}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="mango"
              required
            />
          )}
        </Field>
        <Field label={t("crops.form.nameEn")}>
          {(props) => (
            <input
              {...props}
              className={FIELD_CONTROL_CLASS}
              value={nameEn}
              onChange={(e) => setNameEn(e.target.value)}
              required
            />
          )}
        </Field>
        <Field label={t("crops.form.nameAr")}>
          {(props) => (
            <input
              {...props}
              className={FIELD_CONTROL_CLASS}
              value={nameAr}
              dir="rtl"
              onChange={(e) => setNameAr(e.target.value)}
              required
            />
          )}
        </Field>
      </div>
      <p className="mt-2 text-[11px] text-ap-muted">{t("catalog.createDefaults")}</p>
      {createCrop.isError ? (
        <p role="alert" className="mt-2 text-xs text-ap-crit">
          {apiMsg(createCrop.error)}
        </p>
      ) : null}
      <div className="mt-3 flex gap-2">
        <Button type="submit" size="sm" disabled={createCrop.isPending}>
          {createCrop.isPending ? t("crops.form.saving") : t("crops.form.save")}
        </Button>
        <Button variant="ghost" size="sm" onClick={onClose} disabled={createCrop.isPending}>
          {t("crops.form.cancel")}
        </Button>
      </div>
    </Card>
  );
}

export function CreateNodeForm({
  level,
  parentId,
  parentPath,
  onClose,
  onCreated,
}: {
  level: "variety" | "strain";
  parentId: string;
  parentPath: string;
  onClose: () => void;
  /** Receives the new node's full dotted path. */
  onCreated: (path: string) => void;
}): ReactNode {
  const { t } = useTranslation("admin");
  const createVariety = useCreateVariety();
  const createStrain = useCreateStrain();
  const [code, setCode] = useState("");
  const [nameEn, setNameEn] = useState("");
  const [nameAr, setNameAr] = useState("");
  const mutation = level === "variety" ? createVariety : createStrain;

  const submit = (): void => {
    const payload = {
      code: code.trim(),
      name_en: nameEn.trim(),
      name_ar: nameAr.trim() || null,
    };
    // The server derives the path; taking it from the response rather than
    // concatenating avoids the console selecting a node that doesn't exist.
    if (level === "variety") {
      createVariety.mutate({ cropId: parentId, payload }, { onSuccess: (v) => onCreated(v.path) });
    } else {
      createStrain.mutate(
        { varietyId: parentId, payload },
        { onSuccess: (s) => onCreated(s.path) },
      );
    }
  };

  return (
    <form
      className="space-y-2 rounded-lg border border-ap-line bg-ap-bg/40 p-3"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <p className="text-[11px] text-ap-muted">
        {t(level === "variety" ? "catalog.addingVariety" : "catalog.addingStrain", {
          parent: parentPath,
        })}
      </p>
      <div className="grid gap-2 sm:grid-cols-3">
        <Field label={t("crops.form.code")}>
          {(props) => (
            <input
              {...props}
              className={FIELD_CONTROL_CLASS}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              required
            />
          )}
        </Field>
        <Field label={t("crops.form.nameEn")}>
          {(props) => (
            <input
              {...props}
              className={FIELD_CONTROL_CLASS}
              value={nameEn}
              onChange={(e) => setNameEn(e.target.value)}
              required
            />
          )}
        </Field>
        <Field label={t("crops.form.nameAr")}>
          {(props) => (
            <input
              {...props}
              className={FIELD_CONTROL_CLASS}
              value={nameAr}
              dir="rtl"
              onChange={(e) => setNameAr(e.target.value)}
            />
          )}
        </Field>
      </div>
      {mutation.isError ? (
        <p role="alert" className="text-xs text-ap-crit">
          {apiMsg(mutation.error)}
        </p>
      ) : null}
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={mutation.isPending}>
          {mutation.isPending ? t("crops.form.saving") : t("crops.form.save")}
        </Button>
        <Button variant="ghost" size="sm" onClick={onClose} disabled={mutation.isPending}>
          {t("crops.form.cancel")}
        </Button>
      </div>
    </form>
  );
}
