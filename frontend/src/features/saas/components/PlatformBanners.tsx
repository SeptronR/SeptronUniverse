import { Link } from 'react-router-dom';
import { AlertTriangle, CreditCard, Megaphone, X } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { billingApi, platformApi } from '../api';
import { useQ, type Any } from './kit';

/** Every shell: platform announcements (dismissable, polled every 5 min), provider outage, subscription state and the
 * API-cap notice — from ``/auth/me`` ``banners`` and ``/platform/announcements/active`` (Prompts/38 §38.9). */
export function PlatformBanners() {
  const qc = useQueryClient();
  const me = useQ(['me-banners'], () => billingApi.me(), true, 300_000);
  const ann = useQ(['ann-active'], () => platformApi.activeAnnouncements(), true, 300_000);
  const b: Any = (me.data?.data as Any)?.banners;
  const items: Any[] = (ann.data?.data as Any[]) ?? [];
  const dismiss = async (id: string) => {
    await platformApi.dismiss(id);
    qc.invalidateQueries({ queryKey: ['saas', 'ann-active'] });
  };
  return (
    <>
      {items.map((a) => (
        <div key={a.id} role="status" className="flex items-center gap-2 bg-primary/10 px-4 py-1.5 text-sm">
          <Megaphone className="h-4 w-4" /> <b>{a.title}</b> <span className="truncate opacity-80">{a.body}</span>
          <button className="ml-auto" aria-label="Dismiss" onClick={() => dismiss(a.id)}><X className="h-4 w-4" /></button>
        </div>
      ))}
      {(b?.outage ?? []).map((o: Any) => (
        <div key={`${o.provider}${o.capability}`} role="status" className="flex items-center gap-2 bg-warning px-4 py-1.5 text-sm text-warning-foreground">
          <AlertTriangle className="h-4 w-4" /> {o.provider} ({o.capability}) is having an outage; deliveries may be delayed.
        </div>
      ))}
      {b?.subscription && (
        <div role="status" className="flex items-center gap-2 bg-destructive px-4 py-1.5 text-sm text-destructive-foreground">
          <CreditCard className="h-4 w-4" />
          {b.subscription.state === 'trial_ending' && `Your trial ends in ${b.subscription.days} day(s).`}
          {b.subscription.state === 'grace' && `Subscription in grace until ${b.subscription.grace_until}.`}
          {['expired', 'cancelled'].includes(b.subscription.state) && 'Subscription expired — the workspace is read-only.'}
          <Link className="ml-auto underline" to="/admin/billing">Billing</Link>
        </div>
      )}
      {b?.api_cap && (
        <div role="status" className="bg-warning px-4 py-1.5 text-sm text-warning-foreground">
          API usage {b.api_cap.used.toLocaleString()} of {b.api_cap.cap.toLocaleString()} calls today{b.api_cap.exceeded ? ' — further calls are refused until tomorrow' : ''}.
        </div>
      )}
    </>
  );
}

/** Blocking screen for a suspended / archived tenant (login answers 403 INSTITUTION_SUSPENDED). */
export function SuspendedPage({ status = 'suspended' }: { status?: string }) {
  return (
    <div className="flex min-h-screen items-center justify-center p-6 text-center">
      <div className="max-w-md space-y-2">
        <h1 className="text-xl font-semibold">This institution is {status}</h1>
        <p className="text-sm text-muted-foreground">Contact the SeptronUniverse team (support@septronr.com) to restore access.</p>
      </div>
    </div>
  );
}
