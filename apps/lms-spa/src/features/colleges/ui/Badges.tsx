/**
 * Badges, status chips, provenance and verification marks (components.js badge / statusBadge / statusChip /
 * provenance / valueWithBasis / verifiedBadge / chip). Always text + colour, never colour alone.
 *
 *   <StatusChip status={row.status} size="sm" />          // performance / assignment / follow-up status
 *   <StatusBadge kind="op_status" value={college.op_status} />
 *   <ValueWithBasis value={college.strength} />            // "1,240  ≈ Estimated"
 *   <VerifiedBadge state="verified" source={url} date={on} by={who} />
 */
import type { ReactNode } from "react";
import { fmt } from "../lib/fmt";
import type { Basis, ValueBasis } from "../lib/types";
import { cx } from "./context";
import { Icon, type IconName } from "./Icon";
import { BASIS_META, CHIP_ICON, DIAG_TIPS, STATUS_KINDS, TONES, humanize, statusMeta, type StatusKind, type Tone } from "./status";

const toneOf = (t: string | undefined): Tone => (TONES.includes(t as Tone) ? (t as Tone) : "neutral");

export function Badge({ tone = "neutral", dot, title, children }: { tone?: Tone; dot?: boolean; title?: string; children: ReactNode }) {
  return (
    <span className={cx("td-badge", `td-badge--${toneOf(tone)}`, dot && "td-badge--dot")} title={title}>
      {children}
    </span>
  );
}

/** Kind-specific badge: kind = exam_state | op_status | on_track | followup | person_status | diagnosis. */
export function StatusBadge({ kind, value }: { kind: StatusKind; value: string | boolean | null | undefined }) {
  let v: string | null | undefined = typeof value === "boolean" ? (value ? "on_track" : "behind") : value;
  if (kind === "on_track" && (v === null || v === undefined || v === "")) v = "no_target";
  if (kind === "op_status" && !v) v = "pending";
  if (kind === "exam_state" && !v) v = "unknown";
  const hit = v ? STATUS_KINDS[kind]?.[v] : undefined;
  if (!hit) {
    if (v === null || v === undefined || v === "") return <span className="td-badge td-badge--ghost">—</span>;
    return <Badge>{humanize(String(v))}</Badge>;
  }
  return (
    <span className={cx("td-badge", `td-badge--${hit[1]}`, "td-badge--dot")} data-kind={kind} data-value={v} title={kind === "diagnosis" ? DIAG_TIPS[v!] : undefined}>
      {hit[0]}
    </span>
  );
}

/** Performance / assignment / verification / follow-up status (THE vocabulary in ui/status.ts). */
export function StatusChip({ status, label, title, size }: { status: string | null | undefined; label?: string; title?: string; size?: "sm" }) {
  if (status === null || status === undefined || status === "") return <span className="td-badge td-badge--ghost">—</span>;
  const meta = statusMeta(status);
  const ic = CHIP_ICON[status];
  return (
    <span
      className={cx("td-badge", `td-badge--${meta.tone}`, ic ? "td-badge--icon" : "td-badge--dot", size === "sm" && "td-badge--sm", "td-status")}
      title={title || meta.tip || undefined}
      data-status={status}
    >
      {ic ? <Icon name={ic} size={12} /> : null}
      <span>{label ?? meta.label}</span>
    </span>
  );
}

/** Provenance tag: Verified / ≈ Estimated / Pending verification. */
export function Provenance({ basis }: { basis: Basis | string | null | undefined }) {
  const b = BASIS_META[basis as keyof typeof BASIS_META] ?? BASIS_META.pending;
  return (
    <span className={cx("td-prov", `td-prov--${b.cls}`)} title={b.tip} role="note" aria-label={b.tip}>
      {b.icon ? <Icon name={b.icon} size={12} /> : null}
      <span>{b.label}</span>
    </span>
  );
}

/** A number with its provenance; unknown values show "—" + Pending. */
export function ValueWithBasis({ value, format = fmt.num }: { value: ValueBasis | number | null | undefined; format?: (n: number) => string }) {
  const v = value && typeof value === "object" ? value.value : value;
  const basis = value && typeof value === "object" ? value.basis : null;
  const unknown = v === null || v === undefined || Number.isNaN(v);
  return (
    <span className={cx("td-vb", unknown && "td-vb--unknown")}>
      <span className="td-vb__value td-num">{unknown ? "—" : format(v as number)}</span>
      <Provenance basis={unknown ? "pending" : basis || "pending"} />
    </span>
  );
}

/** Field verification mark (colleges' verified_fields, contacts). */
export function VerifiedBadge({ state = "missing", source, date, by }: { state?: "verified" | "unverified" | "missing" | string; source?: string | null; date?: string | null; by?: string | null }) {
  const st = state === "verified" || state === "unverified" || state === "missing" ? state : "unverified";
  const parts: string[] = [];
  if (date) parts.push(fmt.date(date));
  if (source) parts.push(String(source).replace(/^https?:\/\//, "").slice(0, 60));
  const tip =
    st === "verified"
      ? `Verified${date ? ` on ${fmt.date(date)}` : ""}${by ? ` by ${by}` : ""}${source ? ` · source: ${source}` : ""}`
      : st === "unverified"
        ? "Unverified — entered without a confirmed source. Check before relying on it."
        : "Missing — no value recorded yet.";
  return (
    <span className={cx("td-verify", `td-verify--${st}`)} title={tip} aria-label={tip}>
      <Icon name={st === "verified" ? "check" : st === "unverified" ? "warn" : "info"} size={12} />
      <span>{st === "verified" ? "Verified" : st === "unverified" ? "Unverified" : "Missing"}</span>
      {st === "verified" && parts.length ? <span className="td-verify__meta">{parts.join(" · ")}</span> : null}
    </span>
  );
}

/** Filter / choice pill; clickable with onClick, removable with onRemove. */
export function Chip({
  label,
  tone = "neutral",
  active,
  icon,
  onClick,
  onRemove,
}: {
  label: ReactNode;
  tone?: Tone;
  active?: boolean;
  icon?: IconName;
  onClick?: () => void;
  onRemove?: () => void;
}) {
  const cls = cx("td-chip2", `td-chip2--${toneOf(tone)}`, active && "is-active");
  const inner = (
    <>
      {icon ? <Icon name={icon} size={14} /> : null}
      <span>{label}</span>
      {onRemove ? (
        <button
          type="button"
          className="td-chip2__x"
          aria-label={`Remove ${typeof label === "string" ? label : "filter"}`}
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
        >
          <Icon name="close" size={12} />
        </button>
      ) : null}
    </>
  );
  if (onClick)
    return (
      <button type="button" className={cls} onClick={onClick} aria-pressed={active === undefined ? undefined : !!active}>
        {inner}
      </button>
    );
  return <span className={cls}>{inner}</span>;
}
