/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
  readonly VITE_WS_URL?: string;
  readonly VITE_APP_ENV?: string;
  readonly VITE_CAPTCHA_PROVIDER?: string;
  readonly VITE_CAPTCHA_SITE_KEY?: string;
  readonly VITE_RAZORPAY_KEY_ID?: string;
  readonly VITE_VAPID_PUBLIC_KEY?: string;
  readonly VITE_SENTRY_DSN?: string;
}
