/** Captcha token acquisition for public forms; provider from VITE_CAPTCHA_PROVIDER (none | turnstile | recaptcha | hcaptcha). */
export type CaptchaProvider = 'none' | 'turnstile' | 'recaptcha' | 'hcaptcha';
export const captchaProvider = (import.meta.env.VITE_CAPTCHA_PROVIDER || 'none') as CaptchaProvider;
export const captchaSiteKey = import.meta.env.VITE_CAPTCHA_SITE_KEY || '';

interface CaptchaWindow {
  grecaptcha?: { execute: (key: string, opts: { action: string }) => Promise<string> };
  turnstile?: { getResponse: () => string | undefined };
  hcaptcha?: { getResponse: () => string | undefined };
}

export async function getCaptchaToken(action = 'submit'): Promise<string | null> {
  if (captchaProvider === 'none') return null;
  const w = window as unknown as CaptchaWindow;
  if (captchaProvider === 'recaptcha' && w.grecaptcha) return w.grecaptcha.execute(captchaSiteKey, { action });
  if (captchaProvider === 'turnstile') return w.turnstile?.getResponse() ?? null;
  if (captchaProvider === 'hcaptcha') return w.hcaptcha?.getResponse() ?? null;
  return null;
}
