import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { QRCodeSVG } from 'qrcode.react';
import { api, getApiError } from '@/api/axios';
import { EmptyState } from '@/components/shared/EmptyState';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Switch } from '@/components/ui/Switch';
import { toast } from '@/components/ui/Toaster';
import { usePortalConfig } from '@/components/layout/PortalLayout';
import DashboardPage from '@/pages/DashboardPage';
import { useAuthStore } from '@/store/authStore';
import { portalApi, type NotificationItem, type PreferenceSet } from '../api';
import { NavIcon } from '../components/icons';
import { disablePush, enablePush } from '../lib';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const inr = (p: unknown) => `₹ ${(Number(p ?? 0) / 100).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
const dt = (v: unknown) => (v ? new Date(String(v)).toLocaleString() : '—');
const q = <T,>(key: unknown[], fn: () => Promise<T>, enabled = true) => ({ queryKey: ['portal', ...key], queryFn: fn, retry: false, enabled });

function Loading({ r }: { r: Any }) {
  if (r.isLoading) return <p className="text-sm text-muted-foreground">…</p>;
  if (r.isError) return <p className="text-sm text-destructive">{getApiError(r.error)}</p>;
  return null;
}

/** Portal Home: greeting + the Phase 35 `GET /dashboard` widgets of the persona's role. */
export function PortalHome() {
  const user = useAuthStore((s) => s.currentUser);
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold" data-tour="page-title">Hello{user?.display_name ? `, ${user.display_name}` : ''}</h1>
      <DashboardPage />
    </div>
  );
}

/** More grid — every `more` entry of the persona (features already filtered server-side). */
export function PortalMorePage() {
  const { t } = useTranslation();
  const cfg = usePortalConfig();
  const more = cfg.data?.data?.more ?? [];
  return (
    <div className="space-y-4">
      <PageHeader title={t('portal.more')} />
      <Loading r={cfg} />
      <div className="grid grid-cols-3 gap-3 sm:grid-cols-4 lg:grid-cols-6">
        {more.map((m) => (
          <Link key={m.key} to={m.route} className="flex flex-col items-center gap-2 rounded-lg border bg-card p-3 text-center text-xs hover:bg-muted">
            <NavIcon name={m.icon} className="h-6 w-6 text-primary" />
            {t(m.label_key)}
          </Link>
        ))}
      </div>
    </div>
  );
}

export function PortalRequestsPage() {
  const { t } = useTranslation();
  const [status, setStatus] = useState('');
  const r = useQuery(q(['requests', status], () => portalApi.requests({ status: status || undefined })));
  const d: Any = r.data?.data;
  const groups: Record<string, Any[]> = {};
  for (const i of d?.items ?? []) (groups[i.source_module] ??= []).push(i);
  return (
    <div className="space-y-4">
      <PageHeader title={t('portal.nav.requests')} actions={
        <select aria-label="Status" className="h-9 rounded-md border bg-background px-2 text-sm" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All</option>
          {['pending', 'in_progress', 'approved', 'rejected', 'completed', 'cancelled', 'draft'].map((s) => <option key={s} value={s}>{s.replace('_', ' ')}{d?.by_status?.[s] ? ` (${d.by_status[s]})` : ''}</option>)}
        </select>
      } />
      {(d?.launchers ?? []).length > 0 && (
        <div className="flex flex-wrap gap-2" aria-label={t('portal.raiseNew')}>
          {(d.launchers as Any[]).map((l) => (
            <Link key={l.key} to={l.route}><Button size="sm" variant="outline"><NavIcon name={l.icon} className="mr-1 h-3 w-3" />{l.key.replace('_', ' ')}</Button></Link>
          ))}
        </div>
      )}
      <Loading r={r} />
      {d && d.items.length === 0 && <EmptyState title={t('portal.noItems')} />}
      {Object.entries(groups).map(([mod, items]) => (
        <Card key={mod}>
          <CardContent className="p-4">
            <h2 className="mb-2 text-sm font-semibold capitalize">{mod.replace('_', ' ')}</h2>
            <ul className="divide-y">
              {items.map((i) => (
                <li key={`${i.type}${i.id}`} className="flex items-center justify-between gap-2 py-2 text-sm">
                  <Link to={i.route} className="min-w-0 truncate hover:underline">{i.number ? `${i.number} · ` : ''}{i.title}</Link>
                  <span className="flex items-center gap-2 text-xs text-muted-foreground">{dt(i.created_at)}<StatusBadge status={i.status} /></span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

export function PortalDocumentsPage() {
  const { t } = useTranslation();
  const r = useQuery(q(['documents'], () => portalApi.documents()));
  const items: Any[] = (r.data?.data as Any[]) ?? [];
  const download = async (route: string) => {
    try {
      const res: Any = await api.get(route.replace(/^\/api\/v1/, ''));
      const url = res?.data?.url ?? res?.data?.signed_url;
      if (url) window.open(url, '_blank', 'noopener');
    } catch (e) {
      toast.error(getApiError(e));
    }
  };
  return (
    <div className="space-y-4">
      <PageHeader title={t('portal.nav.documents')} actions={<Button size="sm" variant="outline" className="print:hidden" onClick={() => window.print()}>{t('portal.print')}</Button>} />
      <Loading r={r} />
      {!r.isLoading && items.length === 0 && <EmptyState title={t('portal.noItems')} />}
      <div className="grid gap-3 sm:grid-cols-2">
        {items.map((doc) => (
          <Card key={doc.id} className="break-inside-avoid">
            <CardContent className="flex gap-3 p-4">
              {doc.verify_url && <QRCodeSVG value={`${window.location.origin}${doc.verify_url}`} size={72} aria-label={t('portal.verify')} />}
              <div className="min-w-0 flex-1 text-sm">
                <p className="font-medium">{doc.title}</p>
                <p className="text-xs text-muted-foreground">{doc.document_number ?? ''} · {dt(doc.issued_at)}</p>
                <div className="mt-2 flex gap-2 print:hidden">
                  <Button size="sm" onClick={() => void download(doc.download_route)}>Download</Button>
                  {doc.verify_url && <Link to={doc.verify_url}><Button size="sm" variant="outline">{t('portal.verify')}</Button></Link>}
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

export function PortalPaymentsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const cfg = usePortalConfig();
  const r = useQuery(q(['payments'], () => portalApi.payments()));
  const d: Any = r.data?.data;
  const home = cfg.data?.data?.home ?? '/student';
  return (
    <div className="space-y-4">
      <PageHeader title={t('portal.nav.payments')} />
      <Loading r={r} />
      {d && (
        <>
          <div className="grid gap-3 sm:grid-cols-4">
            {[['Invoiced', d.totals.invoiced_paise], ['Paid', d.totals.paid_paise], ['Balance', d.totals.balance_paise], ['Refunded', d.totals.refunded_paise]].map(([l, v]) => (
              <Card key={l as string}><CardContent className="p-4"><p className="text-xs text-muted-foreground">{l}</p><p className="text-lg font-semibold">{inr(v)}</p></CardContent></Card>
            ))}
          </div>
          {(['invoices', 'payments', 'refunds'] as const).map((k) => (
            <Card key={k}>
              <CardContent className="p-4">
                <h2 className="mb-2 text-sm font-semibold capitalize">{k}</h2>
                {(d[k] as Any[]).length === 0 ? <p className="text-sm text-muted-foreground">{t('portal.noItems')}</p> : (
                  <table className="w-full text-sm">
                    <tbody className="divide-y">
                      {(d[k] as Any[]).map((i) => (
                        <tr key={i.id}>
                          <td className="py-2">{i.number ?? '—'}<span className="ml-2 text-xs text-muted-foreground">{i.source_type ?? ''}</span></td>
                          <td className="py-2 text-right tabular-nums">{inr(i.amount_paise)}</td>
                          <td className="py-2 text-right"><StatusBadge status={i.status} /></td>
                          <td className="py-2 text-right">{i.payable && <Button size="sm" onClick={() => navigate(`${home}/fees?invoice=${i.id}`)}>{t('portal.pay')}</Button>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </CardContent>
            </Card>
          ))}
        </>
      )}
    </div>
  );
}

export function PortalApprovalsPage() {
  const { t } = useTranslation();
  const r = useQuery(q(['approvals'], () => portalApi.approvals()));
  const items: Any[] = (r.data?.data as Any[]) ?? [];
  return (
    <div className="space-y-4">
      <PageHeader title={t('portal.nav.approvals')} />
      <Loading r={r} />
      {!r.isLoading && items.length === 0 && <EmptyState title={t('portal.noItems')} />}
      <ul className="divide-y rounded-lg border bg-card">
        {items.map((a) => (
          <li key={a.step_id} className="flex items-center justify-between gap-2 p-3 text-sm">
            <Link to={a.route} className="hover:underline">{a.title}<span className="ml-2 text-xs text-muted-foreground">{a.workflow}</span></Link>
            <span className="text-xs text-muted-foreground">SLA {dt(a.sla_due_at)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function PortalCalendarPage() {
  const { t } = useTranslation();
  const r = useQuery(q(['calendar'], () => portalApi.calendar()));
  const d: Any = r.data?.data;
  const byDay: Record<string, Any[]> = {};
  for (const i of d?.items ?? []) (byDay[String(i.start).slice(0, 10)] ??= []).push(i);
  return (
    <div className="space-y-4">
      <PageHeader title={t('portal.nav.calendar')} actions={<Link to="/calendar"><Button size="sm" variant="outline">{t('portal.subscribe')}</Button></Link>} />
      <Loading r={r} />
      {d && Object.keys(byDay).length === 0 && <EmptyState title={t('portal.noItems')} />}
      {Object.entries(byDay).map(([day, items]) => (
        <div key={day}>
          <h2 className="text-sm font-semibold">{new Date(day).toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'short' })}</h2>
          <ul className="mt-1 space-y-1">
            {items.map((i) => <li key={i.id} className="rounded border bg-card px-3 py-2 text-sm">{i.title}<span className="ml-2 text-xs text-muted-foreground">{i.kind}</span></li>)}
          </ul>
        </div>
      ))}
    </div>
  );
}

export function PortalTimelinePage() {
  const { t } = useTranslation();
  const r = useQuery(q(['timeline'], () => portalApi.timeline()));
  const items: Any[] = (r.data?.data as Any[]) ?? [];
  return (
    <div className="space-y-4">
      <PageHeader title={t('portal.nav.timeline')} />
      <Loading r={r} />
      <ol className="relative space-y-3 border-l pl-4">
        {items.map((i, n) => (
          <li key={n} className="text-sm">
            <span className="absolute -left-1.5 mt-1.5 h-3 w-3 rounded-full bg-primary" aria-hidden="true" />
            <p>{i.route ? <Link to={i.route} className="hover:underline">{i.title}</Link> : i.title}</p>
            <p className="text-xs text-muted-foreground">{dt(i.at)} · {i.kind}</p>
          </li>
        ))}
      </ol>
    </div>
  );
}

/** Notification centre: category tabs with unread badges, unread filter, mark read / all, snooze, deep links,
 * acknowledgement-pinned announcements on top. */
export function PortalNotificationsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const cfg = usePortalConfig();
  const [cat, setCat] = useState('');
  const [unread, setUnread] = useState(false);
  const counts = useQuery(q(['ncounts'], () => portalApi.counts()));
  const list = useQuery(q(['nlist', cat, unread], () => portalApi.notifications({ category: cat || undefined, unread, page_size: 50 })));
  const acks = useQuery(q(['acks'], () => portalApi.pendingAcks()));
  const c: Any = counts.data?.data;
  const refresh = () => qc.invalidateQueries({ queryKey: ['portal'] });
  const open = async (n: NotificationItem) => {
    const r: Any = await portalApi.open(n.id);
    void refresh();
    if (r.data?.route) navigate(r.data.route);
  };
  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      await refresh();
    } catch (e) {
      toast.error(getApiError(e));
    }
  };
  const cats = Object.keys(c?.unread_by_category ?? {});
  return (
    <div className="space-y-4">
      <PageHeader title={t('portal.notifications')} actions={
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => void act(() => portalApi.markRead({ all: true, category: cat || undefined }))}>{t('portal.markAll')}</Button>
          <Link to={`${cfg.data?.data?.home ?? ''}/notifications/settings`}><Button size="sm" variant="outline">{t('portal.preferences')}</Button></Link>
        </div>
      } />
      {((acks.data?.data as Any[]) ?? []).map((a) => (
        <Card key={a.id} className="border-warning">
          <CardContent className="flex items-center justify-between gap-2 p-3 text-sm">
            <span><b>{t('portal.pendingAck')}:</b> {a.title}</span>
            <Button size="sm" onClick={() => void act(() => portalApi.acknowledge(a.id))}>{t('portal.acknowledge')}</Button>
          </CardContent>
        </Card>
      ))}
      <div className="flex flex-wrap items-center gap-2">
        {/* only role="tab" children may live inside the tablist (axe aria-required-children) */}
        <div className="flex flex-wrap items-center gap-2" role="tablist" aria-label="Categories">
          {['', ...cats].map((k) => (
            <button key={k || 'all'} role="tab" aria-selected={cat === k} className={`rounded-full border px-3 py-1 text-xs ${cat === k ? 'bg-primary text-primary-foreground' : ''}`} onClick={() => setCat(k)}>
              {k || 'All'} {k ? `(${c.unread_by_category[k]})` : c ? `(${c.unread})` : ''}
            </button>
          ))}
        </div>
        <label className="ml-auto flex items-center gap-2 text-xs"><Switch checked={unread} onCheckedChange={setUnread} /> Unread only</label>
        {cat && (
          c?.snoozed?.[cat]
            ? <Button size="sm" variant="ghost" onClick={() => void act(() => portalApi.snooze(cat, 0))}>{t('portal.unsnooze')}</Button>
            : <Button size="sm" variant="ghost" onClick={() => void act(() => portalApi.snooze(cat, 24))}>{t('portal.snooze')}</Button>
        )}
      </div>
      <Loading r={list} />
      <ul className="divide-y rounded-lg border bg-card">
        {((list.data?.data as NotificationItem[]) ?? []).map((n) => (
          <li key={n.id}>
            <button className={`w-full p-3 text-left text-sm hover:bg-muted ${n.is_read ? 'text-muted-foreground' : 'font-medium'}`} onClick={() => void open(n)}>
              <span className="mr-2 rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase">{n.category ?? 'system'}</span>
              {n.title}
              <span className="block text-xs font-normal text-muted-foreground">{dt(n.created_at)}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function PortalNotificationSettingsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const cfg = usePortalConfig();
  const r = useQuery(q(['nprefs'], () => portalApi.preferences()));
  const p: PreferenceSet | undefined = r.data?.data;
  const save = async (body: Any) => {
    try {
      await portalApi.savePreferences(body);
      await qc.invalidateQueries({ queryKey: ['portal', 'nprefs'] });
      toast.success('Saved');
    } catch (e) {
      toast.error(getApiError(e));
    }
  };
  const toggle = (category: string, channel: string, on: boolean) => {
    const row = p?.categories.find((c) => c.category === category);
    if (!row) return;
    const channels = on ? [...row.channels, channel] : row.channels.filter((x) => x !== channel);
    void save({ categories: [{ category, channels, locked: [], available: [] }] });
  };
  const push = async (on: boolean) => {
    try {
      if (on) {
        const ok = await enablePush([`persona:${cfg.data?.data?.persona ?? 'portal'}`]);
        if (!ok) toast.error('Push is blocked in this browser');
      } else await disablePush();
      await qc.invalidateQueries({ queryKey: ['portal', 'nprefs'] });
    } catch (e) {
      toast.error(getApiError(e));
    }
  };
  return (
    <div className="space-y-4">
      <PageHeader title={t('portal.preferences')} />
      <Loading r={r} />
      {p && (
        <>
          <Card><CardContent className="flex flex-wrap items-center gap-4 p-4 text-sm">
            <label className="flex items-center gap-2"><Switch checked={p.push_subscribed} onCheckedChange={(v) => void push(v)} disabled={!cfg.data?.data?.push_enabled} /> {t('portal.pushOn')}</label>
            {p.push_subscribed && <Button size="sm" variant="outline" onClick={() => void portalApi.testPush().then(() => toast.success('Sent'), (e) => toast.error(getApiError(e)))}>{t('portal.testPush')}</Button>}
            <label className="flex items-center gap-2">{t('portal.digest')}
              <select className="h-8 rounded-md border bg-background px-2" value={p.digest} onChange={(e) => void save({ digest: e.target.value })}>
                {['none', 'daily', 'weekly'].map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
            </label>
            <label className="flex items-center gap-2">{t('portal.quietHours')}
              <input type="time" aria-label="Quiet hours from" className="h-8 rounded-md border bg-background px-1" defaultValue={p.quiet_hours?.from ?? '22:00'} onBlur={(e) => void save({ quiet_hours: { from: e.target.value, to: p.quiet_hours?.to ?? '07:00' } })} />
              –
              <input type="time" aria-label="Quiet hours to" className="h-8 rounded-md border bg-background px-1" defaultValue={p.quiet_hours?.to ?? '07:00'} onBlur={(e) => void save({ quiet_hours: { from: p.quiet_hours?.from ?? '22:00', to: e.target.value } })} />
            </label>
          </CardContent></Card>
          <Card><CardContent className="overflow-x-auto p-4">
            <table className="w-full text-sm">
              <thead><tr><th className="text-left">Category</th>{p.available_channels.map((ch) => <th key={ch} className="px-2 text-xs capitalize">{ch.replace('_', '-')}</th>)}</tr></thead>
              <tbody className="divide-y">
                {p.categories.map((c) => (
                  <tr key={c.category}>
                    <td className="py-2 capitalize">{c.category}</td>
                    {p.available_channels.map((ch) => (
                      <td key={ch} className="px-2 text-center">
                        <input type="checkbox" aria-label={`${c.category} ${ch}`} checked={c.channels.includes(ch)} disabled={c.locked.includes(ch)} onChange={(e) => toggle(c.category, ch, e.target.checked)} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent></Card>
        </>
      )}
    </div>
  );
}

export function PortalProfilePage() {
  const { t } = useTranslation();
  const user = useAuthStore((s) => s.currentUser);
  const cfg = usePortalConfig();
  const home = cfg.data?.data?.home ?? '';
  return (
    <div className="space-y-4">
      <PageHeader title={t('portal.profile')} />
      <Card><CardContent className="space-y-1 p-4 text-sm">
        <p className="font-medium">{user?.display_name ?? user?.username}</p>
        <p className="text-muted-foreground">{user?.role_slugs.join(', ')}</p>
      </CardContent></Card>
      <div className="grid gap-3 sm:grid-cols-3">
        {[
          [`${home}/notifications/settings`, t('portal.preferences')],
          ['/settings/sessions', t('portal.sessions')],
          ['/settings/consents', t('portal.consents')],
          ['/profile', t('common.profile')],
        ].map(([to, label]) => <Link key={to} to={to}><Card><CardContent className="p-4 text-sm hover:bg-muted">{label}</CardContent></Card></Link>)}
      </div>
    </div>
  );
}

/** `/offline` fallback the service worker serves for uncached navigations. */
export function OfflinePage() {
  const { t } = useTranslation();
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 p-6 text-center">
      <p className="text-lg font-semibold">{t('portal.offline')}</p>
      <Button onClick={() => window.location.reload()}>{t('common.retry')}</Button>
    </div>
  );
}
