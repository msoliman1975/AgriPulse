import clsx from "clsx";
import type { ReactNode } from "react";
import { Link, type LinkProps } from "react-router-dom";

import { BUTTON_BASE_CLASS, SIZE_CLASS, VARIANT_CLASS } from "./buttonStyles";
import type { ButtonSize, ButtonVariant } from "./buttonStyles";

interface LinkButtonProps extends Omit<LinkProps, "className"> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  className?: string;
  children: ReactNode;
}

/*
 * A router <Link> wearing <Button>'s clothes.
 *
 * This component is why <Button> had zero importers: roughly half the
 * "buttons" in the app are navigations, and a <Link> can't be a <button>.
 * Every one of those call sites hand-rolled `className="bg-ap-primary px-3
 * py-1.5 …"` because the primitive didn't fit, and the drift compounded from
 * there. Routing them through here keeps one source of truth for button
 * styling while preserving real anchor semantics (middle-click, ⌘-click,
 * "copy link address").
 */
export function LinkButton({
  variant = "primary",
  size = "md",
  className,
  children,
  ...rest
}: LinkButtonProps): ReactNode {
  return (
    <Link
      className={clsx(BUTTON_BASE_CLASS, VARIANT_CLASS[variant], SIZE_CLASS[size], className)}
      {...rest}
    >
      {children}
    </Link>
  );
}
