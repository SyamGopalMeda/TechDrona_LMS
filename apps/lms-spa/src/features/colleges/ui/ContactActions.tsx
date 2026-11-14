/**
 * Call / WhatsApp / email / copy buttons for a person or contact (components.js contactActions).
 *
 *   <ContactActions phone={p.phone} email={p.email} whatsapp name={p.full_name} />
 *   <ContactActions phone={c.phone} compact />          // icon-only (tables)
 */
import { Icon } from "./Icon";
import { Button } from "./Button";
import { cx } from "./context";
import { toast } from "./Overlay";

/** `tel:` link for a phone number ("+91 98765 43210" → "tel:+919876543210"), null when there are no digits. */
export function telHref(p: string | null | undefined): string | null {
  const d = String(p ?? "").replace(/[^\d+]/g, "");
  return d ? `tel:${d}` : null;
}

/** wa.me number: 10 digits get the 91 country code; a trunk 0 is replaced. null when it cannot be a mobile. */
export function waNumber(p: string | null | undefined): string | null {
  let d = String(p ?? "").replace(/\D/g, "");
  if (d.length === 10) d = `91${d}`;
  if (d.length === 11 && d.startsWith("0")) d = `91${d.slice(1)}`;
  return d.length >= 11 ? d : null;
}

export function whatsappHref(p: string | null | undefined): string | null {
  const n = waNumber(p);
  return n ? `https://wa.me/${n}` : null;
}

async function copyText(t: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(t);
    return true;
  } catch {
    return false;
  }
}

function ActionLink({ href, icon, label, aria, compact, external }: { href: string | null; icon: string; label: string; aria: string; compact?: boolean; external?: boolean }) {
  if (!href) {
    return (
      <span className={cx("td-btn", "td-btn--ghost", "td-btn--sm", "is-disabled", compact && "td-btn--icon")} aria-disabled="true" title={`No ${label.toLowerCase()} recorded`}>
        <Icon name={icon} size={16} />
        {compact ? null : <span>No {label.toLowerCase()}</span>}
      </span>
    );
  }
  return (
    <a
      className={cx("td-btn", "td-btn--ghost", "td-btn--sm", compact && "td-btn--icon")}
      href={href}
      aria-label={aria}
      title={aria}
      target={external ? "_blank" : undefined}
      rel={external ? "noopener noreferrer" : undefined}
    >
      <Icon name={icon} size={16} />
      {compact ? null : <span>{label}</span>}
    </a>
  );
}

export function ContactActions({ phone, email, compact, whatsapp, name }: { phone?: string | null; email?: string | null; compact?: boolean; whatsapp?: boolean; name?: string | null }) {
  const who = name ? ` ${name}` : "";
  const val = [phone, email].filter(Boolean).join(" · ");
  return (
    <div className={cx("td-contact", compact && "td-contact--compact")}>
      <ActionLink href={telHref(phone)} icon="phone" label="Call" aria={`Call${who} ${phone ?? ""}`.trim()} compact={compact} />
      {whatsapp ? <ActionLink href={whatsappHref(phone)} icon="external" label="WhatsApp" aria={`WhatsApp${who}`} compact={compact} external /> : null}
      <ActionLink href={email ? `mailto:${email}` : null} icon="mail" label="Email" aria={`Email${who} ${email ?? ""}`.trim()} compact={compact} />
      {val ? (
        <Button
          icon="link"
          tone="ghost"
          size="sm"
          ariaLabel={`Copy contact details${who}`}
          title="Copy"
          onClick={async () => toast((await copyText(val)) ? `Copied ${val}` : "Could not copy — select the text instead", "info")}
        />
      ) : null}
    </div>
  );
}
