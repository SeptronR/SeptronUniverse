/** Web push (VAPID) registration - completed by Phase 04/39 (portals.pwa_push). */
export const isPushSupported = () => 'serviceWorker' in navigator && 'PushManager' in window;

export async function registerServiceWorker(): Promise<ServiceWorkerRegistration | null> {
  if (!('serviceWorker' in navigator)) return null;
  try {
    return await navigator.serviceWorker.register('/sw.js');
  } catch {
    return null;
  }
}

export async function subscribeToPush(
  vapidPublicKey = import.meta.env.VITE_VAPID_PUBLIC_KEY,
): Promise<PushSubscription | null> {
  if (!isPushSupported() || !vapidPublicKey) return null;
  const reg = await registerServiceWorker();
  if (!reg) return null;
  const existing = await reg.pushManager.getSubscription();
  if (existing) return existing;
  return reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(vapidPublicKey),
  });
}

function urlBase64ToUint8Array(base64: string) {
  const padding = '='.repeat((4 - (base64.length % 4)) % 4);
  const raw = atob((base64 + padding).replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}
