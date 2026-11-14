import { redirect } from "next/navigation";

/**
 * `/app/orders` has no list of its own (only `/app/orders/<id>`, the order status page). The
 * student's orders are listed on Billing, so the bare URL forwards there instead of rendering
 * a blank page (live audit F-11).
 */
export default function Page() {
  redirect("/app/billing");
}
