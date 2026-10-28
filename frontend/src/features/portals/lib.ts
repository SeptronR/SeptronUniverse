import i18n from '@/lib/i18n';
import { isPushSupported, registerServiceWorker } from '@/lib/push';
import { portalApi } from './api';

/** Web i18n (Prompts/39 §39.6 ``i18n_service``): the static pack from the build, then the API pack with the
 * institution's vocabulary overrides when `i18n.web` is on. */
export async function loadLocale(lng: string, i18nWeb: boolean) {
  try {
    const res = await fetch(`/locales/${lng}.json`, { cache: 'force-cache' });
    if (res.ok) i18n.addResourceBundle(lng, 'translation', await res.json(), true, true);
  } catch {
    /* offline: keep what is bundled */
  }
  if (i18nWeb) {
    try {
      const r = await portalApi.localePack(lng);
      if (r.data?.strings) i18n.addResourceBundle(lng, 'translation', r.data.strings, true, true);
    } catch {
      /* feature off for this tenant → English packs only */
    }
  }
  await i18n.changeLanguage(lng);
  document.documentElement.lang = lng;
}

// ---- PWA: install prompt + update toast + manifest link --------------------------------------------------------------
type Listener = () => void;
interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}
let deferred: BeforeInstallPromptEvent | null = null;
let waiting: ServiceWorker | null = null;
const listeners = new Set<Listener>();
const notify = () => listeners.forEach((l) => l());
export const pwaState = {
  canInstall: () => deferred !== null,
  updateReady: () => waiting !== null,
  subscribe: (l: Listener) => {
    listeners.add(l);
    return () => void listeners.delete(l);
  },
};

export function initPwa(institutionSlug?: string | null) {
  const href = `/api/v1/public/manifest.json${institutionSlug ? `?institution=${encodeURIComponent(institutionSlug)}` : ''}`;
  let link = document.querySelector<HTMLLinkElement>('link[rel="manifest"]');
  if (!link) {
    link = document.createElement('link');
    link.rel = 'manifest';
    document.head.appendChild(link);
  }
  link.href = href;
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferred = e as BeforeInstallPromptEvent;
    notify();
  });
  window.addEventListener('appinstalled', () => {
    deferred = null;
    notify();
    void portalApi.installed('installed').catch(() => undefined);
  });
  void registerServiceWorker().then((reg) => {
    if (!reg) return;
    const track = (w: ServiceWorker | null) => {
      if (!w) return;
      w.addEventListener('statechange', () => {
        if (w.state === 'installed' && navigator.serviceWorker.controller) {
          waiting = w;
          notify();
        }
      });
    };
    if (reg.waiting && navigator.serviceWorker.controller) {
      waiting = reg.waiting;
      notify();
    }
    reg.addEventListener('updatefound', () => track(reg.installing));
    // the worker fetches /public/pwa-config itself; tell it which tenant we are
    reg.active?.postMessage({ type: 'config', institution: institutionSlug ?? null });
  });
  let reloading = false;
  navigator.serviceWorker?.addEventListener('controllerchange', () => {
    if (reloading) return;
    reloading = true;
    window.location.reload();
  });
}

export async function promptInstall() {
  if (!deferred) return;
  await deferred.prompt();
  const choice = await deferred.userChoice;
  void portalApi.installed(choice.outcome).catch(() => undefined);
  deferred = null;
  notify();
}

export function applyUpdate() {
  waiting?.postMessage({ type: 'skip-waiting' });
}

// ---- web push ------------------------------------------------------------------------------------------------------------
function urlBase64ToUint8Array(base64: string) {
  const padding = '='.repeat((4 - (base64.length % 4)) % 4);
  const raw = atob((base64 + padding).replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

export async function enablePush(topics: string[] = []): Promise<boolean> {
  if (!isPushSupported()) return false;
  if ((await Notification.requestPermission()) !== 'granted') return false;
  const key = (await portalApi.vapidKey()).data?.public_key;
  const reg = await registerServiceWorker();
  if (!key || !reg) return false;
  const sub =
    (await reg.pushManager.getSubscription()) ??
    (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(key) }));
  const json = sub.toJSON();
  await portalApi.subscribe({ endpoint: json.endpoint, keys: json.keys, topics, platform: 'web' });
  return true;
}

export async function disablePush() {
  const reg = await registerServiceWorker();
  const sub = await reg?.pushManager.getSubscription();
  if (!sub) return;
  await portalApi.unsubscribe(sub.endpoint).catch(() => undefined);
  await sub.unsubscribe();
}

/** Logout: drop this browser's subscription so the next user of the device gets nothing. */
export const pushLogout = () => disablePush().catch(() => undefined);
