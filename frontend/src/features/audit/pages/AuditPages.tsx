import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { ScopeTabs } from '@/components/shared/ScopeTabs';
import { SettingsField } from '@/components/shared/SettingsField';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { SimpleTable } from '@/features/hr/components/shared';
import { usePermission } from '@/hooks/usePermission';
import { auditApi, EXAM_SECTIONS } from '../api';

// Phase 37 web screens (Prompts/37 §37.9). Scope narrowing, PII masking, decode visibility, locks, reasons and
// retention maximums are enforced by the API; these pages render what it returns.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));
const useQ = <T,>(key: unknown[], fn: () => Promise<T>, enabled = true) => useQuery({ queryKey: ['audit', ...key], queryFn: fn, retry: false, enabled });
function useRun() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(), onSuccess: () => qc.invalidateQueries({ queryKey: ['audit'] }), onError: fail });
}
const list = (r: Any): Any[] => (Array.isArray(r?.data) ? r.data : Array.isArray(r?.data?.items) ? r.data.items : []);
const sel = 'h-9 rounded-md border bg-background px-2 text-sm';
const dt = (v: unknown) => (v ? new Date(String(v)).toLocaleString() : '—');
const daysAgo = (n: number) => new Date(Date.now() - n * 86400000).toISOString().slice(0, 10);
const show = (v: unknown) => (v === null || v === undefined ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v));
const SEV: Record<string, 'info' | 'secondary' | 'warning' | 'destructive'> = { info: 'secondary', low: 'info', medium: 'warning', high: 'destructive' };

function Section({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <Card><CardContent className="space-y-3 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-sm font-semibold">{title}</h2>{action}</div>{children}</CardContent></Card>;
}
function Err({ q }: { q: Any }) {
  return q.isError ? <p className="text-sm text-destructive">{getApiError(q.error)}</p> : null;
}

// ---- explorer ---------------------------------------------------------------------------------------------------------
function AuditDrawer({ id, onClose }: { id: string | null; onClose: () => void }) {
  const q = useQ(['detail', id], () => auditApi.detail(id!), !!id);
  const d: Any = q.data?.data;
  return (
    <Modal open={!!id} onOpenChange={(o) => !o && onClose()} title={d ? `${d.module}:${d.action}` : 'Audit row'} description={d?.summary} size="xl">
      <Err q={q} />
      {d && (
        <div className="space-y-3 text-sm">
          <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
            <span>When: {dt(d.occurred_at)}</span>
            <span>By: {d.user?.name ?? '—'}{d.impersonator ? ` (impersonated by ${d.impersonator.name})` : ''}</span>
            <span>Record: {d.record_type} {d.record_id}</span>
            <span>IP: {d.ip_masked ?? '—'} · request {d.request_id ?? '—'}</span>
          </div>
          <SimpleTable
            head={['Field', 'Before', 'After']}
            rows={(d.diff ?? []).map((x: Any) => [<span key="f">{x.field}{x.masked && <Badge variant="warning" className="ml-1">masked</Badge>}</span>, show(x.old), show(x.new)])}
            empty="No field changes recorded."
          />
          {d.related?.length > 0 && (
            <SimpleTable head={['Related (same request)', 'When']} rows={d.related.map((r: Any) => [r.summary, dt(r.occurred_at)])} />
          )}
          <p className="break-all font-mono text-[10px] text-muted-foreground">hash {d.hash} · prev {d.prev_hash ?? '—'}</p>
        </div>
      )}
    </Modal>
  );
}

export function AuditExplorerPage() {
  useTitle('Audit logs');
  const { can } = usePermission();
  const [sp, setSp] = useSearchParams();
  const [open, setOpen] = useState<string | null>(null);
  const [f, setF] = useState<Record<string, string>>({ from: daysAgo(30), to: '', module: '', action: '', record_type: '', record_id: '', q: '' });
  const [imp, setImp] = useState(false);
  const [page, setPage] = useState(1);
  const scope = sp.get('scope') ?? undefined;
  const params = { ...f, impersonator_only: imp || undefined, scope, page, page_size: 50 };
  const q = useQ(['list', params], () => auditApi.list(params));
  const run = useRun();
  const data: Any = q.data?.data;
  return (
    <div className="space-y-4">
      <PageHeader
        title="Audit logs"
        description="Who did what, when — scoped to your reach; personal data masked unless you hold the record module's view_pii."
        actions={
          <div className="flex gap-2">
            <Link to="/admin/audit-logs/integrity"><Button variant="outline" size="sm">Integrity</Button></Link>
            {can('audit_logs', 'export') && <Button size="sm" onClick={() => run.mutate(async () => { await auditApi.export(params, 'csv'); toast.success('Export queued — the file arrives in the jobs tray'); })}>Export</Button>}
          </div>
        }
      />
      <ScopeTabs visibility={q.data?.meta?.visibility} value={scope} onChange={(s) => setSp({ scope: s })} />
      <div className="flex flex-wrap items-end gap-2">
        {(['from', 'to'] as const).map((k) => <Input key={k} type="date" className="w-40" value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} />)}
        {(['module', 'action', 'record_type', 'record_id', 'q'] as const).map((k) => <Input key={k} className="w-36" placeholder={k.replace('_', ' ')} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} />)}
        <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={imp} onChange={(e) => setImp(e.target.checked)} /> impersonated only</label>
      </div>
      <Err q={q} />
      <SimpleTable
        head={['When', 'Module', 'Action', 'Summary', 'User', 'IP', '']}
        rows={list(q.data).map((r) => [
          dt(r.occurred_at), r.module, r.action, r.summary,
          <span key="u">{r.user?.name ?? '—'}{r.impersonator && <Badge variant="destructive" className="ml-1">impersonated</Badge>}</span>,
          r.ip_masked ?? '—',
          r.has_diff ? <Button key="d" size="sm" variant="ghost" onClick={() => setOpen(r.id)}>Diff</Button> : <Button key="d" size="sm" variant="ghost" onClick={() => setOpen(r.id)}>Open</Button>,
        ])}
      />
      {data && (
        <div className="flex items-center gap-2 text-sm">
          <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
          <span>Page {data.page} · {data.total} rows</span>
          <Button size="sm" variant="outline" disabled={page * data.page_size >= data.total} onClick={() => setPage(page + 1)}>Next</Button>
        </div>
      )}
      <AuditDrawer id={open} onClose={() => setOpen(null)} />
    </div>
  );
}

// ---- integrity --------------------------------------------------------------------------------------------------------
export function AuditIntegrityPage() {
  useTitle('Audit integrity');
  const [from, setFrom] = useState(daysAgo(7));
  const [res, setRes] = useState<Any>(null);
  const digests = useQ(['digests'], () => auditApi.digests());
  const verify = useMutation({ mutationFn: () => auditApi.verify({ from }), onSuccess: (r) => setRes(r.data), onError: fail });
  return (
    <div className="space-y-4">
      <PageHeader title="Audit integrity" description="Recompute the hash chain and compare it with the signed daily digests held in cold storage." />
      <Section title="Verify a range" action={<div className="flex gap-2"><Input type="date" className="w-40" value={from} onChange={(e) => setFrom(e.target.value)} /><Button size="sm" loading={verify.isPending} onClick={() => verify.mutate()}>Verify</Button></div>}>
        {verify.isPending && <p className="text-sm text-muted-foreground">Walking the chain in batches of 10 000…</p>}
        {res && (
          <div className={`rounded border p-3 text-sm ${res.ok ? 'border-status-approved' : 'border-destructive'}`}>
            <p className="font-semibold">{res.ok ? 'Chain intact' : 'Chain broken'} — {res.rows} rows in {res.duration_ms} ms</p>
            {res.first_broken && <p>First broken row {res.first_broken.id} at {dt(res.first_broken.occurred_at)} ({res.first_broken.reason})</p>}
            {res.digest_mismatches?.length > 0 && <p>Digest mismatches: {res.digest_mismatches.join(', ')}</p>}
            <p className="break-all font-mono text-[10px]">digest {res.digest}</p>
          </div>
        )}
      </Section>
      <Section title="Daily digests">
        <Err q={digests} />
        <SimpleTable
          head={['Date', 'Rows', 'Digest', 'Signed', 'Archived']}
          rows={list(digests.data).map((d) => [d.date, d.rows, <span key="g" className="font-mono text-[10px]">{String(d.digest).slice(0, 16)}…</span>,
            d.signed ? <Badge key="s" variant="success">signed</Badge> : <Badge key="s" variant="destructive">unsigned</Badge>,
            d.archived_url ? <a key="a" className="text-primary underline" href={d.archived_url} target="_blank" rel="noreferrer">file</a> : '—'])}
        />
      </Section>
    </div>
  );
}

// ---- exam audit -------------------------------------------------------------------------------------------------------
export function ExamAuditPage() {
  useTitle('Exam audit');
  const { sessionId = '' } = useParams();
  const { can } = usePermission();
  const [section, setSection] = useState<string>('marks');
  const summary = useQ(['exam-summary', sessionId], () => auditApi.examSummary(sessionId), !!sessionId);
  const q = useQ(['exam', sessionId, section], () => auditApi.examSection(sessionId, section), !!sessionId);
  const run = useRun();
  const s: Any = summary.data?.data;
  const sections = EXAM_SECTIONS.filter((x) => x !== 'decode' || s?.decode_visible || can('exams', 'decode'));
  return (
    <div className="space-y-4">
      <PageHeader
        title={`Exam audit${s ? ` — ${s.session_name}` : ''}`}
        description="Marks, question-paper print, custody, valuation, moderation, decode, runs, publication and post-result trails."
        actions={<Button size="sm" onClick={() => run.mutate(async () => { await auditApi.examExport(sessionId); toast.success('Exam audit report queued'); })}>Export report</Button>}
      />
      {s && (
        <div className="flex flex-wrap gap-2 text-xs">
          {Object.entries(s.sections as Record<string, number>).map(([k, v]) => <Badge key={k} variant="secondary">{k.replace('_', ' ')}: {v}</Badge>)}
          <Badge variant={s.open_gaps ? 'destructive' : 'success'}>gaps: {s.open_gaps}</Badge>
          {s.days_to_publication != null && <Badge variant="info">{s.days_to_publication} days to publication</Badge>}
        </div>
      )}
      <div className="flex flex-wrap gap-1">
        {sections.map((x) => <Button key={x} size="sm" variant={section === x ? 'default' : 'outline'} onClick={() => setSection(x)}>{x.replace('_', ' ')}</Button>)}
      </div>
      <Err q={q} />
      {q.data?.data?.summary && <p className="text-xs text-muted-foreground">{Object.entries(q.data.data.summary).map(([k, v]) => `${k}: ${v}`).join(' · ')}</p>}
      <SimpleTable
        head={['When', 'Actor', 'Action', 'Subject', 'Details', 'IP']}
        rows={(q.data?.data?.entries ?? []).map((e: Any) => [
          <span key="w" className={e.gap ? 'font-semibold text-destructive' : ''}>{dt(e.at)}{e.gap && ' · gap'}</span>,
          e.actor?.name ?? '—', e.action, e.subject ?? '—', <span key="d" className="text-xs">{show(e.details)}</span>, e.ip_masked ?? '—',
        ])}
      />
    </div>
  );
}

// ---- security ---------------------------------------------------------------------------------------------------------
export function SecurityPage() {
  useTitle('Security');
  const [type, setType] = useState('');
  const [ackId, setAckId] = useState<string | null>(null);
  const [note, setNote] = useState('');
  const [user, setUser] = useState('');
  const events = useQ(['events', type], () => auditApi.events({ type: type || undefined }));
  const anomalies = useQ(['anomalies'], () => auditApi.anomalies(true));
  const sessions = useQ(['sessions', user], () => auditApi.sessions({ user_id: user || undefined }));
  const logins = useQ(['logins', user], () => auditApi.loginHistory({ user_id: user || undefined }));
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Security" description="Login failures, lockouts, session revocations, impersonation, allow-list and API-key changes, exports and PII unmasks." />
      <Section title="Anomaly alerts">
        <Err q={anomalies} />
        <SimpleTable
          head={['Rule', 'Count', 'Users / IPs', 'First seen', 'Actions']}
          rows={list(anomalies.data).map((a) => [a.rule, a.count, [...a.users.map((u: Any) => u.name), ...a.ips].join(', ') || '—', dt(a.first_seen),
            <div key="x" className="flex gap-1">
              <Button size="sm" variant="outline" onClick={() => setAckId(a.id)}>Acknowledge</Button>
              {a.users[0] && <Button size="sm" variant="destructive" onClick={() => run.mutate(() => auditApi.revoke({ user_id: a.users[0].id, all: true, reason: `anomaly ${a.rule}` }))}>Revoke sessions</Button>}
            </div>])}
          empty="No open alerts."
        />
      </Section>
      <Section title="Events" action={<select className={sel} value={type} onChange={(e) => setType(e.target.value)}>{['', 'login_failed', 'locked', 'mfa_failed', 'session_revoked', 'impersonation', 'ip_allowlist_change', 'api_key', 'export', 'pii_unmask', 'feature_toggle', 'settings_change'].map((t) => <option key={t} value={t}>{t || 'all types'}</option>)}</select>}>
        <Err q={events} />
        <SimpleTable head={['When', 'Type', 'Severity', 'User', 'IP', 'Details']} rows={list(events.data).slice(0, 200).map((e) => [dt(e.at), e.type, <Badge key="s" variant={SEV[e.severity] ?? 'secondary'}>{e.severity}</Badge>, e.user?.name ?? e.identifier ?? '—', e.ip_masked ?? '—', <span key="d" className="text-xs">{show(e.details)}</span>])} />
      </Section>
      <Section title="Sessions across users" action={<Input className="w-72" placeholder="user id (optional)" value={user} onChange={(e) => setUser(e.target.value)} />}>
        <Err q={sessions} />
        <SimpleTable head={['User', 'Device', 'IP', 'Last seen', '']} rows={list(sessions.data).map((s) => [s.user?.name ?? '—', s.device_label ?? s.platform ?? '—', s.ip_masked ?? '—', dt(s.last_seen_at),
          <Button key="r" size="sm" variant="outline" onClick={() => run.mutate(() => auditApi.revoke({ session_id: s.id }))}>Revoke</Button>])} />
      </Section>
      <Section title="Login history">
        <Err q={logins} />
        <SimpleTable head={['When', 'User', 'Outcome', 'IP']} rows={list(logins.data).slice(0, 200).map((l) => [dt(l.occurred_at), l.user?.name ?? l.identifier ?? '—', l.outcome, l.ip_masked ?? '—'])} />
      </Section>
      <Modal open={!!ackId} onOpenChange={(o) => !o && setAckId(null)} title="Acknowledge alert"
        footer={<Button disabled={note.length < 2} onClick={() => run.mutate(async () => { await auditApi.ack(ackId!, note); setAckId(null); setNote(''); })}>Acknowledge</Button>}>
        <Input placeholder="What was done" value={note} onChange={(e) => setNote(e.target.value)} />
      </Modal>
    </div>
  );
}

// ---- settings catalogue -----------------------------------------------------------------------------------------------
export function SettingsCataloguePage() {
  useTitle('Settings');
  const { can } = usePermission();
  const [cat, setCat] = useState('');
  const [q, setQ] = useState('');
  const [college, setCollege] = useState('');
  const [edits, setEdits] = useState<Record<string, unknown>>({});
  const [reasonFor, setReasonFor] = useState<string[] | null>(null);
  const [reason, setReason] = useState('');
  const [histKey, setHistKey] = useState<string | null>(null);
  const [since, setSince] = useState('');
  const [importDoc, setImportDoc] = useState('');
  const [report, setReport] = useState<Any>(null);
  const catalogue = useQ(['catalogue'], () => auditApi.catalogue());
  const effective = useQ(['effective', college], () => auditApi.effective({ college_id: college || undefined }));
  const history = useQ(['history', histKey], () => auditApi.history({ key: histKey!, from: daysAgo(365) }), !!histKey);
  const changes = useQ(['since', since], () => auditApi.changesSince(since), !!since);
  const qc = useQueryClient();
  const defs = list(catalogue.data);
  const eff = useMemo(() => Object.fromEntries(list(effective.data).map((e) => [e.key, e])), [effective.data]);
  const cats = useMemo(() => [...new Set(defs.map((d) => d.category))].sort(), [defs]);
  const shown = defs.filter((d) => (!cat || d.category === cat) && (!q || `${d.key} ${d.label}`.toLowerCase().includes(q.toLowerCase())));
  const manage = can('settings', 'manage');
  const save = async (withReason?: string) => {
    const items = Object.entries(edits).map(([k, value]) => {
      const [category, ...rest] = k.split('.');
      return { category, key: rest.join('.'), value, college_id: college || undefined };
    });
    try {
      await auditApi.save(items, withReason);
      toast.success('Settings saved');
      setEdits({});
      setReasonFor(null);
      setReason('');
      qc.invalidateQueries({ queryKey: ['audit'] });
    } catch (e) {
      fail(e);
    }
  };
  const trySave = () => {
    const sensitive = Object.keys(edits).filter((k) => defs.find((d) => d.key === k)?.sensitive);
    if (sensitive.length) setReasonFor(sensitive);
    else void save();
  };
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader
        title="Settings"
        description="Every key with its type, default, source (college / institution / platform / default), locks and dependencies."
        actions={
          <div className="flex flex-wrap gap-2">
            <Link to="/admin/settings/classic"><Button size="sm" variant="outline">Branding & providers</Button></Link>
            <Link to="/admin/settings/feature-changes"><Button size="sm" variant="outline">Feature changes</Button></Link>
            {manage && <Button size="sm" variant="outline" onClick={() => run.mutate(async () => { const r = await auditApi.exportSettings(); setImportDoc(JSON.stringify(r.data, null, 1)); })}>Export</Button>}
            {manage && Object.keys(edits).length > 0 && <Button size="sm" onClick={trySave}>Save {Object.keys(edits).length}</Button>}
          </div>
        }
      />
      <div className="flex flex-wrap items-center gap-2">
        <Input className="w-64" placeholder="Search keys" value={q} onChange={(e) => setQ(e.target.value)} />
        <Input className="w-72" placeholder="College id (overrides)" value={college} onChange={(e) => setCollege(e.target.value)} />
        <label className="flex items-center gap-1 text-sm">What changed since <Input type="date" className="w-40" value={since} onChange={(e) => setSince(e.target.value)} /></label>
      </div>
      {since && <SimpleTable head={['Key', 'Then', 'Now', 'Changed']} rows={list(changes.data).map((c) => [c.key, show(c.before), show(c.after), dt(c.changed_at)])} empty="No changes since that date." />}
      <div className="grid gap-4 md:grid-cols-[200px_1fr]">
        <nav className="space-y-1 text-sm">
          <button type="button" className={`block w-full rounded px-2 py-1 text-left ${!cat ? 'bg-muted font-semibold' : ''}`} onClick={() => setCat('')}>All categories</button>
          {cats.map((c) => <button key={c} type="button" className={`block w-full rounded px-2 py-1 text-left ${cat === c ? 'bg-muted font-semibold' : ''}`} onClick={() => setCat(c)}>{c}</button>)}
        </nav>
        <div className="space-y-2">
          <Err q={catalogue} />
          {shown.map((d) => {
            const e = eff[d.key];
            const locked = d.locked_by !== 'none' || d.scope === 'platform';
            const value = d.key in edits ? edits[d.key] : e?.value;
            return (
              <div key={d.key} className="rounded border p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{d.label}</span>
                  <code className="text-xs text-muted-foreground">{d.key}</code>
                  {e && <Badge variant={e.source === 'college' ? 'info' : e.source === 'institution' ? 'default' : 'secondary'}>{e.source}</Badge>}
                  {locked && <Badge variant="warning">locked: {d.lock_reason ?? d.locked_by}</Badge>}
                  {d.overridden_in_colleges > 0 && <Badge variant="outline">overridden in {d.overridden_in_colleges} colleges</Badge>}
                  {d.sensitive && <Badge variant="destructive">sensitive</Badge>}
                  {d.requires_restart && <Badge variant="outline">restart</Badge>}
                  <Button size="sm" variant="ghost" onClick={() => setHistKey(d.key)}>History</Button>
                  {manage && !locked && e?.source === 'institution' && !college && <Button size="sm" variant="ghost" onClick={() => run.mutate(() => auditApi.reset(d.key, d.sensitive ? window.prompt('Reason') ?? undefined : undefined))}>Reset</Button>}
                  {manage && college && e?.source === 'college' && <Button size="sm" variant="ghost" onClick={() => run.mutate(() => auditApi.clearOverride(d.key, college, d.sensitive ? window.prompt('Reason') ?? undefined : undefined))}>Clear override</Button>}
                </div>
                {d.dependency_hint && <p className="text-xs text-muted-foreground">Depends on {d.depends_on.join(', ')} — {d.dependency_hint}</p>}
                <div className="mt-2">
                  <SettingsField type={d.type} value={value} choices={d.choices} min={d.min} max={d.max} disabled={!manage || locked || (!!college && d.scope !== 'college')} onChange={(v) => setEdits({ ...edits, [d.key]: v })} />
                </div>
              </div>
            );
          })}
        </div>
      </div>
      {manage && (
        <Section title="Import" action={<div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => run.mutate(async () => { const r = await auditApi.importSettings(JSON.parse(importDoc || '{}'), true, reason || undefined); setReport(r.data); })}>Dry run</Button>
          <Button size="sm" disabled={!report} onClick={() => run.mutate(async () => { const r = await auditApi.importSettings(JSON.parse(importDoc || '{}'), false, reason || 'settings import'); setReport(r.data); })}>Apply</Button>
        </div>}>
          <textarea className="min-h-[120px] w-full rounded-md border bg-background p-2 font-mono text-xs" value={importDoc} onChange={(e) => setImportDoc(e.target.value)} placeholder='{"values": {"fees.late_fee_grace_days": 5}}' />
          {report && <p className="text-sm">{report.dry_run ? 'Dry run' : 'Applied'}: {report.applied.length} applied, {report.unchanged.length} unchanged, {report.skipped_locked.length} locked skipped ({report.skipped_locked.join(', ')}), {report.invalid.length} invalid</p>}
        </Section>
      )}
      <Modal open={!!reasonFor} onOpenChange={(o) => !o && setReasonFor(null)} title="Reason required" description={`Sensitive keys: ${(reasonFor ?? []).join(', ')}`}
        footer={<Button disabled={reason.trim().length < 3} onClick={() => void save(reason)}>Save</Button>}>
        <Input placeholder="Why is this changing?" value={reason} onChange={(e) => setReason(e.target.value)} />
      </Modal>
      <Modal open={!!histKey} onOpenChange={(o) => !o && setHistKey(null)} title={`History — ${histKey}`} size="lg">
        <Err q={history} />
        <SimpleTable head={['When', 'Old', 'New', 'By', 'Reason']} rows={list(history.data).map((h) => [dt(h.at), show(h.old), show(h.new), h.actor_name ?? '—', h.reason ?? '—'])} empty="No changes recorded." />
      </Modal>
    </div>
  );
}

export function FeatureChangesPage() {
  useTitle('Feature changes');
  const fc = useQ(['feature-changes'], () => auditApi.featureChanges({ from: daysAgo(365) }));
  const pa = useQ(['platform-actions'], () => auditApi.platformActions({ from: daysAgo(90) }));
  return (
    <div className="space-y-4">
      <PageHeader title="Feature changes" description="Feature-flag changes of your institution and platform (super-admin) actions affecting it." />
      <Section title="Feature flag log">
        <Err q={fc} />
        <SimpleTable head={['When', 'Feature', 'Old', 'New', 'By', 'Reason']} rows={list(fc.data).map((r) => [dt(r.changed_at), r.feature_key, show(r.old_value), show(r.new_value),
          <span key="b">{r.changed_by?.name ?? '—'}{r.platform_actor && <Badge variant="info" className="ml-1">platform</Badge>}</span>, r.reason ?? '—'])} />
      </Section>
      <Section title="Platform actions">
        <Err q={pa} />
        <SimpleTable head={['When', 'Summary', 'By', 'Impersonator']} rows={list(pa.data).map((r) => [dt(r.occurred_at), r.summary, r.user?.name ?? '—', r.impersonator?.name ?? '—'])} />
      </Section>
    </div>
  );
}

// ---- retention --------------------------------------------------------------------------------------------------------
const PURGE = ['login_history', 'notifications', 'message_logs', 'domain_events', 'webhook_deliveries', 'job_files', 'report_files', 'document_previews', 'visitor_pii', 'gps_logs'];
const ARCHIVE = ['attendance', 'message_logs', 'audit_logs'];

export function RetentionPage() {
  useTitle('Retention');
  const pol = useQ(['policies'], () => auditApi.policies());
  const manifests = useQ(['manifests'], () => auditApi.manifests());
  const holds = useQ(['holds'], () => auditApi.holds(true));
  const [vals, setVals] = useState<Record<string, number>>({});
  const [dc, setDc] = useState('login_history');
  const [period, setPeriod] = useState('');
  const [hold, setHold] = useState({ data_class: 'message_logs', batch_id: '', reason: '' });
  const preview = useQ(['preview', dc], () => auditApi.preview(dc));
  const run = useRun();
  const p: Any = pol.data?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="Retention & archival" description="Retention per data class (never beyond the platform maximum), purges, archives with sha256 manifests and legal holds." />
      <Section title="Policy" action={<Button size="sm" disabled={!Object.keys(vals).length} onClick={() => run.mutate(async () => { await auditApi.putPolicies(vals, 'retention policy update'); setVals({}); toast.success('Saved'); })}>Save</Button>}>
        <Err q={pol} />
        {p && (
          <div className="grid gap-2 md:grid-cols-3">
            {Object.entries(p.maximums as Record<string, number>).map(([k, max]) => (
              <label key={k} className="text-sm">
                <span className="block text-xs text-muted-foreground">{k} (max {max})</span>
                <Input type="number" min={p.minimums[k] ?? 1} max={max} value={vals[k] ?? p.values[k] ?? ''} onChange={(e) => setVals({ ...vals, [k]: Number(e.target.value) })} />
              </label>
            ))}
          </div>
        )}
      </Section>
      <Section title="Preview & run" action={<select className={sel} value={dc} onChange={(e) => setDc(e.target.value)}>{[...new Set([...PURGE, ...ARCHIVE])].map((x) => <option key={x}>{x}</option>)}</select>}>
        <Err q={preview} />
        {preview.data?.data && <p className="text-sm">Eligible: {preview.data.data.eligible} · held: {preview.data.data.held}{preview.data.data.cutoff ? ` · older than ${dt(preview.data.data.cutoff)}` : ''}</p>}
        <div className="flex flex-wrap gap-2">
          {PURGE.includes(dc) && <Button size="sm" variant="destructive" onClick={() => run.mutate(async () => { await auditApi.purge(dc); toast.success('Purge queued'); })}>Purge now</Button>}
          {ARCHIVE.includes(dc) && (
            <>
              <Input className="w-40" placeholder="2022-23 or 2023-04" value={period} onChange={(e) => setPeriod(e.target.value)} />
              <Button size="sm" disabled={!period} onClick={() => run.mutate(async () => { await auditApi.archive(dc, period); toast.success('Archive queued'); })}>Archive</Button>
            </>
          )}
        </div>
      </Section>
      <Section title="Manifests">
        <Err q={manifests} />
        <SimpleTable head={['When', 'Kind', 'Class', 'Period', 'Rows', 'sha256', 'File']} rows={list(manifests.data).map((m) => [dt(m.created_at), m.kind, m.data_class, m.period ?? '—', m.rows,
          <span key="s" className="font-mono text-[10px]">{m.sha256 ? `${String(m.sha256).slice(0, 12)}…` : '—'}</span>,
          m.file_url ? <a key="f" className="text-primary underline" href={m.file_url} target="_blank" rel="noreferrer">download</a> : '—'])} />
      </Section>
      <Section title="Legal holds">
        <Err q={holds} />
        <SimpleTable head={['Class', 'Scope', 'Reason', 'Until', '']} rows={list(holds.data).map((h) => [h.data_class, show(h.scope), h.reason, h.until ?? '—',
          <Button key="c" size="sm" variant="outline" onClick={() => run.mutate(() => auditApi.clearHold(h.id))}>Clear</Button>])} empty="No active holds." />
        <div className="flex flex-wrap gap-2">
          <select className={sel} value={hold.data_class} onChange={(e) => setHold({ ...hold, data_class: e.target.value })}>{['all', ...PURGE, ...ARCHIVE].map((x) => <option key={x}>{x}</option>)}</select>
          <Input className="w-72" placeholder="batch id" value={hold.batch_id} onChange={(e) => setHold({ ...hold, batch_id: e.target.value })} />
          <Input className="w-72" placeholder="reason" value={hold.reason} onChange={(e) => setHold({ ...hold, reason: e.target.value })} />
          <Button size="sm" disabled={!hold.batch_id || hold.reason.length < 3} onClick={() => run.mutate(() => auditApi.addHold({ data_class: hold.data_class, scope: { batch_id: hold.batch_id }, reason: hold.reason }))}>Add hold</Button>
        </div>
      </Section>
    </div>
  );
}
