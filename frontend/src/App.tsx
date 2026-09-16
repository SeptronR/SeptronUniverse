import { useEffect } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { I18nextProvider } from 'react-i18next';
import AppRoutes from '@/routes';
import { queryClient } from '@/lib/queryClient';
import i18n from '@/lib/i18n';
import { Toaster } from '@/components/ui/Toaster';
import { TooltipProvider } from '@/components/ui/Tooltip';
import { applyThemePrefs, loadThemePrefs } from '@/styles/themes';

/** Provider tree: QueryClient -> I18n -> Tooltip -> Router; Toaster mounted once (Prompts/00 §4, Phase 01 §01.9). */
export default function App() {
  useEffect(() => {
    applyThemePrefs(loadThemePrefs());
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => {
      const prefs = loadThemePrefs();
      if (prefs.mode === 'system') applyThemePrefs(prefs);
    };
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <I18nextProvider i18n={i18n}>
        <TooltipProvider>
          <AppRoutes />
          <Toaster />
        </TooltipProvider>
      </I18nextProvider>
    </QueryClientProvider>
  );
}
