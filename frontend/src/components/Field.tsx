import clsx from "clsx";
import { useId, type ReactNode } from "react";

interface FieldProps {
  label: ReactNode;
  /** Rendered below the control. Kept OUTSIDE the <label> element on purpose:
   *  help text inside a <label> pollutes the field's accessible name. */
  help?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  className?: string;
  /** Receives the wiring the control needs to be announced correctly. */
  children: (props: {
    id: string;
    "aria-describedby": string | undefined;
    "aria-invalid": boolean | undefined;
  }) => ReactNode;
}

/*
 * One form field, replacing seven independent local `Field` components
 * (TenantCreatePage, DecisionTreeCreatePage, PlanTemplateEditorPage,
 * SignalsConfigPage, ManagePanel, FarmDrawer, ValueInput).
 *
 * The render-prop is what makes the a11y wiring unskippable: the control
 * cannot be rendered without receiving its id and aria-describedby.
 */
export function Field({
  label,
  help,
  error,
  required,
  className,
  children,
}: FieldProps): ReactNode {
  const id = useId();
  const helpId = help ? `${id}-help` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [helpId, errorId].filter(Boolean).join(" ") || undefined;

  return (
    <div className={clsx("flex flex-col gap-1", className)}>
      <label htmlFor={id} className="text-xs font-medium text-ap-ink">
        {label}
        {required ? (
          <span className="ms-0.5 text-ap-crit" aria-hidden="true">
            *
          </span>
        ) : null}
      </label>
      {children({
        id,
        "aria-describedby": describedBy,
        "aria-invalid": error ? true : undefined,
      })}
      {help ? (
        <p id={helpId} className="text-[11px] text-ap-muted">
          {help}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className="text-[11px] text-ap-crit">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/** The shared input styling, for controls rendered inside a <Field>. */
export const FIELD_CONTROL_CLASS =
  "w-full rounded-md border border-ap-line bg-ap-panel px-3 py-1.5 text-sm text-ap-ink " +
  "focus:border-ap-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-ap-primary " +
  "disabled:cursor-not-allowed disabled:opacity-60 aria-[invalid=true]:border-ap-crit";
