"use client";

import { useState } from "react";
import { Badge, Button, Checkbox, Dialog, FormField, Input, LoadingBlock, PageHeader, Pagination, Select, Table, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { Schema } from "@/lib/api-types";
import { ActionDialog, FilterBar, KeyValueList, StateBadge, TextArea } from "@/features/admin/components/console-ui";
import { cleanQuery, formatDate, formatINR, humanize, personLabel, shortRef, toOutcome, useCursorList, type MutationOutcome } from "@/features/admin/lib/console";

/* ------------------------------------------------------------------ shared */

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** ₹ text → integer paise (NaN when not a number). */
export const toPaise = (rupees: string) => (rupees.trim() === "" ? Number.NaN : Math.round(Number(rupees) * 100));

/** Start of a calendar day in IST (the api takes datetimes). */
const istDayStart = (d: string) => `${d}T00:00:00+05:30`;
/** End of a calendar day in IST, for "valid until" dates chosen by day. */
const istDayEnd = (d: string) => `${d}T23:59:59+05:30`;

/* ---------------------------------------------------------------- products */

/** verified: app/modules/commerce/admin.py plan_json price(). */
export interface CatalogPrice {
  price_id: string;
  amount_paise: number;
  currency?: string;
  tax_inclusive?: boolean;
  is_recurring?: boolean;
  valid_from: string;
  valid_until: string | null;
  is_active?: boolean;
}

/** verified: app/modules/commerce/admin.py plan_json. */
export interface CatalogPlan {
  plan_id: string;
  code: string;
  billing_type: "one_time" | "recurring" | string;
  interval_unit: string | null;
  interval_count: number | null;
  access_duration_days: number | null;
  status: string;
  prices: CatalogPrice[];
}

/** verified: app/modules/commerce/admin.py product_json (GET finance/products → catalogue(include_drafts=True), {data, page}). */
export interface CatalogProduct {
  product_id: string;
  sku: string;
  name: string;
  product_kind: string;
  description_md: string | null;
  sac_code: string;
  gst_rate: string;
  refund_policy_key: string;
  status: string;
  unlocks?: { item_type: string; ref_id: string | null; feature_key: string | null; quantity: number | null }[];
  plans?: CatalogPlan[];
}

/** schemas.ProductIn product_kind. */
const PRODUCT_KINDS = ["free_resource", "free_course", "course", "bundle", "subscription_plan", "placement_package", "mock_pack"] as const;
/** schemas.ProductItemIn item_type. */
const ITEM_TYPES = ["course", "test", "company_path", "topic_practice", "feature"] as const;

export const productLabel = (p: Pick<CatalogProduct, "name" | "sku">) => `${p.name} (${p.sku})`;

/**
 * Refund rules the api knows (schemas.ProductIn default; the refund engine applies the published
 * 7-day / 20 % rule). Shown as words, stored as the key.
 */
export const REFUND_RULES: { value: string; label: string }[] = [{ value: "standard_7d_20pct", label: "Standard: full refund within 7 days if under 20 % is used" }];
export const refundRuleLabel = (key: string | null | undefined) => REFUND_RULES.find((r) => r.value === key)?.label ?? humanize(key);

/** "Course #9F3C21AB", "Feature: Mock interview ×5" for a product unlock. */
const unlockLabel = (u: NonNullable<CatalogProduct["unlocks"]>[number]) =>
  `${humanize(u.item_type)}${u.feature_key ? `: ${humanize(u.feature_key)}` : u.ref_id ? ` ${shortRef(u.ref_id)}` : ""}${u.quantity ? ` ×${u.quantity}` : ""}`;

const planTerm = (pl: CatalogPlan) =>
  pl.billing_type === "recurring" ? `Every ${pl.interval_count ?? 1} ${pl.interval_unit ?? "month"}${(pl.interval_count ?? 1) > 1 ? "s" : ""}` : pl.access_duration_days ? `${pl.access_duration_days} days access` : "One time";

/** The price in force now (valid window contains now), else the latest one. */
function currentPrice(pl: CatalogPlan, now: number): CatalogPrice | undefined {
  const live = pl.prices.filter((p) => Date.parse(p.valid_from) <= now && (!p.valid_until || Date.parse(p.valid_until) > now));
  return live[live.length - 1] ?? pl.prices[pl.prices.length - 1];
}

interface ItemDraft {
  item_type: (typeof ITEM_TYPES)[number];
  ref: string;
  quantity: string;
}

const emptyProduct = { sku: "", name: "", product_kind: "course", description_md: "", sac_code: "9992", gst_rate: "18", refund_policy_key: "standard_7d_20pct", status: "draft" };

/** Client checks mirroring schemas.ProductItemIn: feature items need a feature key, others a ref id. */
export function validateItems(items: ItemDraft[]): string | null {
  for (const [i, it] of items.entries()) {
    const n = i + 1;
    if (it.item_type === "feature" ? !/^[a-z][a-z0-9_]{1,62}$/.test(it.ref.trim()) : !UUID_RE.test(it.ref.trim())) return it.item_type === "feature" ? `Unlock ${n}: enter a feature key (lower_case).` : `Unlock ${n}: enter the full ${humanize(it.item_type).toLowerCase()} id.`;
    if (it.quantity.trim() && !(Number.isInteger(Number(it.quantity)) && Number(it.quantity) > 0)) return `Unlock ${n}: quantity must be a whole number above 0.`;
  }
  return null;
}

/** FIN-002 products, plans and prices (COM-20..24). Price decreases over 20 % (or with live subscriptions) need a second admin. */
export function Products() {
  const toast = useToast();
  const list = useCursorList<CatalogProduct>("finance/products");
  const [openId, setOpenId] = useState<string | null>(null);
  const open = list.rows?.find((p) => p.product_id === openId) ?? null;
  const [dialog, setDialog] = useState<null | { kind: "create" } | { kind: "edit"; product: CatalogProduct } | { kind: "plan"; product: CatalogProduct } | { kind: "price"; plan: CatalogPlan }>(null);
  const [form, setForm] = useState(emptyProduct);
  const [items, setItems] = useState<ItemDraft[]>([]);
  const [edit, setEdit] = useState({ name: "", description_md: "", status: "draft" });
  const [plan, setPlan] = useState({ code: "", billing_type: "one_time", access_duration_days: "365", interval_unit: "month", interval_count: "1" });
  const [price, setPrice] = useState({ amount: "", valid_from: "", valid_until: "", reason: "" });
  const [now] = useState(() => Date.now());
  const [retireAck, setRetireAck] = useState(false);
  const close = () => setDialog(null);
  // Retiring takes a product off sale: ask for an explicit confirmation (audit 0.7).
  const retiring = dialog?.kind === "edit" && edit.status === "retired" && dialog.product.status !== "retired";
  const set = (k: keyof typeof emptyProduct) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const cols: Column<CatalogProduct>[] = [
    { key: "sku", header: "SKU", cell: (p) => <span className="font-mono text-xs">{p.sku}</span> },
    { key: "name", header: "Name", cell: (p) => p.name },
    { key: "kind", header: "Kind", cell: (p) => humanize(p.product_kind) },
    { key: "gst", header: "GST", align: "right", cell: (p) => `${Number(p.gst_rate)}%` },
    { key: "plans", header: "Plans", align: "right", cell: (p) => String(p.plans?.length ?? 0) },
    { key: "status", header: "Status", cell: (p) => <StateBadge state={p.status} /> },
    {
      key: "act",
      header: <span className="sr-only">Actions</span>,
      cell: (p) => (
        <Button size="sm" variant="secondary" onClick={() => setOpenId(p.product_id)} aria-label={`Manage ${p.sku}`}>
          Manage
        </Button>
      ),
    },
  ];

  const planCols: Column<CatalogPlan>[] = [
    { key: "code", header: "Plan", cell: (pl) => <span className="font-mono text-xs">{pl.code}</span> },
    { key: "term", header: "Term", cell: (pl) => planTerm(pl) },
    { key: "price", header: "Current price (incl. GST)", align: "right", cell: (pl) => formatINR(currentPrice(pl, now)?.amount_paise) },
    {
      key: "history",
      header: "Price history",
      cell: (pl) =>
        pl.prices.length ? (
          <ul className="space-y-0.5 text-xs">
            {pl.prices.map((pr) => (
              <li key={pr.price_id}>
                {formatINR(pr.amount_paise)} · {formatDate(pr.valid_from)} – {pr.valid_until ? formatDate(pr.valid_until) : "open"}
              </li>
            ))}
          </ul>
        ) : (
          <span className="text-fg-muted">No price yet</span>
        ),
    },
    { key: "status", header: "Status", cell: (pl) => <StateBadge state={pl.status} /> },
    {
      key: "act",
      header: <span className="sr-only">Actions</span>,
      cell: (pl) => (
        <Button
          size="sm"
          variant="secondary"
          onClick={() => {
            setPrice({ amount: "", valid_from: "", valid_until: "", reason: "" });
            setDialog({ kind: "price", plan: pl });
          }}
          aria-label={`Add price to ${pl.code}`}
        >
          Add price
        </Button>
      ),
    },
  ];

  const pricePlan = dialog?.kind === "price" ? dialog.plan : null;
  const priceCurrent = pricePlan ? currentPrice(pricePlan, now) : undefined;
  const pricePaise = toPaise(price.amount);
  const bigDecrease = !!priceCurrent && Number.isFinite(pricePaise) && pricePaise < priceCurrent.amount_paise * 0.8;

  return (
    <div>
      <PageHeader
        title="Products & prices"
        description="Prices are GST-inclusive. A price cut of more than 20 % needs a second admin."
        actions={
          <Button
            onClick={() => {
              setForm(emptyProduct);
              setItems([]);
              setDialog({ kind: "create" });
            }}
          >
            New product
          </Button>
        }
      />
      <Table caption="Products" columns={cols} rows={list.rows} rowKey={(p) => p.product_id} loading={list.loading} error={list.error} onRetry={() => void list.reload()} empty={{ title: "No products yet", description: "Create a product, then add plans and prices.", icon: "card" }} />

      {/* Product details open in a dialog (bottom sheet on phones) instead of a card below the table; it steps aside while an edit dialog is open. */}
      <Dialog
        open={open !== null && dialog === null}
        onClose={() => setOpenId(null)}
        size="xl"
        title={open ? productLabel(open) : "Product"}
        footer={
          open ? (
            <>
              <Button
                variant="secondary"
                onClick={() => {
                  setEdit({ name: open.name, description_md: open.description_md ?? "", status: open.status });
                  setDialog({ kind: "edit", product: open });
                }}
              >
                Edit product
              </Button>
              <Button
                onClick={() => {
                  setPlan({ code: "", billing_type: "one_time", access_duration_days: "365", interval_unit: "month", interval_count: "1" });
                  setDialog({ kind: "plan", product: open });
                }}
              >
                Add plan
              </Button>
            </>
          ) : null
        }
      >
        {open ? (
          <div className="space-y-4">
            <KeyValueList
              items={[
                { label: "Kind", value: humanize(open.product_kind) },
                { label: "Status", value: <StateBadge state={open.status} /> },
                { label: "SAC / GST", value: `${open.sac_code} · ${Number(open.gst_rate)}%` },
                { label: "Refund rule", value: refundRuleLabel(open.refund_policy_key) },
                { label: "Unlocks", value: open.unlocks?.length ? open.unlocks.map(unlockLabel).join(", ") : "Nothing yet", wide: true },
              ]}
            />
            <Table caption={`Plans of ${open.sku}`} showCaption columns={planCols} rows={open.plans ?? []} rowKey={(pl) => pl.plan_id} empty={{ title: "No plans", description: "Add a plan to sell this product.", icon: "card" }} />
          </div>
        ) : null}
      </Dialog>

      <ActionDialog
        open={dialog?.kind === "create"}
        onClose={close}
        title="New product"
        submitLabel="Create product"
        validate={() => {
          if (!/^[A-Za-z0-9][A-Za-z0-9-]{1,63}$/.test(form.sku.trim())) return "SKU: 2–64 letters, digits or hyphens.";
          if (form.name.trim().length < 2) return "Enter a name.";
          if (!/^[0-9]{4,8}$/.test(form.sac_code.trim())) return "SAC code: 4–8 digits.";
          const g = Number(form.gst_rate);
          if (form.gst_rate.trim() === "" || !(g >= 0 && g <= 28)) return "GST rate must be 0–28 %.";
          return validateItems(items);
        }}
        onSubmit={async () =>
          toOutcome(
            await api.post(
              "finance/products",
              {
                sku: form.sku.trim(),
                name: form.name.trim(),
                product_kind: form.product_kind as Schema<"ProductIn">["product_kind"],
                description_md: form.description_md.trim() || null,
                sac_code: form.sac_code.trim(),
                gst_rate: form.gst_rate.trim(),
                refund_policy_key: form.refund_policy_key.trim() || "standard_7d_20pct",
                status: form.status as "draft" | "active",
                items: items.map((it) => ({
                  item_type: it.item_type,
                  ref_id: it.item_type === "feature" ? null : it.ref.trim(),
                  feature_key: it.item_type === "feature" ? it.ref.trim() : null,
                  quantity: it.quantity.trim() ? Number(it.quantity) : null,
                })),
              } satisfies Schema<"ProductIn">,
              { idempotencyKey: true },
            ),
          )
        }
        onDone={() => {
          toast.show({ title: "Product created.", tone: "success" });
          void list.reload();
        }}
      >
        <FormField label="SKU" required>{(f) => <Input {...f} value={form.sku} onChange={set("sku")} />}</FormField>
        <FormField label="Name" required>{(f) => <Input {...f} value={form.name} onChange={set("name")} />}</FormField>
        <FormField label="Kind" required>{(f) => <Select {...f} value={form.product_kind} onChange={set("product_kind")} options={PRODUCT_KINDS.map((k) => ({ value: k, label: humanize(k) }))} />}</FormField>
        <FormField label="SAC code">{(f) => <Input {...f} inputMode="numeric" value={form.sac_code} onChange={set("sac_code")} />}</FormField>
        <FormField label="GST rate (%)">{(f) => <Input {...f} inputMode="decimal" value={form.gst_rate} onChange={set("gst_rate")} />}</FormField>
        <FormField label="Refund rule" hint="The refund rule shown to buyers at checkout.">
          {(f) => <Select {...f} value={form.refund_policy_key} onChange={set("refund_policy_key")} options={REFUND_RULES.some((r) => r.value === form.refund_policy_key) ? REFUND_RULES : [...REFUND_RULES, { value: form.refund_policy_key, label: humanize(form.refund_policy_key) }]} />}
        </FormField>
        <FormField label="Status">{(f) => <Select {...f} value={form.status} onChange={set("status")} options={["draft", "active"].map((s) => ({ value: s, label: humanize(s) }))} />}</FormField>
        <FormField label="Description">{(f) => <TextArea {...f} value={form.description_md} onChange={set("description_md")} maxLength={20000} />}</FormField>
        <fieldset className="space-y-2 rounded-lg border border-line p-3">
          <legend className="px-1 text-sm font-semibold text-fg">What the product unlocks</legend>
          {items.length === 0 ? <p className="text-sm text-fg-muted">Nothing yet.</p> : null}
          {items.map((it, i) => (
            <div key={i} className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_2fr_1fr_auto] sm:items-end">
              <FormField label={`Unlock ${i + 1} type`}>
                {(f) => <Select {...f} value={it.item_type} onChange={(e) => setItems((xs) => xs.map((x, j) => (j === i ? { ...x, item_type: e.target.value as ItemDraft["item_type"] } : x)))} options={ITEM_TYPES.map((t) => ({ value: t, label: humanize(t) }))} />}
              </FormField>
              <FormField label={it.item_type === "feature" ? `Unlock ${i + 1} feature key` : `Unlock ${i + 1} id`} hint={it.item_type === "feature" ? "e.g. mock_interview" : `Full ${humanize(it.item_type).toLowerCase()} id, from its page in Studio.`}>
                {(f) => <Input {...f} value={it.ref} onChange={(e) => setItems((xs) => xs.map((x, j) => (j === i ? { ...x, ref: e.target.value } : x)))} />}
              </FormField>
              <FormField label={`Unlock ${i + 1} quantity`}>
                {(f) => <Input {...f} inputMode="numeric" value={it.quantity} onChange={(e) => setItems((xs) => xs.map((x, j) => (j === i ? { ...x, quantity: e.target.value } : x)))} />}
              </FormField>
              <Button size="sm" variant="ghost" onClick={() => setItems((xs) => xs.filter((_, j) => j !== i))} aria-label={`Remove unlock ${i + 1}`}>
                Remove
              </Button>
            </div>
          ))}
          <Button size="sm" variant="secondary" onClick={() => setItems((xs) => [...xs, { item_type: "course", ref: "", quantity: "" }])}>
            Add unlock
          </Button>
        </fieldset>
      </ActionDialog>

      <ActionDialog
        open={dialog?.kind === "edit"}
        onClose={close}
        onOpen={() => setRetireAck(false)}
        title={`Edit ${dialog?.kind === "edit" ? dialog.product.name : ""}`}
        submitLabel={retiring ? "Retire product" : "Save"}
        danger={retiring}
        validate={() => (edit.name.trim().length < 2 ? "Enter a name." : retiring && !retireAck ? "Confirm that you want to retire this product." : null)}
        onSubmit={async () => {
          const p = (dialog as { product: CatalogProduct }).product;
          return toOutcome(
            await api.patch(`finance/products/${p.product_id}`, { name: edit.name.trim(), description_md: edit.description_md.trim() || null, status: edit.status as "draft" | "active" | "retired" } satisfies Schema<"ProductPatchIn">),
          );
        }}
        onDone={() => {
          toast.show({ title: "Product updated.", tone: "success" });
          void list.reload();
        }}
      >
        <FormField label="Name" required>{(f) => <Input {...f} value={edit.name} onChange={(e) => setEdit((x) => ({ ...x, name: e.target.value }))} />}</FormField>
        <FormField label="Status">{(f) => <Select {...f} value={edit.status} onChange={(e) => setEdit((x) => ({ ...x, status: e.target.value }))} options={["draft", "active", "retired"].map((s) => ({ value: s, label: humanize(s) }))} />}</FormField>
        {retiring ? (
          <div role="note" className="space-y-2 rounded-lg border border-warning-border bg-warning-subtle p-3 text-sm">
            <p className="font-semibold text-warning-fg">Retiring takes this product off sale</p>
            <p className="text-fg-secondary">It disappears from the catalogue and nobody can buy it. Check that no live campaign or coupon still points to it.</p>
            <Checkbox label="I understand — retire this product" checked={retireAck} onChange={(e) => setRetireAck(e.target.checked)} />
          </div>
        ) : null}
        <FormField label="Description">{(f) => <TextArea {...f} value={edit.description_md} onChange={(e) => setEdit((x) => ({ ...x, description_md: e.target.value }))} maxLength={20000} />}</FormField>
      </ActionDialog>

      <ActionDialog
        open={dialog?.kind === "plan"}
        onClose={close}
        title={`Add plan to ${dialog?.kind === "plan" ? dialog.product.sku : ""}`}
        submitLabel="Add plan"
        validate={() => {
          if (!/^[A-Za-z0-9][A-Za-z0-9_-]{1,63}$/.test(plan.code.trim())) return "Plan code: 2–64 letters, digits, _ or -.";
          if (plan.billing_type === "one_time") {
            const d = Number(plan.access_duration_days);
            return Number.isInteger(d) && d > 0 && d <= 3650 ? null : "Access days must be 1–3650.";
          }
          const c = Number(plan.interval_count);
          return Number.isInteger(c) && c >= 1 && c <= 12 ? null : "Interval count must be 1–12.";
        }}
        onSubmit={async () => {
          const p = (dialog as { product: CatalogProduct }).product;
          const oneTime = plan.billing_type === "one_time";
          return toOutcome(
            await api.post(
              `finance/products/${p.product_id}/plans`,
              {
                code: plan.code.trim(),
                billing_type: oneTime ? "one_time" : "recurring",
                access_duration_days: oneTime ? Number(plan.access_duration_days) : null,
                interval_unit: oneTime ? null : (plan.interval_unit as "month" | "year"),
                interval_count: oneTime ? null : Number(plan.interval_count),
              } satisfies Schema<"PlanIn">,
              { idempotencyKey: true },
            ),
          );
        }}
        onDone={() => {
          toast.show({ title: "Plan added. Add a price to start selling it.", tone: "success" });
          void list.reload();
        }}
      >
        <FormField label="Plan code" required>{(f) => <Input {...f} value={plan.code} onChange={(e) => setPlan((x) => ({ ...x, code: e.target.value }))} />}</FormField>
        <FormField label="Billing">{(f) => <Select {...f} value={plan.billing_type} onChange={(e) => setPlan((x) => ({ ...x, billing_type: e.target.value }))} options={[{ value: "one_time", label: "One time" }, { value: "recurring", label: "Recurring (UPI AutoPay)" }]} />}</FormField>
        {plan.billing_type === "one_time" ? (
          <FormField label="Access days" required>{(f) => <Input {...f} type="number" min={1} max={3650} value={plan.access_duration_days} onChange={(e) => setPlan((x) => ({ ...x, access_duration_days: e.target.value }))} />}</FormField>
        ) : (
          <>
            <FormField label="Interval">{(f) => <Select {...f} value={plan.interval_unit} onChange={(e) => setPlan((x) => ({ ...x, interval_unit: e.target.value }))} options={["month", "year"].map((u) => ({ value: u, label: humanize(u) }))} />}</FormField>
            <FormField label="Interval count" required>{(f) => <Input {...f} type="number" min={1} max={12} value={plan.interval_count} onChange={(e) => setPlan((x) => ({ ...x, interval_count: e.target.value }))} />}</FormField>
          </>
        )}
      </ActionDialog>

      <ActionDialog
        open={dialog?.kind === "price"}
        onClose={close}
        title={`New price for ${pricePlan?.code ?? ""}`}
        description={priceCurrent ? `Current price ${formatINR(priceCurrent.amount_paise)} (GST-inclusive).` : "This plan has no price yet."}
        submitLabel={bigDecrease ? "Submit for approval" : "Add price"}
        validate={() => {
          if (!Number.isFinite(pricePaise) || pricePaise <= 0) return "Enter the price in ₹.";
          if (price.valid_from && price.valid_until && price.valid_until < price.valid_from) return "Valid until must be after valid from.";
          return price.reason.trim().length < 3 ? "Give a reason (3+ characters)." : null;
        }}
        onSubmit={async () =>
          toOutcome(
            await api.post(
              `finance/plans/${pricePlan!.plan_id}/prices`,
              { amount_paise: pricePaise, valid_from: price.valid_from ? istDayStart(price.valid_from) : null, valid_until: price.valid_until ? istDayEnd(price.valid_until) : null, reason: price.reason.trim() } satisfies Schema<"PriceIn">,
              { idempotencyKey: true },
            ),
          )
        }
        onDone={(o) => {
          if (o.kind === "ok") toast.show({ title: "Price added.", tone: "success" });
          void list.reload();
        }}
      >
        <FormField label="Price (₹, incl. GST)" required>{(f) => <Input {...f} inputMode="decimal" value={price.amount} onChange={(e) => setPrice((x) => ({ ...x, amount: e.target.value }))} />}</FormField>
        <FormField label="Valid from" hint="Empty = now.">{(f) => <Input {...f} type="date" value={price.valid_from} onChange={(e) => setPrice((x) => ({ ...x, valid_from: e.target.value }))} />}</FormField>
        <FormField label="Valid until" hint="Empty = open-ended.">{(f) => <Input {...f} type="date" value={price.valid_until} onChange={(e) => setPrice((x) => ({ ...x, valid_until: e.target.value }))} />}</FormField>
        <FormField label="Reason" required>{(f) => <TextArea {...f} value={price.reason} onChange={(e) => setPrice((x) => ({ ...x, reason: e.target.value }))} maxLength={500} />}</FormField>
        {bigDecrease ? (
          <p className="text-sm text-info-fg">
            <span aria-hidden="true">ⓘ </span>This is a cut of more than 20 %: a second admin must approve it.
          </p>
        ) : null}
      </ActionDialog>
    </div>
  );
}

/* ----------------------------------------------------------------- coupons */

/** verified: app/modules/commerce/admin.py coupon_json (GET finance/coupons, {data, page}). */
export interface CouponRow {
  coupon_id: string;
  code: string;
  discount_type: "percent" | "flat" | "free_access" | string;
  percent_off: number | null;
  amount_off_paise: number | null;
  applicable_product_ids: string[];
  min_order_paise: number | null;
  max_redemptions: number | null;
  per_user_limit: number;
  redeemed_count: number;
  valid_from: string;
  valid_until: string | null;
  first_time_only: boolean;
  status: string;
  /** Pending `commerce.coupon.activate` approval for this coupon, or null (webstaff R6). */
  approval_request_id?: string | null;
}

/** policy.COUPON_DUAL_PERCENT / COUPON_DUAL_REDEMPTIONS (admin.coupon_needs_dual). */
const COUPON_DUAL_PERCENT = 50;
const COUPON_DUAL_REDEMPTIONS = 1000;

export function couponNeedsDual(discountType: string, percentOff: number | null, maxRedemptions: number | null): boolean {
  return discountType === "free_access" || (percentOff !== null && percentOff > COUPON_DUAL_PERCENT) || maxRedemptions === null || maxRedemptions > COUPON_DUAL_REDEMPTIONS;
}

const COUPON_ENDED = new Set(["expired", "retired", "archived"]);

const couponValue = (c: CouponRow) => (c.discount_type === "percent" ? `${c.percent_off}% off` : c.discount_type === "flat" ? `${formatINR(c.amount_off_paise)} off` : "Free access");

/**
 * POST finance/coupons answers 202 with the coupon (`status: "paused"`) plus the approval
 * envelope fields `approval_status`, `approval_request_id`, `action_type`,
 * `required_approver_role` and `expires_at` when it needs a second admin (COM-26,
 * webstaff R6). The coupon keeps its own `status`, so the api client returns the body as ok:
 * turn it into the dual-control outcome here, using the server's role and expiry.
 */
export type CouponCreateBody = CouponRow & { approval_status?: string; action_type?: string; required_approver_role?: string; expires_at?: string };

export function couponCreateOutcome(res: Awaited<ReturnType<typeof api.post<CouponCreateBody>>>): MutationOutcome<CouponRow> {
  if (res.kind === "ok" && res.status === 202 && res.data.approval_request_id) {
    const d = res.data;
    return {
      kind: "approval_pending",
      approval: {
        status: "approval_pending",
        approval_request_id: d.approval_request_id!,
        action_type: d.action_type ?? "commerce.coupon.activate",
        required_approver_role: d.required_approver_role ?? "super_admin",
        expires_at: d.expires_at ?? "",
      },
      requestId: res.requestId,
    };
  }
  return toOutcome(res);
}

const emptyCoupon = { code: "", discount_type: "percent", percent_off: "", amount_off: "", max_redemptions: "", per_user_limit: "1", min_order: "", valid_from: "", valid_until: "", first_time_only: false, reason: "" };

/** FIN-003 coupons (COM-25..27). Big or unlimited coupons are created paused until a second admin approves. */
export function Coupons() {
  const toast = useToast();
  const [status, setStatus] = useState("");
  // fin_coupons: server-side `status` filter and keyset paging (webstaff R6).
  const list = useCursorList<CouponRow>("finance/coupons", cleanQuery({ status }));
  const rows = list.rows;
  const [create, setCreate] = useState(false);
  const [form, setForm] = useState(emptyCoupon);
  const [productIds, setProductIds] = useState<string[]>([]);
  const products = useCursorList<CatalogProduct>(create ? "finance/products" : null);
  const [awaiting, setAwaiting] = useState<Set<string>>(() => new Set());
  const [edit, setEdit] = useState<CouponRow | null>(null);
  const [patch, setPatch] = useState({ status: "active", valid_until: "", max_redemptions: "" });
  const set = (k: keyof typeof emptyCoupon) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const pct = form.discount_type === "percent" && form.percent_off.trim() ? Number(form.percent_off) : null;
  const max = form.max_redemptions.trim() ? Number(form.max_redemptions) : null;
  const needsDual = couponNeedsDual(form.discount_type, pct, max);

  const cols: Column<CouponRow>[] = [
    { key: "code", header: "Code", cell: (c) => <span className="font-mono text-xs">{c.code}</span> },
    { key: "value", header: "Discount", cell: couponValue },
    { key: "used", header: "Redeemed", align: "right", cell: (c) => `${c.redeemed_count} / ${c.max_redemptions ?? "Unlimited"}` },
    { key: "per", header: "Per user", align: "right", cell: (c) => String(c.per_user_limit) },
    { key: "valid", header: "Valid", cell: (c) => `${formatDate(c.valid_from)} – ${c.valid_until ? formatDate(c.valid_until) : "open"}` },
    { key: "scope", header: "Applies to", cell: (c) => (c.applicable_product_ids.length ? `${c.applicable_product_ids.length} products` : "All products") + (c.first_time_only ? " · first purchase" : "") },
    {
      key: "status",
      header: "Status",
      cell: (c) => (
        <span className="flex flex-col gap-1">
          <StateBadge state={c.status} />
          {c.status === "paused" && (c.approval_request_id || awaiting.has(c.coupon_id)) ? <span className="text-xs text-warning-fg">⇄ Awaiting second approver</span> : null}
        </span>
      ),
    },
    {
      key: "act",
      header: <span className="sr-only">Actions</span>,
      // An expired coupon cannot be changed (the api only takes active/paused): no Edit.
      cell: (c) =>
        COUPON_ENDED.has(c.status) ? null : (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => {
              setPatch({ status: c.status === "paused" ? "paused" : "active", valid_until: "", max_redemptions: "" });
              setEdit(c);
            }}
            aria-label={`Edit coupon ${c.code}`}
          >
            Edit
          </Button>
        ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="Coupons"
        description={`More than ${COUPON_DUAL_PERCENT} % off, free access, or more than ${COUPON_DUAL_REDEMPTIONS.toLocaleString("en-IN")} (or unlimited) redemptions needs a second admin.`}
        actions={
          <Button
            onClick={() => {
              setForm(emptyCoupon);
              setProductIds([]);
              setCreate(true);
            }}
          >
            New coupon
          </Button>
        }
      />
      <FilterBar label="Coupon filters">
        <FormField label="Status">{(f) => <Select {...f} value={status} onChange={(e) => setStatus(e.target.value)} options={[{ value: "", label: "Any" }, ...["active", "paused", "expired"].map((s) => ({ value: s, label: humanize(s) }))]} />}</FormField>
      </FilterBar>
      <Table caption="Coupons" columns={cols} rows={rows} rowKey={(c) => c.coupon_id} loading={list.loading} error={list.error} onRetry={() => void list.reload()} empty={{ title: status ? "No coupons match" : "No coupons yet", description: status ? "Choose another status to see more coupons." : "Create a coupon to offer a discount at checkout.", icon: "card" }} footer={<Pagination hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} />} />

      <ActionDialog
        open={create}
        onClose={() => setCreate(false)}
        title="New coupon"
        submitLabel={needsDual ? "Create and request approval" : "Create coupon"}
        validate={() => {
          if (!/^[A-Za-z0-9_-]{3,32}$/.test(form.code.trim())) return "Code: 3–32 letters, digits, _ or -.";
          if (form.discount_type === "percent" && !(pct !== null && pct > 0 && pct <= 100)) return "Percent off must be above 0 and at most 100.";
          if (form.discount_type === "flat" && !(toPaise(form.amount_off) > 0)) return "Enter the amount off in ₹.";
          if (max !== null && !(Number.isInteger(max) && max > 0)) return "Max redemptions must be a whole number above 0 (empty = unlimited).";
          const per = Number(form.per_user_limit);
          if (!(Number.isInteger(per) && per >= 1 && per <= 100)) return "Per-user limit must be 1–100.";
          if (form.min_order.trim() && !(toPaise(form.min_order) >= 0)) return "Minimum order must be a number.";
          if (!form.valid_from) return "Choose the start date.";
          if (form.valid_until && form.valid_until < form.valid_from) return "Valid until must be after valid from.";
          return form.reason.trim().length < 3 ? "Give a reason (3+ characters)." : null;
        }}
        onSubmit={async () => {
          const res = await api.post<CouponCreateBody>(
              "finance/coupons",
              {
                code: form.code.trim(),
                discount_type: form.discount_type as "percent" | "flat" | "free_access",
                percent_off: form.discount_type === "percent" ? pct : null,
                amount_off_paise: form.discount_type === "flat" ? toPaise(form.amount_off) : null,
                applicable_product_ids: productIds,
                min_order_paise: form.min_order.trim() ? toPaise(form.min_order) : null,
                max_redemptions: max,
                per_user_limit: Number(form.per_user_limit),
                valid_from: istDayStart(form.valid_from),
                valid_until: form.valid_until ? istDayEnd(form.valid_until) : null,
                first_time_only: form.first_time_only,
                reason: form.reason.trim(),
              } satisfies Schema<"CouponIn">,
              { idempotencyKey: true },
            );
          const outcome = couponCreateOutcome(res);
          // The approval id is only returned on create: remember which paused coupons wait for approval.
          if (outcome.kind === "approval_pending" && res.kind === "ok") setAwaiting((ids) => new Set(ids).add(res.data.coupon_id));
          return outcome;
        }}
        onDone={(o) => {
          if (o.kind === "approval_pending") toast.show({ title: `Coupon ${form.code.trim()} was created paused. It goes live when a second admin approves.`, tone: "info" });
          else toast.show({ title: `Coupon ${o.data.code} is active.`, tone: "success" });
          void list.reload();
        }}
      >
        <FormField label="Code" required>{(f) => <Input {...f} value={form.code} onChange={set("code")} />}</FormField>
        <FormField label="Discount type">{(f) => <Select {...f} value={form.discount_type} onChange={set("discount_type")} options={[{ value: "percent", label: "Percent off" }, { value: "flat", label: "Flat amount off" }, { value: "free_access", label: "Free access" }]} />}</FormField>
        {form.discount_type === "percent" ? <FormField label="Percent off" required>{(f) => <Input {...f} inputMode="decimal" value={form.percent_off} onChange={set("percent_off")} />}</FormField> : null}
        {form.discount_type === "flat" ? <FormField label="Amount off (₹)" required>{(f) => <Input {...f} inputMode="decimal" value={form.amount_off} onChange={set("amount_off")} />}</FormField> : null}
        <FormField label="Max redemptions" hint="Empty = unlimited.">{(f) => <Input {...f} inputMode="numeric" value={form.max_redemptions} onChange={set("max_redemptions")} />}</FormField>
        <FormField label="Per-user limit">{(f) => <Input {...f} inputMode="numeric" value={form.per_user_limit} onChange={set("per_user_limit")} />}</FormField>
        <FormField label="Minimum order (₹)">{(f) => <Input {...f} inputMode="decimal" value={form.min_order} onChange={set("min_order")} />}</FormField>
        <FormField label="Valid from" required>{(f) => <Input {...f} type="date" value={form.valid_from} onChange={set("valid_from")} />}</FormField>
        <FormField label="Valid until">{(f) => <Input {...f} type="date" value={form.valid_until} onChange={set("valid_until")} />}</FormField>
        <Checkbox label="First purchase only" checked={form.first_time_only} onChange={(e) => setForm((x) => ({ ...x, first_time_only: e.target.checked }))} />
        <fieldset className="space-y-1 rounded-lg border border-line p-3">
          <legend className="px-1 text-sm font-semibold text-fg">Applies to</legend>
          <p className="text-xs text-fg-muted">
            {productIds.length ? `${productIds.length} selected.` : "None selected = every product."}
          </p>
          {products.rows ? (
            // A long catalogue scrolls inside the box instead of stretching the dialog.
            <div className="max-h-60 space-y-1 overflow-y-auto pr-1">
              {products.rows.map((p) => (
                <Checkbox key={p.product_id} label={productLabel(p)} checked={productIds.includes(p.product_id)} onChange={(e) => setProductIds((xs) => (e.target.checked ? [...xs, p.product_id] : xs.filter((x) => x !== p.product_id)))} />
              ))}
            </div>
          ) : products.error ? (
            <p className="text-sm text-fg-muted">Products could not be loaded. Close and reopen this dialog to try again.</p>
          ) : (
            <LoadingBlock label="Loading products…" rows={2} />
          )}
        </fieldset>
        <FormField label="Reason" required>{(f) => <TextArea {...f} value={form.reason} onChange={set("reason")} maxLength={500} />}</FormField>
        {needsDual ? (
          <p className="text-sm text-info-fg">
            <span aria-hidden="true">ⓘ </span>This coupon is created paused: a second admin must approve it before it can be redeemed.
          </p>
        ) : null}
      </ActionDialog>

      <ActionDialog
        open={edit !== null}
        onClose={() => setEdit(null)}
        title={`Edit coupon ${edit?.code ?? ""}`}
        description="Loosening a big coupon (re-activating it or raising its limit) needs a new coupon and a second approval."
        submitLabel="Save"
        validate={() => {
          if (patch.max_redemptions.trim()) {
            const n = Number(patch.max_redemptions);
            if (!(Number.isInteger(n) && n > 0)) return "Max redemptions must be a whole number above 0.";
          }
          return null;
        }}
        onSubmit={async () => {
          const body: Schema<"CouponPatchIn"> = {};
          if (patch.status !== edit!.status) body.status = patch.status as "active" | "paused";
          if (patch.valid_until) body.valid_until = istDayEnd(patch.valid_until);
          if (patch.max_redemptions.trim()) body.max_redemptions = Number(patch.max_redemptions);
          return toOutcome(await api.patch(`finance/coupons/${edit!.coupon_id}`, body));
        }}
        onDone={() => {
          toast.show({ title: "Coupon updated.", tone: "success" });
          void list.reload();
        }}
      >
        {edit ? <KeyValueList items={[{ label: "Discount", value: couponValue(edit) }, { label: "Redeemed", value: `${edit.redeemed_count} / ${edit.max_redemptions ?? "Unlimited"}` }]} /> : null}
        <FormField label="Status">{(f) => <Select {...f} value={patch.status} onChange={(e) => setPatch((x) => ({ ...x, status: e.target.value }))} options={["active", "paused"].map((s) => ({ value: s, label: humanize(s) }))} />}</FormField>
        <FormField label="New valid until" hint="Empty = unchanged.">{(f) => <Input {...f} type="date" value={patch.valid_until} onChange={(e) => setPatch((x) => ({ ...x, valid_until: e.target.value }))} />}</FormField>
        <FormField label="New max redemptions" hint="Empty = unchanged.">{(f) => <Input {...f} inputMode="numeric" value={patch.max_redemptions} onChange={(e) => setPatch((x) => ({ ...x, max_redemptions: e.target.value }))} />}</FormField>
      </ActionDialog>
    </div>
  );
}

/* ----------------------------------------------------------- subscriptions */

/** verified: app/modules/commerce/service.py sub_json + user_id (GET finance/subscriptions, latest 200, {data, page}). */
export interface SubscriptionRow {
  subscription_id: string;
  user_id: string;
  plan_id: string;
  price_id: string;
  status: string;
  gateway_subscription_id: string | null;
  mandate_max_amount_paise: number | null;
  current_period_start: string | null;
  current_period_end: string | null;
  next_charge_at: string | null;
  cancel_at_period_end: boolean;
  grace_until: string | null;
  paid_count: number;
}

/** commerce_0001 subscriptions.status CHECK. */
const SUB_STATUSES = ["created", "authenticated", "active", "pending", "halted", "paused", "cancelled", "completed", "expired"];
const SUB_ENDED = new Set(["cancelled", "completed", "expired"]);

/** The gateway's subscription id (what finance searches in the gateway), else a short reference. */
const subRef = (s: Pick<SubscriptionRow, "gateway_subscription_id" | "subscription_id">) => s.gateway_subscription_id ?? shortRef(s.subscription_id);

/** FIN-006 UPI AutoPay subscriptions (COM-09/10 admin view) with cancel on the user's behalf (reason required). */
export function Subscriptions() {
  const toast = useToast();
  const [status, setStatus] = useState("");
  const list = useCursorList<SubscriptionRow>("finance/subscriptions", cleanQuery({ status }));
  const [cancel, setCancel] = useState<SubscriptionRow | null>(null);
  const [form, setForm] = useState({ reason: "", ticket_ref: "", immediate: false });
  const cols: Column<SubscriptionRow>[] = [
    { key: "id", header: "Subscription", cell: (s) => <span className="font-mono text-xs">{subRef(s)}</span> },
    { key: "user", header: "User", cell: (s) => <span title={s.user_id}>{personLabel({ id: s.user_id })}</span> },
    { key: "status", header: "Status", cell: (s) => <span className="flex flex-col gap-1"><StateBadge state={s.status} />{s.cancel_at_period_end && !SUB_ENDED.has(s.status) ? <Badge tone="warning">Ends at period end</Badge> : null}</span> },
    { key: "period", header: "Current period", cell: (s) => `${formatDate(s.current_period_start)} – ${formatDate(s.current_period_end)}` },
    { key: "next", header: "Next debit", cell: (s) => formatDate(s.next_charge_at) },
    { key: "mandate", header: "Max per debit", align: "right", cell: (s) => formatINR(s.mandate_max_amount_paise) },
    { key: "paid", header: "Debits", align: "right", cell: (s) => String(s.paid_count) },
    {
      key: "act",
      header: <span className="sr-only">Actions</span>,
      cell: (s) =>
        SUB_ENDED.has(s.status) ? null : (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => {
              setForm({ reason: "", ticket_ref: "", immediate: false });
              setCancel(s);
            }}
            aria-label={`Cancel subscription ${subRef(s)}`}
          >
            Cancel
          </Button>
        ),
    },
  ];
  return (
    <div>
      <PageHeader title="Subscriptions" description="UPI AutoPay subscriptions (at most ₹15,000 per debit). Cancelling for a user needs a reason and is recorded in the audit log." />
      <FilterBar label="Subscription filters">
        <FormField label="Status">{(f) => <Select {...f} value={status} onChange={(e) => setStatus(e.target.value)} options={[{ value: "", label: "Any" }, ...SUB_STATUSES.map((s) => ({ value: s, label: humanize(s) }))]} />}</FormField>
      </FilterBar>
      <Table caption="Subscriptions" columns={cols} rows={list.rows} rowKey={(s) => s.subscription_id} loading={list.loading} error={list.error} onRetry={() => void list.reload()} empty={{ title: status ? "No subscriptions match" : "No subscriptions yet", description: status ? "Choose another status to see more subscriptions." : "Subscriptions appear when a buyer sets up UPI AutoPay.", icon: "card" }} footer={<Pagination hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} />} />
      <ActionDialog
        open={cancel !== null}
        onClose={() => setCancel(null)}
        title={`Cancel subscription ${cancel ? subRef(cancel) : ""}?`}
        description={form.immediate ? "The mandate is cancelled now and access moves to its grace period." : "No further debits; access continues until the current period ends."}
        submitLabel="Cancel subscription"
        cancelLabel="Keep subscription"
        danger
        validate={() => (form.reason.trim().length < 3 ? "Give a reason (3+ characters)." : form.ticket_ref.trim().length > 40 ? "Ticket reference: at most 40 characters." : null)}
        onSubmit={async () =>
          toOutcome(
            await api.post(
              `finance/subscriptions/${cancel!.subscription_id}/cancel`,
              { reason: form.reason.trim(), ticket_ref: form.ticket_ref.trim() || null, immediate: form.immediate } satisfies Schema<"AdminCancelSubIn">,
              { idempotencyKey: true },
            ),
          )
        }
        onDone={() => {
          toast.show({ title: "Subscription cancelled.", tone: "success" });
          void list.reload();
        }}
      >
        <FormField label="Reason" required>{(f) => <TextArea {...f} value={form.reason} onChange={(e) => setForm((x) => ({ ...x, reason: e.target.value }))} maxLength={200} />}</FormField>
        <FormField label="Support ticket">{(f) => <Input {...f} value={form.ticket_ref} onChange={(e) => setForm((x) => ({ ...x, ticket_ref: e.target.value }))} maxLength={40} />}</FormField>
        <Checkbox label="Cancel immediately (not at period end)" checked={form.immediate} onChange={(e) => setForm((x) => ({ ...x, immediate: e.target.checked }))} />
      </ActionDialog>
    </div>
  );
}
