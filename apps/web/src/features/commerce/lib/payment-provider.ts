/**
 * Payment provider abstraction for checkout (STU-016). The browser only collects the
 * gateway's callback fields; payment is confirmed server-side (COM-06 verifies the
 * signature and fetches the payment; webhooks are the other path). The callback alone never
 * grants access (api-specification §17.1).
 *
 *  - razorpayProvider: Razorpay Checkout JS (https://checkout.razorpay.com/v1/checkout.js).
 *  - testGatewayProvider: the backend's fake gateway in dev/test (no gateway network call;
 *    the learner picks the outcome in an explicit "Test mode" dialog).
 */
import type { ConfirmPayload, GatewayCheckout, OrderDto } from "./types";

export type PaymentOutcome = { kind: "success"; payload: ConfirmPayload } | { kind: "dismissed"; failure?: string | null };

export interface TestPaymentUi {
  /** Resolve with the outcome the learner chose in the test-mode dialog. */
  chooseOutcome: () => Promise<"success" | "failure" | "dismiss">;
}

export type PayableOrder = OrderDto & { checkout: GatewayCheckout };

export interface PaymentProvider {
  readonly id: "razorpay" | "test";
  readonly testMode: boolean;
  pay(order: PayableOrder, ui: TestPaymentUi): Promise<PaymentOutcome>;
}

/** The backend's FakePaymentProvider key (commerce/gateway.py FakePaymentProvider.KEY_ID). */
const FAKE_GATEWAY_KEY_ID = "rzp_test_FAKE";

export function isTestMode(order: Pick<OrderDto, "gateway" | "checkout">): boolean {
  return (
    order.gateway === "fake" ||
    Boolean(order.checkout?.key_id?.startsWith("rzp_test_")) ||
    Boolean(order.checkout?.test_payment)
  );
}

/* ------------------------------------------------------------------ Razorpay */

interface RazorpayResponse {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
}

interface RazorpayInstance {
  open(): void;
  on(event: "payment.failed", cb: (resp: { error?: { description?: string } }) => void): void;
}

type RazorpayCtor = new (options: Record<string, unknown>) => RazorpayInstance;

declare global {
  interface Window {
    Razorpay?: RazorpayCtor;
  }
}

const RAZORPAY_SRC = "https://checkout.razorpay.com/v1/checkout.js";
let razorpayLoading: Promise<RazorpayCtor> | null = null;

function loadRazorpay(): Promise<RazorpayCtor> {
  if (window.Razorpay) return Promise.resolve(window.Razorpay);
  if (razorpayLoading) return razorpayLoading;
  razorpayLoading = new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = RAZORPAY_SRC;
    s.async = true;
    s.onload = () => (window.Razorpay ? resolve(window.Razorpay) : reject(new Error("The payment window failed to load.")));
    s.onerror = () => {
      razorpayLoading = null;
      reject(new Error("We couldn't load the payment window. Check your connection and try again."));
    };
    document.head.appendChild(s);
  });
  return razorpayLoading;
}

export const razorpayProvider: PaymentProvider = {
  id: "razorpay",
  testMode: false,
  async pay(order) {
    const Razorpay = await loadRazorpay();
    const c = order.checkout;
    return new Promise<PaymentOutcome>((resolve) => {
      let lastFailure: string | null = null;
      const rzp = new Razorpay({
        key: c.key_id,
        order_id: c.gateway_order_id,
        amount: c.amount,
        currency: c.currency,
        name: c.name ?? "Tech Drona",
        description: c.description,
        prefill: c.prefill,
        notes: c.notes,
        handler: (resp: RazorpayResponse) =>
          resolve({
            kind: "success",
            payload: { razorpay_order_id: resp.razorpay_order_id, razorpay_payment_id: resp.razorpay_payment_id, razorpay_signature: resp.razorpay_signature },
          }),
        modal: { ondismiss: () => resolve({ kind: "dismissed", failure: lastFailure }), escape: true, confirm_close: true },
      });
      // Razorpay keeps its window open after a failure so the learner can try another method.
      rzp.on("payment.failed", (resp) => {
        lastFailure = resp.error?.description ?? "The payment didn't go through.";
      });
      rzp.open();
    });
  },
};

/* --------------------------------------------------------------- Test gateway */

export const testGatewayProvider: PaymentProvider = {
  id: "test",
  testMode: true,
  async pay(order, ui) {
    const outcome = await ui.chooseOutcome();
    const tp = order.checkout.test_payment;
    if (outcome === "success" && tp) {
      return {
        kind: "success",
        payload: { razorpay_order_id: order.checkout.gateway_order_id, razorpay_payment_id: tp.payment_id, razorpay_signature: tp.signature },
      };
    }
    if (outcome === "failure") return { kind: "dismissed", failure: "Test payment declined (simulated). No money was involved." };
    return { kind: "dismissed" };
  },
};

export function providerFor(order: Pick<OrderDto, "gateway" | "checkout">): PaymentProvider {
  // The fake gateway reports itself as "razorpay" (it speaks the protocol); detect it by its key.
  if (order.gateway === "fake" || order.checkout?.key_id === FAKE_GATEWAY_KEY_ID || order.checkout?.test_payment) return testGatewayProvider;
  return razorpayProvider;
}

/* ------------------------------------------------------------ Subscriptions */

export interface SubscriptionCheckout {
  key_id: string;
  subscription_id: string;
  name?: string;
}

export type SubscriptionOutcome =
  | { kind: "success"; payload: { razorpay_payment_id: string; razorpay_subscription_id: string; razorpay_signature: string } }
  | { kind: "dismissed"; failure?: string | null };

/** The fake gateway cannot authorise a mandate in the browser (no simulated subscription payment). */
export function isFakeSubscription(c: SubscriptionCheckout): boolean {
  return c.key_id === FAKE_GATEWAY_KEY_ID;
}

/** Razorpay Checkout in subscription mode (UPI AutoPay / e-mandate authorisation, COM-09 → COM-10). */
export async function payRazorpaySubscription(c: SubscriptionCheckout): Promise<SubscriptionOutcome> {
  const Razorpay = await loadRazorpay();
  return new Promise<SubscriptionOutcome>((resolve) => {
    let lastFailure: string | null = null;
    const rzp = new Razorpay({
      key: c.key_id,
      subscription_id: c.subscription_id,
      name: c.name ?? "Tech Drona",
      handler: (resp: { razorpay_payment_id: string; razorpay_subscription_id: string; razorpay_signature: string }) =>
        resolve({
          kind: "success",
          payload: {
            razorpay_payment_id: resp.razorpay_payment_id,
            razorpay_subscription_id: resp.razorpay_subscription_id,
            razorpay_signature: resp.razorpay_signature,
          },
        }),
      modal: { ondismiss: () => resolve({ kind: "dismissed", failure: lastFailure }), escape: true, confirm_close: true },
    });
    rzp.on("payment.failed", (resp) => {
      lastFailure = resp.error?.description ?? "The mandate wasn't authorised.";
    });
    rzp.open();
  });
}
