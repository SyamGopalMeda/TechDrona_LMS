import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { OrderStatus } from "@/features/commerce/components/OrderStatus";

export const metadata: Metadata = { title: "Order status" };

/** STU-017 order status (polls COM-05 while the payment is confirmed). */
async function Page__server({ params }: { params: Promise<{ order_id: string }> }) {
  const { order_id } = await params;
  return <OrderStatus orderId={decodeURIComponent(order_id)} />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/app/orders/[order_id]/page.tsx#Page");
