import { useEffect, useState, type ReactNode } from 'react';

/** Blurs PII while the tab is hidden / being switched (marks, valuation pages) — the web mirror of the mobile
 * screenshot block (Prompts/39 §39.6 accessibility_and_print). Printing is unaffected. */
export function SafeScreen({ children }: { children: ReactNode }) {
  const [hidden, setHidden] = useState(false);
  useEffect(() => {
    const on = () => setHidden(document.visibilityState !== 'visible');
    const blur = () => setHidden(true);
    const focus = () => setHidden(false);
    document.addEventListener('visibilitychange', on);
    window.addEventListener('blur', blur);
    window.addEventListener('focus', focus);
    return () => {
      document.removeEventListener('visibilitychange', on);
      window.removeEventListener('blur', blur);
      window.removeEventListener('focus', focus);
    };
  }, []);
  return <div className={hidden ? 'select-none blur-md transition print:blur-none' : 'transition'}>{children}</div>;
}
