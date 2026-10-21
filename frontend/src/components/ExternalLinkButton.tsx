import clsx from "clsx";
import type { AnchorHTMLAttributes, ReactNode } from "react";

import { BUTTON_BASE_CLASS, SIZE_CLASS, VARIANT_CLASS } from "./buttonStyles";
import type { ButtonSize, ButtonVariant } from "./buttonStyles";

interface ExternalLinkButtonProps extends Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> {
  href: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
  children: ReactNode;
}

/*
 * <LinkButton> for destinations outside the app.
 *
 * <LinkButton> wraps a router <Link>, which rewrites an absolute URL into a
 * client-side route and lands on the SPA 404. Off-app links (the docs site,
 * the marketing site) need a plain anchor, and they all want the same
 * `target="_blank"` + `rel="noopener noreferrer"` pair — leaving that to each
 * call site is how one of them ends up without the rel.
 */
export function ExternalLinkButton({
  href,
  variant = "secondary",
  size = "md",
  className,
  children,
  ...rest
}: ExternalLinkButtonProps): ReactNode {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={clsx(BUTTON_BASE_CLASS, VARIANT_CLASS[variant], SIZE_CLASS[size], className)}
      {...rest}
    >
      {children}
    </a>
  );
}
