import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { Field, FIELD_CONTROL_CLASS } from "./Field";

describe("Field", () => {
  it("associates the label with the control", () => {
    render(
      <Field label="Farm code">
        {(props) => <input {...props} className={FIELD_CONTROL_CLASS} defaultValue="BSH-01" />}
      </Field>,
    );
    expect(screen.getByLabelText("Farm code")).toHaveValue("BSH-01");
  });

  // The required marker is decoration. Folding it into the label text makes
  // the accessible name "Farm code *" and breaks every getByLabelText call.
  it("keeps the required asterisk out of the label text", () => {
    render(
      <Field label="Farm code" required>
        {(props) => <input {...props} required />}
      </Field>,
    );
    const input = screen.getByLabelText("Farm code");
    expect(input).toBeRequired();
    expect(input).toHaveAccessibleName("Farm code");
  });

  // Help text inside a <label> pollutes the accessible name — the reason this
  // component renders it as a sibling and wires it via aria-describedby.
  it("keeps help text out of the accessible name", () => {
    render(
      <Field label="Farm code" help="Unique within the tenant.">
        {(props) => <input {...props} />}
      </Field>,
    );
    const input = screen.getByLabelText("Farm code");
    expect(input).toHaveAccessibleName("Farm code");
    expect(input).toHaveAccessibleDescription("Unique within the tenant.");
  });

  it("marks the control invalid and describes the error", () => {
    render(
      <Field label="Area" error="Area must be greater than zero.">
        {(props) => <input {...props} />}
      </Field>,
    );
    const input = screen.getByLabelText("Area");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("Area must be greater than zero.");
  });

  it("describes with both help and error when each is present", () => {
    render(
      <Field label="Area" help="In hectares." error="Too small.">
        {(props) => <input {...props} />}
      </Field>,
    );
    expect(screen.getByLabelText("Area")).toHaveAccessibleDescription("In hectares. Too small.");
  });
});
