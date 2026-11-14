/**
 * Buttons (components.js `button`): tones primary | secondary | ghost | danger | accent, sizes sm | md.
 * Icon-only when there is no label (then `ariaLabel` is required for screen readers).
 *
 *   <Button tone="primary" icon="plus" onClick={add}>Add college</Button>
 *   <Button icon="close" tone="ghost" ariaLabel="Close" />
 *   <LinkButton to={portalPath.colleges} icon="college">Browse colleges</LinkButton>
 */
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Link } from "react-router";
import { cx } from "./context";
import { Icon, type IconName } from "./Icon";

export type ButtonTone = "primary" | "secondary" | "ghost" | "danger" | "accent";

export interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "type"> {
  tone?: ButtonTone;
  size?: "sm" | "md";
  icon?: IconName;
  /** trailing icon */
  iconEnd?: IconName;
  ariaLabel?: string;
  type?: "button" | "submit" | "reset";
  /** shows the busy spinner and disables the button */
  busy?: boolean;
  children?: ReactNode;
}

export function buttonClass({ tone = "secondary", size, iconOnly, busy, className }: { tone?: ButtonTone; size?: "sm" | "md"; iconOnly?: boolean; busy?: boolean; className?: string }): string {
  return cx("td-btn", `td-btn--${tone}`, size && size !== "md" && `td-btn--${size}`, iconOnly && "td-btn--icon", busy && "is-busy", className);
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { tone = "secondary", size, icon, iconEnd, ariaLabel, type = "button", busy, className, children, title, disabled, ...rest },
  ref,
) {
  const iconOnly = children === undefined || children === null || children === false;
  return (
    <button
      ref={ref}
      type={type}
      className={buttonClass({ tone, size, iconOnly, busy, className })}
      title={title ?? (iconOnly ? ariaLabel : undefined)}
      aria-label={ariaLabel ?? (iconOnly ? title : undefined)}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      {...rest}
    >
      {icon ? <Icon name={icon} size={size === "sm" ? 16 : 18} /> : null}
      {iconOnly ? null : <span>{children}</span>}
      {iconEnd ? <Icon name={iconEnd} size={size === "sm" ? 14 : 16} /> : null}
    </button>
  );
});

export interface LinkButtonProps {
  to: string;
  tone?: ButtonTone;
  size?: "sm" | "md";
  icon?: IconName;
  ariaLabel?: string;
  className?: string;
  /** external / full page load (an LMS page outside the portal, a download) */
  reload?: boolean;
  target?: string;
  rel?: string;
  children?: ReactNode;
}

/** A link styled as a button (client navigation inside the SPA unless `reload`). */
export function LinkButton({ to, tone = "secondary", size, icon, ariaLabel, className, reload, target, rel, children }: LinkButtonProps) {
  const iconOnly = children === undefined || children === null;
  const cls = buttonClass({ tone, size, iconOnly, className });
  const inner = (
    <>
      {icon ? <Icon name={icon} size={size === "sm" ? 16 : 18} /> : null}
      {iconOnly ? null : <span>{children}</span>}
    </>
  );
  if (reload || /^(https?:|mailto:|tel:)/.test(to)) {
    return (
      <a href={to} className={cls} aria-label={ariaLabel} title={iconOnly ? ariaLabel : undefined} target={target} rel={rel}>
        {inner}
      </a>
    );
  }
  return (
    <Link to={to} className={cls} aria-label={ariaLabel} title={iconOnly ? ariaLabel : undefined}>
      {inner}
    </Link>
  );
}
