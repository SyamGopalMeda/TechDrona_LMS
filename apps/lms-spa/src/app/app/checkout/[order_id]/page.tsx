import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { OrderStatus } from "@/features/commerce/components/OrderStatus";

export const metadata: Metadata = { title: "Checkout" };

/** STU-016 resume payment for an existing order (COM-05 → provider → COM-06). */
async function Page__server({ params }: { params: Promise<{ order_id: string }> }) {
  const { order_id } = await params;
  return <OrderStatus orderId={decodeURIComponent(order_id)} mode="resume" />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/app/checkout/[order_id]/page.tsx#Page");
