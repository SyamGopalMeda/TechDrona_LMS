import type { Metadata } from "next";
import { OrderStatus } from "@/features/commerce/components/OrderStatus";

export const metadata: Metadata = { title: "Checkout" };

/** STU-016 resume payment for an existing order (COM-05 → provider → COM-06). */
export default async function Page({ params }: { params: Promise<{ order_id: string }> }) {
  const { order_id } = await params;
  return <OrderStatus orderId={decodeURIComponent(order_id)} mode="resume" />;
}
