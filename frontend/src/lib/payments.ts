/** Razorpay checkout loader (payments land in Phase 12; the order always comes from the backend, never the client). */
export interface CheckoutOrder {
  order_id: string;
  amount_paise: number;
  currency: string;
  key_id: string;
  name: string;
  description?: string;
  prefill?: { name?: string; email?: string; contact?: string };
}

export interface CheckoutResult {
  razorpay_payment_id: string;
  razorpay_order_id: string;
  razorpay_signature: string;
}

interface RazorpayInstance {
  open: () => void;
}
interface RazorpayWindow {
  Razorpay: new (options: object) => RazorpayInstance;
}

let sdkPromise: Promise<void> | null = null;
export function loadRazorpay(): Promise<void> {
  sdkPromise ??= new Promise((resolve, reject) => {
    if (document.querySelector('script[data-razorpay]')) return resolve();
    const s = document.createElement('script');
    s.src = 'https://checkout.razorpay.com/v1/checkout.js';
    s.dataset.razorpay = '1';
    s.onload = () => resolve();
    s.onerror = () => reject(new Error('Failed to load payment SDK'));
    document.head.appendChild(s);
  });
  return sdkPromise;
}

export async function openCheckout(order: CheckoutOrder): Promise<CheckoutResult> {
  await loadRazorpay();
  const { Razorpay } = window as unknown as RazorpayWindow;
  return new Promise((resolve, reject) => {
    const rz = new Razorpay({
      key: order.key_id,
      amount: order.amount_paise,
      currency: order.currency,
      order_id: order.order_id,
      name: order.name,
      description: order.description,
      prefill: order.prefill,
      handler: (r: CheckoutResult) => resolve(r),
      modal: { ondismiss: () => reject(new Error('Payment cancelled')) },
    });
    rz.open();
  });
}
