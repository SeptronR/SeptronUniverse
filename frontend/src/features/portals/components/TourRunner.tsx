/* eslint-disable react-refresh/only-export-components */
import { useEffect, useLayoutEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/Button';
import { portalApi, type TourDef } from '../api';

/**
 * Guided tours (Prompts/39 §39.6 ``tour_service``): on each route the matching definitions are fetched; the first one
 * whose version is newer than the completed one (and not dismissed) auto-starts. Steps highlight `step.target`
 * (`[data-tour=…]`); missing targets are skipped. `restartTour(key)` (help drawer) replays one.
 */
const RESTART = 'portal-tour-restart';
export const restartTour = (key: string) => window.dispatchEvent(new CustomEvent(RESTART, { detail: key }));

export function TourRunner({ enabled }: { enabled: boolean }) {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const [tour, setTour] = useState<TourDef | null>(null);
  const [step, setStep] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    void Promise.all([portalApi.tours(pathname), portalApi.tourState()])
      .then(([defs, state]) => {
        if (cancelled) return;
        const s = state.data ?? { completed: {}, dismissed: [] };
        const next = (defs.data ?? []).find((d) => (s.completed[d.key] ?? 0) < d.version && !s.dismissed.includes(d.key));
        if (next) {
          setTour(next);
          setStep(0);
        }
      })
      .catch(() => undefined);
    const onRestart = (e: Event) => {
      const key = (e as CustomEvent<string>).detail;
      void portalApi.tours(pathname).then((defs) => {
        const d = (defs.data ?? []).find((x) => x.key === key);
        if (d) {
          void portalApi.saveTour({ key, version: d.version, reset: true });
          setTour(d);
          setStep(0);
        }
      });
    };
    window.addEventListener(RESTART, onRestart);
    return () => {
      cancelled = true;
      window.removeEventListener(RESTART, onRestart);
    };
  }, [enabled, pathname]);

  const current = tour?.steps[step];
  useLayoutEffect(() => {
    if (!current) return setRect(null);
    const el = document.querySelector(current.target);
    if (el) {
      el.scrollIntoView({ block: 'center', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
      setRect(el.getBoundingClientRect());
    } else setRect(null);
  }, [current]);

  if (!tour || !current) return null;
  const finish = (completed: boolean) => {
    void portalApi.saveTour({ key: tour.key, version: tour.version, completed, dismissed: !completed }).catch(() => undefined);
    setTour(null);
  };
  const last = step === tour.steps.length - 1;
  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label={tour.title ?? 'Tour'}>
      <div className="absolute inset-0 bg-black/40" onClick={() => finish(false)} />
      {rect && (
        <div
          className="pointer-events-none absolute rounded-md ring-4 ring-primary"
          style={{ top: rect.top - 4, left: rect.left - 4, width: rect.width + 8, height: rect.height + 8 }}
        />
      )}
      <div
        className="absolute w-[min(22rem,calc(100vw-2rem))] rounded-lg border bg-card p-4 shadow-lg"
        style={rect ? { top: Math.min(rect.bottom + 12, window.innerHeight - 200), left: Math.max(16, Math.min(rect.left, window.innerWidth - 368)) } : { top: '30%', left: '50%', transform: 'translateX(-50%)' }}
      >
        <p className="text-xs text-muted-foreground">{step + 1} / {tour.steps.length}</p>
        <h2 className="font-semibold">{current.title}</h2>
        <p className="mt-1 text-sm">{current.body}</p>
        <div className="mt-3 flex justify-between gap-2">
          <Button size="sm" variant="ghost" onClick={() => finish(false)}>{t('portal.skipTour')}</Button>
          <div className="flex gap-2">
            {step > 0 && <Button size="sm" variant="outline" onClick={() => setStep(step - 1)}>{t('portal.back')}</Button>}
            <Button size="sm" autoFocus onClick={() => (last ? finish(true) : setStep(step + 1))}>{last ? t('portal.done') : t('portal.next')}</Button>
          </div>
        </div>
      </div>
    </div>
  );
}
