import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowDownRight, ArrowUpRight, Pin, RefreshCw, Settings2 } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { ChartView, Sparkline, type ChartData } from '@/components/charts/ChartView';
import { fmtNumber } from '@/components/charts/format';
import { PageHeader } from '@/components/shared/PageHeader';
import { ScopeTabs } from '@/components/shared/ScopeTabs';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { anApi } from '@/features/analytics/api';
import { drillUrl } from '@/features/analytics/components/drill';
import { useDashboard } from '@/hooks/useDashboard';
import { useAuthStore } from '@/store/authStore';
import { cn } from '@/utils/cn';
import type { VisibilityMeta } from '@/utils/types';

// Role dashboard (Prompts/35 §35.9): widgets come from `GET /dashboard` — the API decides the composition, permissions,
// features and visibility; this page lays them out, toggles chart/table, drills down and personalises (pins / hidden).
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;

const SPAN: Record<string, string> = { sm: 'col-span-1', md: 'col-span-1 md:col-span-2', lg: 'col-span-1 md:col-span-2 xl:col-span-3', xl: 'col-span-1 md:col-span-2 xl:col-span-4' };

function formatStat(v: unknown, fmt?: string) {
  if (v === null || v === undefined) return '—';
  const n = Number(v);
  if (fmt === 'pct') return `${fmtNumber(n)}%`;
  if (fmt === 'inr') return `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
  return fmtNumber(n);
}

function StatWidget({ w }: { w: Any }) {
  const s = w.stat ?? {};
  const up = typeof s.delta === 'number' && s.delta > 0;
  const good = s.on_target;
  return (
    <Card className="h-full">
      <CardContent className="space-y-1 p-4">
        <p className="truncate text-xs font-medium uppercase tracking-wide text-muted-foreground">{w.title}</p>
        <div className="flex items-end justify-between gap-2">
          <p className="text-2xl font-semibold tabular-nums">{formatStat(s.value, s.format)}</p>
          <Sparkline points={s.sparkline ?? []} />
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {s.target !== null && s.target !== undefined && (
            <span className={cn('rounded px-1.5 py-0.5', good === false ? 'bg-red-100 text-red-800' : 'bg-emerald-100 text-emerald-800')}>target {formatStat(s.target, s.format)}</span>
          )}
          {typeof s.delta === 'number' && s.delta !== 0 && (
            <span className="inline-flex items-center text-muted-foreground">
              {up ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
              {fmtNumber(Math.abs(s.delta))}
            </span>
          )}
          {s.class_average !== null && s.class_average !== undefined && <span className="text-muted-foreground">class average {formatStat(s.class_average, s.format)}</span>}
          {w.route && <Link to={w.route} className="ml-auto text-primary underline">open</Link>}
        </div>
      </CardContent>
    </Card>
  );
}

function ListWidget({ w }: { w: Any }) {
  const items: Any[] = w.items ?? [];
  return (
    <Card className="h-full">
      <CardContent className="space-y-2 p-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold">{w.title}</h3>
          {w.route && <Link to={w.route} className="text-xs text-primary underline">open</Link>}
        </div>
        {!items.length && <p className="text-sm text-muted-foreground">Nothing here.</p>}
        <ul className="divide-y text-sm">
          {items.map((i) => (
            <li key={i.id} className="flex items-center justify-between gap-2 py-1.5">
              <Link to={i.route ?? w.route ?? '#'} className="truncate hover:underline">{i.title}</Link>
              <span className="shrink-0 text-xs text-muted-foreground">{i.meta}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function ActionWidget({ w }: { w: Any }) {
  return (
    <Link to={w.route ?? '#'} className="block h-full">
      <Card className="flex h-full items-center justify-center p-4 text-sm font-medium hover:bg-accent">{w.title}</Card>
    </Link>
  );
}

function Unavailable({ w }: { w: Any }) {
  return (
    <Card className="h-full">
      <CardContent className="p-4 text-sm">
        <p className="font-medium">{w.title ?? w.key}</p>
        <p className="text-muted-foreground">Unavailable{w.reason ? ` (${w.reason})` : ''}</p>
      </CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const user = useAuthStore((s) => s.currentUser);
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const role = params.get('role') ?? undefined;
  const scope = params.get('scope') ?? undefined;
  const [personalise, setPersonalise] = useState(false);
  const q = useDashboard({ role, scope });
  const d: Any = q.data?.data ?? null;
  const visibility = q.data?.meta?.visibility as VisibilityMeta | undefined;

  useEffect(() => {
    document.title = 'Dashboard';
  }, []);
  useEffect(() => {
    if (q.updated) toast.success('Dashboard updated');
  }, [q.updated]);

  const set = (k: string, v?: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    setParams(next, { replace: true });
  };
  const widgets: Any[] = useMemo(() => d?.widgets ?? [], [d]);
  const stale = widgets.some((w) => w.stale);
  const lastRefreshed = useMemo(() => {
    const ts = widgets.map((w) => (w.generated_at ? new Date(w.generated_at).getTime() : 0)).filter(Boolean);
    return ts.length ? new Date(Math.min(...ts)) : null;
  }, [widgets]);

  const render = (w: Any): ReactNode => {
    if (w.unavailable) return <Unavailable w={w} />;
    if (w.kind === 'stat') return <StatWidget w={w} />;
    if (w.kind === 'list') return <ListWidget w={w} />;
    if (w.kind === 'action') return <ActionWidget w={w} />;
    const data = w.data as ChartData;
    return (
      <ChartView
        data={data}
        title={w.title}
        onPoint={(p) => {
          const url = drillUrl(data, p);
          if (url) navigate(url);
        }}
      />
    );
  };

  return (
    <div className="space-y-4 print:space-y-2">
      <PageHeader
        title={`Welcome${user?.display_name ? `, ${user.display_name}` : ''}`}
        description={d ? `${String(d.role).replace(/_/g, ' ')} dashboard${lastRefreshed ? ` · data as of ${lastRefreshed.toLocaleTimeString()}` : ''}` : 'Loading your dashboard…'}
        actions={
          <div className="flex flex-wrap items-center gap-2 print:hidden">
            {stale && <span className="rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-800">stale</span>}
            {(d?.roles?.length ?? 0) > 1 && (
              <select aria-label="Dashboard role" className="h-9 rounded-md border bg-background px-2 text-sm" value={d.role} onChange={(e) => set('role', e.target.value)}>
                {d.roles.map((r: string) => <option key={r} value={r}>{r.replace(/_/g, ' ')}</option>)}
              </select>
            )}
            <Button variant="outline" size="sm" onClick={() => void q.refetch()} aria-label="Refresh"><RefreshCw className="h-4 w-4" /></Button>
            <Button variant="outline" size="sm" onClick={() => setPersonalise(true)}><Settings2 className="mr-1 h-4 w-4" />Personalise</Button>
          </div>
        }
      />
      {visibility && visibility.scopes.length > 0 && <ScopeTabs visibility={visibility} value={scope} onChange={(s) => set('scope', s)} />}
      {q.isError && <p className="text-sm text-destructive">{getApiError(q.error)}</p>}
      {(d?.alerts ?? []).length > 0 && (
        <div className="space-y-1">
          {d.alerts.map((a: Any, i: number) => (
            <div key={i} className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              {a.kind === 'kpi' && `${String(a.key).replace(/_/g, ' ')} is ${a.value ?? '—'} against a target of ${a.target}${a.scope && a.scope !== 'all' ? ' (college)' : ''}`}
              {a.kind === 'approvals' && <Link to={a.route} className="underline">{a.count} approval(s) waiting for you</Link>}
              {a.kind === 'read_only' && a.message}
            </div>
          ))}
        </div>
      )}
      {d?.risk && (
        <Card><CardContent className="p-4 text-sm">Your current early-warning level: <strong>{d.risk.level}</strong>. Talk to your mentor for support.</CardContent></Card>
      )}
      <div className="grid auto-rows-min grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        {widgets.map((w) => (
          <div key={w.key} className={SPAN[w.size] ?? SPAN.md}>{render(w)}</div>
        ))}
      </div>
      {personalise && d && <PersonaliseDrawer widgets={widgets} onClose={() => setPersonalise(false)} onSaved={() => void q.refetch()} />}
    </div>
  );
}

function PersonaliseDrawer({ widgets, onClose, onSaved }: { widgets: Any[]; onClose: () => void; onSaved: () => void }) {
  const [pinned, setPinned] = useState<string[]>([]);
  const [hidden, setHidden] = useState<string[]>([]);
  const toggle = (list: string[], set: (v: string[]) => void, k: string) => set(list.includes(k) ? list.filter((x) => x !== k) : [...list, k]);
  const save = async () => {
    try {
      await anApi.pins({ pinned_keys: pinned, hidden_keys: hidden });
      toast.success('Dashboard saved');
      onSaved();
      onClose();
    } catch (e) {
      toast.error(getApiError(e));
    }
  };
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Personalise dashboard" description="Pin widgets to the top or hide them (within what your role allows)." footer={<div className="flex gap-2"><Button variant="outline" onClick={async () => { await anApi.pins({ pinned_keys: [], hidden_keys: [] }); onSaved(); onClose(); }}>Reset</Button><Button onClick={() => void save()}>Save</Button></div>}>
      <ul className="max-h-[60vh] divide-y overflow-auto text-sm">
        {widgets.map((w) => (
          <li key={w.key} className="flex items-center justify-between gap-2 py-1.5">
            <span className="truncate">{w.title ?? w.key}</span>
            <span className="flex gap-1">
              <Button size="sm" variant={pinned.includes(w.key) ? 'default' : 'ghost'} onClick={() => toggle(pinned, setPinned, w.key)} aria-label="Pin"><Pin className="h-3.5 w-3.5" /></Button>
              <Button size="sm" variant={hidden.includes(w.key) ? 'default' : 'ghost'} onClick={() => toggle(hidden, setHidden, w.key)}>{hidden.includes(w.key) ? 'Hidden' : 'Hide'}</Button>
            </span>
          </li>
        ))}
      </ul>
    </Modal>
  );
}
