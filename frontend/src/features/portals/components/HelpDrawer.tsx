import { useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { HelpCircle } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { useFeature } from '@/hooks/useFeature';
import { portalApi } from '../api';
import { restartTour } from './TourRunner';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;

/** `?` button: contextual article for the current route (Phase 38 `help:<route>`), helpful vote, restart the route's
 * tour and the feedback form (page + persona; 10 per 10 minutes) — Prompts/39 §39.6 ``help_context_service``. */
export function HelpDrawer({ persona }: { persona: string | null }) {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  const helpOn = useFeature('platform.help_center');
  const feedbackOn = useFeature('platform.in_app_feedback');
  const ctx = useQuery({
    queryKey: ['help-context', pathname],
    queryFn: () => portalApi.helpContext(pathname),
    enabled: open && helpOn,
    retry: false,
  });
  const [msg, setMsg] = useState('');
  const [rating, setRating] = useState(4);
  const [shot, setShot] = useState('');
  const a: Any = ctx.data?.data?.article;
  const tours: string[] = (ctx.data?.data?.tours as string[]) ?? [];
  const send = async () => {
    try {
      await portalApi.feedback({ page: pathname, persona, rating, message: msg, category: 'idea', client: 'pwa', screenshot_url: shot || undefined });
      toast.success(t('portal.sendFeedback'));
      setMsg('');
      setShot('');
    } catch (e) {
      toast.error(getApiError(e));
    }
  };
  return (
    <>
      <Button variant="ghost" size="icon" aria-label={t('portal.help')} data-tour="portal-help" onClick={() => setOpen(true)}>
        <HelpCircle className="h-4 w-4" />
      </Button>
      <Modal open={open} onOpenChange={setOpen} title={a?.title ?? t('portal.help')}>
        <div className="space-y-4 text-sm">
          {a ? (
            <>
              <div className="prose prose-sm max-w-none whitespace-pre-wrap">{a.body}</div>
              <div className="flex items-center gap-2">
                <span>{t('portal.helpful')}</span>
                <Button size="sm" variant="outline" onClick={() => void portalApi.helpful(a.slug, true).then(() => toast.success('👍'))}>{t('portal.yes')}</Button>
                <Button size="sm" variant="outline" onClick={() => void portalApi.helpful(a.slug, false).then(() => toast.success('🙏'))}>{t('portal.no')}</Button>
              </div>
            </>
          ) : (
            <p className="text-muted-foreground">{ctx.isLoading ? '…' : t('portal.noItems')}</p>
          )}
          {tours.length > 0 && (
            <Button size="sm" variant="secondary" onClick={() => { setOpen(false); restartTour(tours[0]); }}>
              {t('portal.restartTour')}
            </Button>
          )}
          {feedbackOn && (
            <div className="space-y-2 border-t pt-3">
              <p className="font-medium">{t('portal.feedback')}</p>
              <div className="flex gap-1" role="radiogroup" aria-label="Rating">
                {[1, 2, 3, 4, 5].map((n) => (
                  <button key={n} type="button" role="radio" aria-checked={rating === n} className={`h-8 w-8 rounded border ${rating >= n ? 'bg-primary text-primary-foreground' : ''}`} onClick={() => setRating(n)}>
                    {n}
                  </button>
                ))}
              </div>
              <textarea className="h-24 w-full rounded-md border bg-background p-2" aria-label={t('portal.feedback')} value={msg} onChange={(e) => setMsg(e.target.value)} />
              <input className="h-9 w-full rounded-md border bg-background px-2" placeholder="Screenshot URL (optional — avoid personal data)" value={shot} onChange={(e) => setShot(e.target.value)} />
              <Button size="sm" disabled={msg.trim().length < 3} onClick={() => void send()}>{t('portal.sendFeedback')}</Button>
            </div>
          )}
        </div>
      </Modal>
    </>
  );
}
