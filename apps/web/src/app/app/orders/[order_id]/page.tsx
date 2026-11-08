import type { Metadata } from "next";
import { OrderStatus } from "@/features/commerce/components/OrderStatus";

export const metadata: Metadata = { title: "Order status" };

/** STU-017 order status (polls COM-05 while the payment is confirmed). */
export default async function Page({ params }: { params: Promise<{ order_id: string }> }) {
  const { order_id } = await params;
  return <OrderStatus orderId={decodeURIComponent(order_id)} />;
}
