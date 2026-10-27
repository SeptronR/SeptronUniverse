import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Star } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { ReportParamsForm, type JsonSchema } from '@/components/shared/ReportParamsForm';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { SimpleTable } from '@/features/hr/components/shared';
import { usePermission } from '@/hooks/usePermission';
import { repApi, type ReportFormat } from '../api';

// Phase 36 web screens (Prompts/36 §36.9). Visibility, scope narrowing, PII masking, feature gates and statutory roles
// are enforced by the API; these pages only render what it returns.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));
const useQ = <T,>(key: unknown[], fn: () => Promise<T>, enabled = true) => useQuery({ queryKey: ['rep', ...key], queryFn: fn, retry: false, enabled });
function useRun() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(), onSuccess: () => qc.invalidateQueries({ queryKey: ['rep'] }), onError: fail });
}
const list = (r: Any): Any[] => (Array.isArray(r?.data) ? r.data : Array.isArray(r?.data?.items) ? r.data.items : []);
const sel = 'h-9 rounded-md border bg-background px-2 text-sm';
const FORMATS: ReportFormat[] = ['xlsx', 'csv', 'pdf', 'docx', 'json'];
const ROLES = ['registrar', 'vice_chancellor', 'controller_of_examinations', 'dean', 'hod', 'faculty', 'accountant', 'hr_officer', 'admissions_officer', 'placement_officer', 'librarian', 'hostel_warden', 'iqac_coordinator', 'research_cell', 'college_admin', 'principal'];

function Section({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <Card><CardContent className="space-y-3 p-4"><div className="flex items-center justify-between gap-2"><h2 className="text-sm font-semibold">{title}</h2>{action}</div>{children}</CardContent></Card>;
}
function Err({ q }: { q: Any }) {
  return q.isError ? <p className="text-sm text-destructive">{getApiError(q.error)}</p> : null;
}
const fmtCell = (v: unknown, type?: string) => {
  if (v === null || v === undefined) return '—';
  if (type === 'money' && typeof v === 'number') return `₹${(v / 100).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`;
  if (type === 'pct' && v !== '') return `${Number(v).toFixed(2)}%`;
  if (typeof v === 'boolean') return v ? 'Yes' : 'No';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
};
async function download(jobId: string) {
  try {
    const r = await repApi.downloadUrl(jobId);
    window.open(r.data?.url, '_blank', 'noopener');
  } catch (e) {
    fail(e);
  }
}

/** Preview table with column chooser and a pivot / summary toggle (counts per value of the first chosen column). */
export function PreviewTable({ preview }: { preview: Any }) {
  const cols: Any[] = preview?.columns ?? [];
  const [hidden, setHidden] = useState<string[]>([]);
  const [pivot, setPivot] = useState(false);
  const shown = cols.filter((c) => !hidden.includes(c.key));
  const rows: Any[] = useMemo(() => preview?.rows ?? [], [preview]);
  const masked: string[] = preview?.masked_fields ?? [];
  const summary = useMemo(() => {
    if (!pivot || !shown.length) return [];
    const k = shown[0].key;
    const nums = shown.filter((c) => ['int', 'number', 'money'].includes(c.type));
    const by = new Map<string, Any>();
    for (const r of rows) {
      const g = String(r[k] ?? '—');
      const acc = by.get(g) ?? { [k]: g, rows: 0 };
      acc.rows += 1;
      for (const c of nums) acc[c.key] = (acc[c.key] ?? 0) + Number(r[c.key] ?? 0);
      by.set(g, acc);
    }
    return [...by.values()];
  }, [pivot, rows, shown]);
  return (
    <div className="space-y-2 print:space-y-0">
      <div className="flex flex-wrap items-center gap-2 text-xs print:hidden">
        <span className="text-muted-foreground">{rows.length} rows{preview?.truncated ? ' (truncated — run as job for all rows)' : ''}</span>
        {masked.length > 0 && <Badge variant="outline">masked: {masked.join(', ')}</Badge>}
        <details className="ml-auto">
          <summary className="cursor-pointer">Columns</summary>
          <div className="absolute z-10 rounded-md border bg-card p-2 shadow">
            {cols.map((c) => (
              <label key={c.key} className="flex items-center gap-1">
                <input type="checkbox" checked={!hidden.includes(c.key)} onChange={(e) => setHidden(e.target.checked ? hidden.filter((h) => h !== c.key) : [...hidden, c.key])} />
                {c.label}
              </label>
            ))}
          </div>
        </details>
        <Button size="sm" variant="outline" onClick={() => setPivot(!pivot)}>{pivot ? 'Rows' : 'Summary'}</Button>
        <Button size="sm" variant="outline" onClick={() => window.print()}>Print</Button>
      </div>
      <div className="max-h-[28rem] overflow-auto">
        {pivot ? (
          <SimpleTable head={[shown[0]?.label ?? '', 'Rows', ...shown.filter((c) => ['int', 'number', 'money'].includes(c.type)).map((c) => c.label)]} rows={summary.map((s) => [s[shown[0].key], s.rows, ...shown.filter((c) => ['int', 'number', 'money'].includes(c.type)).map((c) => fmtCell(s[c.key], c.type))])} />
        ) : (
          <SimpleTable
            head={shown.map((c) => <span key={c.key}>{c.label}{masked.includes(c.key) ? ' 🔒' : ''}</span>)}
            rows={rows.slice(0, 2000).map((r) => shown.map((c) => fmtCell(r[c.key], c.type)))}
          />
        )}
        {preview?.totals && Object.keys(preview.totals).length > 0 && !pivot && (
          <p className="pt-1 text-xs font-medium">Totals: {Object.entries(preview.totals).map(([k, v]) => `${k} ${fmtCell(v, cols.find((c) => c.key === k)?.type)}`).join(' · ')}</p>
        )}
      </div>
    </div>
  );
}

// ---- /admin/reports — catalogue + run drawer ---------------------------------------------------------------------------
export function ReportCataloguePage() {
  useTitle('Reports');
  const navigate = useNavigate();
  const [search] = useSearchParams();
  const [q, setQ] = useState('');
  const [module, setModule] = useState(search.get('module') ?? '');
  const cat = useQ(['catalogue', module], () => repApi.catalogue({ module: module || undefined }));
  const favs = useQ(['favourites'], () => repApi.favourites());
  const run = useRun();
  const [open, setOpen] = useState<Any>(null);
  const [fmt, setFmt] = useState<ReportFormat>('xlsx');
  const [preview, setPreview] = useState<Any>(null);
  const items = list(cat.data).filter((c) => !q || `${c.name} ${c.key} ${c.description}`.toLowerCase().includes(q.toLowerCase()));
  const modules = useMemo(() => Array.from(new Set(list(cat.data).map((c) => c.module))).sort(), [cat.data]);
  const groups = useMemo(() => {
    const m = new Map<string, Any[]>();
    for (const c of items) m.set(c.favourite ? '★ Favourites' : c.category, [...(m.get(c.favourite ? '★ Favourites' : c.category) ?? []), c]);
    return [...m.entries()];
  }, [items]);
  const exec = async (params: Record<string, unknown>, inline: boolean) => {
    try {
      const r = await repApi.run({ key: open.key, params, format: fmt, inline_preview: inline });
      if (inline) setPreview(r.data?.preview);
      else {
        toast.success(`Report queued (job ${String(r.data?.job_id).slice(0, 8)}) — see Runs / the jobs tray`);
        setOpen(null);
      }
    } catch (e) {
      fail(e);
    }
  };
  return (
    <div className="space-y-4">
      <PageHeader title="Reports" description="Catalogue of the reports you may run — every report shows only rows within your scope." actions={<Button size="sm" variant="outline" onClick={() => navigate('/admin/reports/runs')}>Runs</Button>} />
      <div className="flex flex-wrap gap-2">
        <Input aria-label="Search reports" placeholder="Search…" className="w-64" value={q} onChange={(e) => setQ(e.target.value)} />
        <select aria-label="Module" className={sel} value={module} onChange={(e) => setModule(e.target.value)}>
          <option value="">All modules</option>
          {modules.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
      </div>
      <Err q={cat} />
      <div className="grid gap-4 lg:grid-cols-[1fr_16rem]">
        <div className="space-y-4">
          {groups.map(([g, rows]) => (
            <Section key={g} title={g}>
              <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                {rows.map((c) => (
                  <div key={c.key} className="rounded-md border p-3 text-sm">
                    <div className="flex items-start justify-between gap-2">
                      <button type="button" className="text-left font-medium hover:underline" onClick={() => { setOpen(c); setPreview(null); setFmt(c.formats[0]); }}>{c.name}</button>
                      <button type="button" aria-label="Favourite" onClick={() => run.mutate(() => repApi.toggleFavourite(c.key))}>
                        <Star className={`h-4 w-4 ${c.favourite ? 'fill-yellow-400 text-yellow-500' : 'text-muted-foreground'}`} />
                      </button>
                    </div>
                    <p className="text-xs text-muted-foreground">{c.description || c.key}</p>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {c.register && <Badge variant="outline">register</Badge>}
                      {c.last_run && <Badge variant="outline">last: {c.last_run.status}</Badge>}
                    </div>
                  </div>
                ))}
              </div>
            </Section>
          ))}
        </div>
        <Section title="Recent runs">
          <ul className="space-y-1 text-sm">
            {(favs.data?.data?.recent ?? []).slice(0, 12).map((r: Any) => (
              <li key={`${r.key}${r.at}`} className="flex justify-between gap-2">
                <span className="truncate">{r.key}</span>
                {r.job_id && <button type="button" className="text-xs underline" onClick={() => download(r.job_id)}>file</button>}
              </li>
            ))}
          </ul>
        </Section>
      </div>
      <Modal open={!!open} onOpenChange={(o) => !o && setOpen(null)} title={open?.name ?? ''} description={open?.description} size="xl">
        {open && (
          <div className="space-y-3">
            <ReportParamsForm
              schema={open.params_schema as JsonSchema}
              submitLabel="Run as job"
              onSubmit={(p) => exec(p, false)}
              extra={
                <>
                  <select aria-label="Format" className={sel} value={fmt} onChange={(e) => setFmt(e.target.value as ReportFormat)}>
                    {(open.formats as ReportFormat[]).map((f) => <option key={f} value={f}>{f}</option>)}
                  </select>
                  {open.preview && (
                    <Button type="button" size="sm" variant="outline" onClick={() => exec({}, true)}>Preview (defaults)</Button>
                  )}
                  <Button type="button" size="sm" variant="ghost" onClick={() => navigate(`/admin/reports/schedules?key=${encodeURIComponent(open.key)}`)}>Schedule…</Button>
                </>
              }
            />
            {open.preview && (
              <ReportParamsForm schema={open.params_schema as JsonSchema} submitLabel="Preview with these parameters" onSubmit={(p) => exec(p, true)} />
            )}
            {preview && <PreviewTable preview={preview} />}
          </div>
        )}
      </Modal>
    </div>
  );
}

// ---- /admin/reports/runs ------------------------------------------------------------------------------------------------
export function ReportRunsPage() {
  useTitle('Report runs');
  const [scope, setScope] = useState<'mine' | 'all'>('mine');
  const [status, setStatus] = useState('');
  const runs = useQ(['runs', scope, status], () => repApi.runs({ scope, status: status || undefined, size: 100 }));
  const run = useRun();
  const canAll = (runs.data?.meta as Any)?.visibility?.scopes?.includes('all');
  return (
    <div className="space-y-4">
      <PageHeader title="Report runs" description="Jobs, row counts, checksums and downloads (files expire after the retention period)." />
      <div className="flex flex-wrap gap-2">
        {canAll && (
          <div role="tablist" className="inline-flex rounded-md border bg-muted p-1">
            {(['mine', 'all'] as const).map((s) => (
              <button key={s} type="button" role="tab" aria-selected={scope === s} className={`rounded px-3 py-1 text-sm ${scope === s ? 'bg-background shadow' : ''}`} onClick={() => setScope(s)}>{s === 'mine' ? 'Mine' : 'All'}</button>
            ))}
          </div>
        )}
        <select aria-label="Status" className={sel} value={status} onChange={(e) => setStatus(e.target.value)}>
          {['', 'queued', 'running', 'succeeded', 'failed', 'cancelled'].map((s) => <option key={s} value={s}>{s || 'any status'}</option>)}
        </select>
      </div>
      <Err q={runs} />
      <SimpleTable
        head={['Report', 'Format', 'Status', 'Rows', 'Checksum', 'Requested', 'When', '']}
        rows={list(runs.data).map((r) => [
          r.key,
          r.format ?? '—',
          <Badge key="s" variant="outline">{r.status}{r.purged ? ' · purged' : ''}</Badge>,
          r.rows ?? '—',
          <span key="c" className="font-mono text-xs">{r.checksum ? r.checksum.slice(0, 12) : '—'}</span>,
          r.requested_by_name ?? '—',
          r.created_at ? new Date(r.created_at).toLocaleString() : '—',
          <div key="a" className="flex gap-1">
            {r.status === 'succeeded' && !r.purged && <Button size="sm" variant="outline" onClick={() => download(r.job_id)}>Download</Button>}
            {['queued', 'running'].includes(r.status) && <Button size="sm" variant="outline" onClick={() => run.mutate(() => repApi.cancel(r.job_id))}>Cancel</Button>}
            {r.key && !r.key.startsWith('builder.') && !r.key.startsWith('statutory.') && (
              <Button size="sm" variant="ghost" onClick={() => run.mutate(() => repApi.run({ key: r.key, params: r.params, format: r.format ?? 'xlsx' }))}>Re-run</Button>
            )}
          </div>,
        ])}
      />
    </div>
  );
}

// ---- /admin/reports/registers ------------------------------------------------------------------------------------------
export function RegistersPage() {
  useTitle('Registers');
  const regs = useQ(['registers'], () => repApi.registers());
  const [pick, setPick] = useState('');
  const [fmt, setFmt] = useState<'pdf' | 'xlsx' | 'csv'>('pdf');
  const [preview, setPreview] = useState<Any>(null);
  const items = list(regs.data);
  const r = items.find((x) => x.register === pick);
  const go = async (params: Record<string, unknown>, inline: boolean) => {
    const { from, to, ...scope } = params as Any;
    try {
      if (inline) setPreview((await repApi.run({ key: r.key, params, format: 'xlsx', inline_preview: true })).data?.preview);
      else {
        const res = await repApi.runRegister({ register: pick, scope, period: { from, to }, format: fmt });
        toast.success(`Register queued (job ${String(res.data?.job_id).slice(0, 8)})`);
      }
    } catch (e) {
      fail(e);
    }
  };
  return (
    <div className="space-y-4">
      <PageHeader title="Registers" description="Print-ready ledgers with page-wise totals (admission, attendance, fee day book, results, custody, degree …)." />
      <Err q={regs} />
      <Section title="Register">
        <div className="flex flex-wrap gap-2">
          <select aria-label="Register" className={sel} value={pick} onChange={(e) => { setPick(e.target.value); setPreview(null); }}>
            <option value="">Choose a register…</option>
            {items.map((x) => <option key={x.register} value={x.register} disabled={!x.available}>{x.name}{x.available ? '' : ' (not available to you)'}</option>)}
          </select>
          <select aria-label="Format" className={sel} value={fmt} onChange={(e) => setFmt(e.target.value as Any)}>
            {['pdf', 'xlsx', 'csv'].map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        </div>
        {r && <ReportParamsForm key={r.key} schema={r.params_schema} submitLabel="Generate" onSubmit={(p) => go(p, false)} extra={<span className="text-xs text-muted-foreground">or</span>} />}
        {r && <ReportParamsForm key={`${r.key}-p`} schema={r.params_schema} submitLabel="Print preview" onSubmit={(p) => go(p, true)} />}
      </Section>
      {preview && <Section title="Print preview"><PreviewTable preview={preview} /></Section>}
    </div>
  );
}

// ---- /admin/reports/builder ----------------------------------------------------------------------------------------------
const OPS = ['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'contains', 'in', 'is_null', 'not_null', 'between'];
export function BuilderPage() {
  useTitle('Report builder');
  const { can } = usePermission();
  const models = useQ(['models'], () => repApi.models());
  const [key, setKey] = useState('');
  const m = list(models.data).find((x) => x.key === key);
  const [joins, setJoins] = useState<string[]>([]);
  const [cols, setCols] = useState<string[]>([]);
  const [groupBy, setGroupBy] = useState<string[]>([]);
  const [aggs, setAggs] = useState<{ field: string; fn: string }[]>([]);
  const [filters, setFilters] = useState<{ field: string; op: string; value: string }[]>([]);
  const [sort, setSort] = useState('');
  const [preview, setPreview] = useState<Any>(null);
  const [name, setName] = useState('');
  const [share, setShare] = useState<string[]>([]);
  const [fmt, setFmt] = useState<ReportFormat>('xlsx');
  const available: Any[] = m ? [...m.columns, ...m.joins.filter((j: Any) => joins.includes(j.key)).flatMap((j: Any) => j.columns)] : [];
  const definition = () => ({
    model_key: key,
    joins,
    columns: cols,
    group_by: groupBy,
    aggregates: aggs,
    filters: filters.filter((f) => f.field).map((f) => ({ ...f, value: f.op === 'in' || f.op === 'between' ? f.value.split(',').map((x) => x.trim()) : f.value })),
    sort: sort ? [{ field: sort, dir: 'asc' }] : [],
    name: name || undefined,
  });
  const toggle = (arr: string[], v: string, set: (x: string[]) => void) => set(arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);
  const act = async (fn: () => Promise<Any>, ok?: string) => {
    try {
      const r = await fn();
      if (ok) toast.success(ok);
      return r;
    } catch (e) {
      fail(e);
      return undefined;
    }
  };
  return (
    <div className="space-y-4">
      <PageHeader title="Report builder" description="Ad-hoc reports over whitelisted models — rows always within your scope; personal data masked without view_pii." />
      <Err q={models} />
      <Section title="Model">
        <select aria-label="Model" className={sel} value={key} onChange={(e) => { setKey(e.target.value); setJoins([]); setCols([]); setGroupBy([]); setAggs([]); setFilters([]); setPreview(null); }}>
          <option value="">Choose a model…</option>
          {list(models.data).map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}
        </select>
        {m && m.joins.length > 0 && (
          <div className="flex flex-wrap gap-3 text-sm">
            <span className="text-muted-foreground">Joins (max 3):</span>
            {m.joins.map((j: Any) => (
              <label key={j.key} className="flex items-center gap-1"><input type="checkbox" checked={joins.includes(j.key)} onChange={() => toggle(joins, j.key, setJoins)} />{j.label}</label>
            ))}
          </div>
        )}
      </Section>
      {m && (
        <>
          <Section title="Columns / group by">
            <div className="grid gap-1 text-sm sm:grid-cols-3">
              {available.map((c) => (
                <div key={c.key} className="flex items-center gap-2">
                  <label className="flex items-center gap-1"><input type="checkbox" checked={cols.includes(c.key)} onChange={() => toggle(cols, c.key, setCols)} />{c.label}{c.pii && <Badge variant="outline">PII</Badge>}</label>
                  <label className="flex items-center gap-1 text-xs text-muted-foreground"><input type="checkbox" checked={groupBy.includes(c.key)} onChange={() => toggle(groupBy, c.key, setGroupBy)} />group</label>
                </div>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span>Aggregates:</span>
              {aggs.map((a, i) => (
                <Badge key={i} variant="outline">{a.fn}({a.field}) <button type="button" onClick={() => setAggs(aggs.filter((_, j) => j !== i))}>×</button></Badge>
              ))}
              <select aria-label="Aggregate" className={sel} defaultValue="" onChange={(e) => { const [fn, field] = e.target.value.split('|'); if (fn) setAggs([...aggs, { fn, field }]); e.target.value = ''; }}>
                <option value="">add…</option>
                <option value="count|*">count rows</option>
                {available.filter((c) => c.aggregatable).flatMap((c) => ['sum', 'avg', 'min', 'max'].map((fn) => <option key={`${fn}${c.key}`} value={`${fn}|${c.key}`}>{fn} {c.label}</option>))}
              </select>
              <select aria-label="Sort" className={sel} value={sort} onChange={(e) => setSort(e.target.value)}>
                <option value="">no sort</option>
                {(groupBy.length || aggs.length ? groupBy : cols).map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
          </Section>
          <Section title="Filters" action={<Button size="sm" variant="outline" onClick={() => setFilters([...filters, { field: '', op: 'eq', value: '' }])}>Add filter</Button>}>
            {filters.map((f, i) => (
              <div key={i} className="flex flex-wrap gap-2">
                <select aria-label="Field" className={sel} value={f.field} onChange={(e) => setFilters(filters.map((x, j) => (j === i ? { ...x, field: e.target.value } : x)))}>
                  <option value="">field…</option>
                  {available.filter((c) => c.filterable).map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
                </select>
                <select aria-label="Operator" className={sel} value={f.op} onChange={(e) => setFilters(filters.map((x, j) => (j === i ? { ...x, op: e.target.value } : x)))}>
                  {OPS.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
                <Input aria-label="Value" className="w-48" value={f.value} onChange={(e) => setFilters(filters.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} />
                <Button size="sm" variant="ghost" onClick={() => setFilters(filters.filter((_, j) => j !== i))}>Remove</Button>
              </div>
            ))}
          </Section>
          <Section title="Preview / save / run">
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" onClick={async () => setPreview((await act(() => repApi.preview(definition())))?.data ?? null)}>Preview</Button>
              <select aria-label="Format" className={sel} value={fmt} onChange={(e) => setFmt(e.target.value as ReportFormat)}>
                {['xlsx', 'csv', 'pdf', 'json'].map((f) => <option key={f} value={f}>{f}</option>)}
              </select>
              <Button size="sm" variant="outline" onClick={() => act(() => repApi.builderRun(definition(), fmt), 'Run queued — see the jobs tray')}>Run as job</Button>
              <Input aria-label="Name" placeholder="Name to save…" className="w-56" value={name} onChange={(e) => setName(e.target.value)} />
              {can('reports', 'manage') && (
                <select aria-label="Share with role" className={sel} value="" onChange={(e) => e.target.value && setShare([...new Set([...share, e.target.value])])}>
                  <option value="">share with role…</option>
                  {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              )}
              {share.map((s) => <Badge key={s} variant="outline">{s} <button type="button" onClick={() => setShare(share.filter((x) => x !== s))}>×</button></Badge>)}
              <Button size="sm" variant="outline" disabled={!name} onClick={() => act(() => repApi.save({ name, definition: definition(), share_with_roles: share }), 'Saved')}>Save</Button>
            </div>
            {preview && <PreviewTable preview={preview} />}
          </Section>
        </>
      )}
    </div>
  );
}

// ---- /admin/reports/saved ------------------------------------------------------------------------------------------------
export function SavedReportsPage() {
  useTitle('Saved reports');
  const { can } = usePermission();
  const saved = useQ(['saved'], () => repApi.saved());
  const run = useRun();
  const [sharing, setSharing] = useState<Any>(null);
  const [roles, setRoles] = useState('');
  return (
    <div className="space-y-4">
      <PageHeader title="Saved reports" description="Your builder reports and those shared with your roles." />
      <Err q={saved} />
      <SimpleTable
        head={['Name', 'Model', 'Owner', 'Shared with', '']}
        rows={list(saved.data).map((s) => [
          s.name,
          s.definition?.model_key,
          s.mine ? 'me' : s.owner_name ?? '—',
          (s.shared ?? []).join(', ') || 'private',
          <div key="a" className="flex gap-1">
            <Button size="sm" variant="outline" onClick={() => run.mutate(() => repApi.runSaved(s.id, 'xlsx'))}>Run xlsx</Button>
            {can('reports', 'manage') && <Button size="sm" variant="ghost" onClick={() => { setSharing(s); setRoles((s.shared ?? []).join(', ')); }}>Share</Button>}
            {(s.mine || can('reports', 'manage')) && <Button size="sm" variant="ghost" onClick={() => run.mutate(() => repApi.deleteSaved(s.id))}>Delete</Button>}
          </div>,
        ])}
      />
      <Modal open={!!sharing} onOpenChange={(o) => !o && setSharing(null)} title={`Share “${sharing?.name ?? ''}”`} description="Comma-separated role slugs (reports:manage)." footer={<Button onClick={() => { run.mutate(() => repApi.shareSaved(sharing.id, roles.split(',').map((r) => r.trim()).filter(Boolean))); setSharing(null); }}>Share</Button>}>
        <Input aria-label="Roles" value={roles} onChange={(e) => setRoles(e.target.value)} />
      </Modal>
    </div>
  );
}

// ---- /admin/reports/statutory --------------------------------------------------------------------------------------------
const STEPS = ['generated', 'in_review', 'signed_off', 'submitted'];
export function StatutoryPage() {
  useTitle('Statutory reports');
  const codes = useQ(['statutory'], () => repApi.statutory());
  const [code, setCode] = useState<Any>(null);
  const [period, setPeriod] = useState('');
  const [discipline, setDiscipline] = useState('');
  const detail = useQ(['statutory', code?.code, period, discipline], () => repApi.statutoryOne(code.code, period, discipline || undefined), !!code && period.length >= 4);
  const diff = useQ(['statutory-diff', code?.code, period], () => repApi.diff(code.code, period), !!detail.data);
  const run = useRun();
  const d: Any = detail.data?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="Statutory reports" description="AISHE, NIRF, AICTE, UGC, NSP, fee-regulatory, cells, anti-ragging, RTI, PhD, placement, affiliated colleges, GST — aggregates only, multi-role sign-off." />
      <Err q={codes} />
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {list(codes.data).map((c) => (
          <button key={c.code} type="button" className={`rounded-md border p-3 text-left text-sm ${code?.code === c.code ? 'border-primary' : ''}`} onClick={() => { setCode(c); setPeriod(c.last_period ?? ''); }}>
            <div className="font-medium">{c.name}</div>
            <div className="text-xs text-muted-foreground">due {c.due_on} · {c.period_type.replace('_', ' ')}</div>
            <div className="mt-1 flex gap-1"><Badge variant="outline">{c.status ?? 'not generated'}</Badge>{c.last_period && <Badge variant="outline">{c.last_period}</Badge>}</div>
          </button>
        ))}
      </div>
      {code && (
        <Section title={code.name} action={<span className="text-xs text-muted-foreground">sign-off: {code.signoff_roles.join(', ')}</span>}>
          <div className="flex flex-wrap gap-2">
            <Input aria-label="Period" placeholder="2025-26" className="w-32" value={period} onChange={(e) => setPeriod(e.target.value)} />
            {code.disciplines?.length > 0 && (
              <select aria-label="Discipline" className={sel} value={discipline} onChange={(e) => setDiscipline(e.target.value)}>
                <option value="">overall</option>
                {code.disciplines.map((x: string) => <option key={x} value={x}>{x}</option>)}
              </select>
            )}
            <Button size="sm" onClick={() => run.mutate(() => repApi.generate(code.code, { period_label: period, discipline: discipline || undefined }))}>{d ? 'Regenerate' : 'Generate'}</Button>
            {d && <Button size="sm" variant="outline" onClick={() => run.mutate(() => repApi.pack(code.code, period))}>Export pack</Button>}
          </div>
          {d && (
            <div className="space-y-3">
              <ol className="flex flex-wrap gap-2 text-xs">
                {STEPS.map((s) => <li key={s} className={`rounded-full border px-2 py-0.5 ${STEPS.indexOf(s) <= STEPS.indexOf(d.status) ? 'bg-primary text-primary-foreground' : ''}`}>{s.replace('_', ' ')}</li>)}
              </ol>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="outline" onClick={() => run.mutate(() => repApi.review(code.code, period, { action: 'request_review' }, discipline || undefined))}>Request review</Button>
                {code.signoff_roles.map((r: string) => (
                  <Button key={r} size="sm" variant="outline" disabled={d.signoffs.some((s: Any) => s.role === r)} onClick={() => run.mutate(() => repApi.review(code.code, period, { action: 'sign_off', role: r }, discipline || undefined))}>Sign off as {r}</Button>
                ))}
                <Button size="sm" variant="ghost" onClick={() => { const remarks = window.prompt('Reason to reopen'); if (remarks) run.mutate(() => repApi.review(code.code, period, { action: 'reopen', remarks }, discipline || undefined)); }}>Reopen</Button>
              </div>
              <SimpleTable head={['Section', 'Check', 'Status', 'Detail']} rows={(d.validation ?? []).map((v: Any) => [v.section, v.check, <Badge key="s" variant="outline">{v.status}</Badge>, v.detail ?? ''])} empty="No validation results." />
              <SimpleTable head={['Format', 'Checksum', 'File']} rows={(d.files ?? []).map((f: Any) => [f.format, <span key="c" className="font-mono text-xs">{String(f.checksum ?? '').slice(0, 12)}</span>, f.revoked ? 'revoked' : <a key="l" className="underline" href={f.url} target="_blank" rel="noreferrer">open</a>])} />
              <SimpleTable head={['Signed role', 'By', 'At']} rows={(d.signoffs ?? []).map((s: Any) => [s.role, s.user_name ?? '—', s.at ? new Date(s.at).toLocaleString() : ''])} empty="No sign-offs yet." />
              {d.compliance_submission_id && <p className="text-xs">Phase 32 submission: <a className="underline" href={`/iqac/submissions?id=${d.compliance_submission_id}`}>{d.compliance_submission_id.slice(0, 8)}</a></p>}
              <SimpleTable
                head={['Section', 'Rows (prev → now)', 'Totals Δ']}
                rows={(diff.data?.data?.sections ?? []).map((s: Any) => [s.title ?? s.section, `${s.rows_previous ?? '—'} → ${s.rows_current ?? '—'}`, Object.entries(s.totals ?? {}).map(([k, v]: Any) => `${k} ${v.delta ?? '—'}`).join(' · ')])}
                empty="No previous period to compare."
              />
            </div>
          )}
          <Err q={detail} />
        </Section>
      )}
    </div>
  );
}

// ---- /admin/reports/schedules --------------------------------------------------------------------------------------------
export function SchedulesPage() {
  useTitle('Report schedules');
  const [search] = useSearchParams();
  const items = useQ(['schedules'], () => repApi.schedules());
  const cat = useQ(['catalogue', ''], () => repApi.catalogue());
  const run = useRun();
  const [form, setForm] = useState<Any>(search.get('key') ? { key: search.get('key'), cadence: 'weekly', at: '07:00', format: 'xlsx', roles: '', emails: '', channels: ['email', 'in_app'] } : null);
  const [hist, setHist] = useState<Any>(null);
  const history = useQ(['history', hist?.id], () => repApi.history(hist.id), !!hist);
  const spec = list(cat.data).find((c) => c.key === form?.key);
  const pii = !!spec?.pii;
  const save = () =>
    run.mutate(async () => {
      await repApi.createSchedule({
        name: form.name || undefined,
        key: form.key,
        cadence: form.cadence,
        at: form.at,
        weekday: form.cadence === 'weekly' ? Number(form.weekday ?? 0) : undefined,
        day_of_month: form.cadence === 'monthly' ? Number(form.day_of_month ?? 1) : undefined,
        cron: form.cadence === 'cron' ? form.cron : undefined,
        format: form.format,
        recipients: { roles: form.roles.split(',').map((x: string) => x.trim()).filter(Boolean), emails: form.emails.split(',').map((x: string) => x.trim()).filter(Boolean) },
        channels: form.channels,
      });
      setForm(null);
    });
  return (
    <div className="space-y-4">
      <PageHeader title="Report schedules" description="Each recipient receives the report as themselves (their scope). External emails only for reports without personal data." actions={<Button size="sm" onClick={() => setForm({ cadence: 'weekly', at: '07:00', format: 'xlsx', roles: '', emails: '', channels: ['email', 'in_app'] })}>New schedule</Button>} />
      <Err q={items} />
      <SimpleTable
        head={['Name', 'Report', 'Cadence', 'Next run', 'Recipients', 'Status', '']}
        rows={list(items.data).map((s) => [
          s.name ?? '—',
          s.key ?? `saved ${s.saved_report_id}`,
          `${s.cadence} ${s.at}`,
          s.next_run_at ? new Date(s.next_run_at).toLocaleString() : '—',
          [...(s.recipients?.roles ?? []), ...(s.recipients?.emails ?? [])].join(', ') || 'owner',
          <Badge key="s" variant="outline">{s.is_active ? 'active' : s.paused_reason ?? 'paused'}</Badge>,
          <div key="a" className="flex gap-1">
            <Button size="sm" variant="outline" onClick={() => run.mutate(() => repApi.runNow(s.id))}>Run now</Button>
            <Button size="sm" variant="ghost" onClick={() => run.mutate(() => (s.is_active ? repApi.pause(s.id) : repApi.resume(s.id)))}>{s.is_active ? 'Pause' : 'Resume'}</Button>
            <Button size="sm" variant="ghost" onClick={() => setHist(s)}>History</Button>
            <Button size="sm" variant="ghost" onClick={() => run.mutate(() => repApi.deleteSchedule(s.id))}>Delete</Button>
          </div>,
        ])}
      />
      <Modal open={!!form} onOpenChange={(o) => !o && setForm(null)} title="Schedule a report" size="lg" footer={<Button onClick={save} disabled={!form?.key}>Save</Button>}>
        {form && (
          <div className="grid gap-2 sm:grid-cols-2">
            <Input aria-label="Name" placeholder="Name" value={form.name ?? ''} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <select aria-label="Report" className={sel} value={form.key ?? ''} onChange={(e) => setForm({ ...form, key: e.target.value })}>
              <option value="">report…</option>
              {list(cat.data).map((c) => <option key={c.key} value={c.key}>{c.name}</option>)}
            </select>
            <select aria-label="Cadence" className={sel} value={form.cadence} onChange={(e) => setForm({ ...form, cadence: e.target.value })}>
              {['daily', 'weekly', 'monthly', 'termly', 'cron'].map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <Input aria-label="At" type="time" value={form.at} onChange={(e) => setForm({ ...form, at: e.target.value })} />
            {form.cadence === 'weekly' && <select aria-label="Weekday" className={sel} value={form.weekday ?? 0} onChange={(e) => setForm({ ...form, weekday: e.target.value })}>{['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((d, i) => <option key={d} value={i}>{d}</option>)}</select>}
            {form.cadence === 'monthly' && <Input aria-label="Day of month" type="number" min={1} max={28} value={form.day_of_month ?? 1} onChange={(e) => setForm({ ...form, day_of_month: e.target.value })} />}
            {form.cadence === 'cron' && <Input aria-label="Cron" placeholder="0 7 * * 1" value={form.cron ?? ''} onChange={(e) => setForm({ ...form, cron: e.target.value })} />}
            <select aria-label="Format" className={sel} value={form.format} onChange={(e) => setForm({ ...form, format: e.target.value })}>{['xlsx', 'csv', 'pdf'].map((f) => <option key={f} value={f}>{f}</option>)}</select>
            <Input aria-label="Recipient roles" placeholder="roles: hod, accountant" value={form.roles} onChange={(e) => setForm({ ...form, roles: e.target.value })} />
            <Input aria-label="Recipient emails" placeholder={pii ? 'emails disabled — report has personal data' : 'emails (non-PII reports)'} disabled={pii} value={form.emails} onChange={(e) => setForm({ ...form, emails: e.target.value })} />
            <div className="flex gap-3 text-sm sm:col-span-2">
              {['email', 'whatsapp', 'in_app'].map((ch) => (
                <label key={ch} className="flex items-center gap-1"><input type="checkbox" checked={form.channels.includes(ch)} onChange={() => setForm({ ...form, channels: form.channels.includes(ch) ? form.channels.filter((x: string) => x !== ch) : [...form.channels, ch] })} />{ch}</label>
              ))}
            </div>
          </div>
        )}
      </Modal>
      <Modal open={!!hist} onOpenChange={(o) => !o && setHist(null)} title={`History — ${hist?.name ?? ''}`} size="lg">
        <SimpleTable head={['Run at', 'Status', 'Delivered to', 'File']} rows={list(history.data).map((h) => [h.run_at ? new Date(h.run_at).toLocaleString() : '—', h.status, (h.delivered_to ?? []).length, h.result_url ? <a key="l" className="underline" href={h.result_url} target="_blank" rel="noreferrer">open</a> : h.error ?? '—'])} />
      </Modal>
    </div>
  );
}

// ---- /admin/reports/access-log -------------------------------------------------------------------------------------------
export function AccessLogPage() {
  useTitle('Report access log');
  const [key, setKey] = useState('');
  const log = useQ(['access', key], () => repApi.accessLog({ key: key || undefined }));
  return (
    <div className="space-y-4">
      <PageHeader title="Report access log" description="Who ran, previewed or downloaded which report (audit_logs, module reports)." />
      <Input aria-label="Report key" placeholder="report key…" className="w-64" value={key} onChange={(e) => setKey(e.target.value)} />
      <Err q={log} />
      <SimpleTable
        head={['When', 'User', 'Action', 'Report', 'Parameters']}
        rows={list(log.data).map((r) => [new Date(r.at).toLocaleString(), r.user_name ?? '—', r.action, r.key ?? '—', <span key="p" className="font-mono text-xs">{JSON.stringify(r.params)}</span>])}
      />
    </div>
  );
}

export const FORMAT_OPTIONS = FORMATS;
