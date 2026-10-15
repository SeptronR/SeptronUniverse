import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { ColumnDef } from '@tanstack/react-table';
import { Check, Play, Plus, RotateCcw, Upload, X } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { DataTable } from '@/components/shared/DataTable';
import { FormField } from '@/components/shared/FormField';
import { ScopeTabs } from '@/components/shared/ScopeTabs';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Input, Select, Textarea } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { usePermission } from '@/hooks/usePermission';
import { usePrograms } from '@/features/academics/hooks';
import { SimpleTable } from '@/features/hr/components/shared';
import { admissionsApi } from '../api';
import {
  useAdmissionsMutation,
  useAllotments,
  useApplicants,
  useCyclePrograms,
  useMeritList,
  useMeritLists,
  useOffers,
  useRounds,
  useSeatStatus,
  useVerificationQueue,
} from '../hooks';
import {
  APPLICANT_STATUSES,
  ROUND_NEXT,
  label,
  type AllotmentSummary,
  type Applicant,
  type ApplicantListItem,
  type ImportResult,
  type SeatStatus,
} from '../types';

const toast$ = async (p: Promise<unknown>, ok: string) => {
  try {
    await p;
    toast.success(ok);
    return true;
  } catch (e) {
    toast.error(getApiError(e));
    return false;
  }
};

// ---- programmes & intake ---------------------------------------------------------------------------------------------
interface ProgRow {
  program_id: string;
  intake: number;
  lateral_intake: number;
  entrance_source: string;
  min_pct: string;
}

export function ProgramsTab({ cycleId, editable }: { cycleId: string; editable: boolean }) {
  const q = useCyclePrograms(cycleId);
  const programs = usePrograms({ page_size: 200 });
  const [rows, setRows] = useState<ProgRow[]>([]);
  const save = useAdmissionsMutation((r: ProgRow[]) =>
    admissionsApi.savePrograms(
      cycleId,
      r.map((x) => ({
        program_id: x.program_id,
        intake: Number(x.intake),
        lateral_intake: Number(x.lateral_intake),
        entrance_source: x.entrance_source,
        eligibility_rules: x.min_pct ? { min_qualifying_pct: Number(x.min_pct) } : null,
        merit_formula: [{ field: 'entrance_score', weight: 60 }, { field: 'qualifying_pct', weight: 40 }],
        tie_break: ['entrance_score', 'dob_asc', 'submitted_at'],
      })),
    ),
  );
  useEffect(() => {
    setRows(
      (q.data?.data ?? []).map((p) => ({
        program_id: p.program_id,
        intake: p.intake,
        lateral_intake: p.lateral_intake,
        entrance_source: p.entrance_source,
        min_pct: String((p.eligibility_rules as { min_qualifying_pct?: number } | null)?.min_qualifying_pct ?? ''),
      })),
    );
  }, [q.data]);
  const patch = (i: number, p: Partial<ProgRow>) => setRows((r) => r.map((x, j) => (j === i ? { ...x, ...p } : x)));
  const sources = ['jee', 'neet', 'cuet', 'state_cet', 'gate', 'cat', 'institution_test', 'merit_only'];
  return (
    <Card>
      <CardHeader><CardTitle className="text-base">Programmes &amp; intake</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <SimpleTable
          head={['Programme', 'Intake', 'Lateral', 'Entrance', 'Min. qualifying %', '']}
          rows={rows.map((r, i) => [
            <Select key="p" aria-label="Programme" disabled={!editable} value={r.program_id} onChange={(e) => patch(i, { program_id: e.target.value })} options={(programs.data?.data ?? []).map((p) => ({ value: p.id, label: `${p.code} — ${p.name}` }))} />,
            <Input key="i" type="number" aria-label="Intake" className="w-20" disabled={!editable} value={r.intake} onChange={(e) => patch(i, { intake: Number(e.target.value) })} />,
            <Input key="l" type="number" aria-label="Lateral intake" className="w-20" disabled={!editable} value={r.lateral_intake} onChange={(e) => patch(i, { lateral_intake: Number(e.target.value) })} />,
            <Select key="s" aria-label="Entrance" disabled={!editable} value={r.entrance_source} onChange={(e) => patch(i, { entrance_source: e.target.value })} options={sources.map((s) => ({ value: s, label: label(s) }))} />,
            <Input key="m" aria-label="Min %" className="w-20" disabled={!editable} value={r.min_pct} onChange={(e) => patch(i, { min_pct: e.target.value })} />,
            editable ? <Button key="x" size="sm" variant="ghost" aria-label="Remove" onClick={() => setRows((x) => x.filter((_, j) => j !== i))}><X className="h-4 w-4" /></Button> : null,
          ])}
          empty="No programmes yet."
        />
        {editable && (
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => setRows((r) => [...r, { program_id: programs.data?.data[0]?.id ?? '', intake: 60, lateral_intake: 0, entrance_source: 'merit_only', min_pct: '' }])}>
              <Plus className="h-4 w-4" /> Add programme
            </Button>
            <Button disabled={save.isPending || !rows.length} onClick={() => toast$(save.mutateAsync(rows), 'Programmes saved')}>Save</Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ---- seat matrix ---------------------------------------------------------------------------------------------------------
export function SeatMatrixTab({ cycleId, editable }: { cycleId: string; editable: boolean }) {
  const q = useSeatStatus(cycleId);
  const progs = useCyclePrograms(cycleId);
  const [grid, setGrid] = useState<Record<string, number>>({});
  const save = useAdmissionsMutation((rows: { program_id: string; quota: string; category: string; seats: number }[]) =>
    admissionsApi.saveSeatMatrix(cycleId, rows),
  );
  const data = q.data?.data;
  useEffect(() => {
    const g: Record<string, number> = {};
    (data?.rows ?? []).forEach((r) => (g[`${r.program_id}|${r.quota}|${r.category}`] = r.seats));
    setGrid(g);
  }, [data]);
  const quotas = (data?.quotas ?? []).filter((x) => ['STATE', 'ALL_INDIA', 'MANAGEMENT', 'NRI', 'LATERAL', 'PWD'].includes(x));
  const cats = data?.categories ?? [];
  const onSave = () =>
    toast$(
      save.mutateAsync(
        Object.entries(grid)
          .filter(([, v]) => Number(v) > 0)
          .map(([k, v]) => {
            const [program_id, quota, category] = k.split('|');
            return { program_id, quota, category, seats: Number(v) };
          }),
      ),
      'Seat matrix saved',
    );
  return (
    <div className="space-y-4">
      {(progs.data?.data ?? []).map((p) => {
        const total = Object.entries(grid).filter(([k]) => k.startsWith(`${p.program_id}|`)).reduce((s, [, v]) => s + Number(v || 0), 0);
        const target = p.intake + p.lateral_intake;
        return (
          <Card key={p.id}>
            <CardHeader>
              <CardTitle className="flex items-center justify-between text-base">
                {p.program_code} — {p.program_name}
                <Badge variant={total === target ? 'success' : 'warning'}>Σ {total} / intake {target}</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              <table className="text-sm">
                <thead>
                  <tr><th className="px-2 py-1 text-left text-xs text-muted-foreground">Quota \ category</th>{cats.map((c) => <th key={c} className="px-2 py-1 text-xs">{c}</th>)}</tr>
                </thead>
                <tbody>
                  {quotas.map((qu) => (
                    <tr key={qu}>
                      <td className="px-2 py-1 text-xs font-medium">{qu}</td>
                      {cats.map((c) => {
                        const k = `${p.program_id}|${qu}|${c}`;
                        return (
                          <td key={c} className="px-1 py-1">
                            <Input type="number" min={0} aria-label={`${qu} ${c}`} className="h-8 w-16" disabled={!editable} value={grid[k] ?? ''} onChange={(e) => setGrid((g) => ({ ...g, [k]: Number(e.target.value) }))} />
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        );
      })}
      {editable && <Button disabled={save.isPending} onClick={onSave}>Save seat matrix</Button>}
    </div>
  );
}

/** Filled / vacant heatmap per programme × quota × category. */
export function SeatHeatmap({ data }: { data: SeatStatus | undefined }) {
  if (!data) return <p className="text-sm text-muted-foreground">Loading…</p>;
  const byProg = new Map<string, typeof data.rows>();
  data.rows.forEach((r) => byProg.set(r.program_code ?? r.program_id, [...(byProg.get(r.program_code ?? r.program_id) ?? []), r]));
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {[...byProg.entries()].map(([code, rows]) => (
        <Card key={code}>
          <CardHeader><CardTitle className="text-base">{code}</CardTitle></CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {rows.map((r) => {
              const pct = r.seats ? r.filled / r.seats : 0;
              const tone = pct >= 1 ? 'bg-emerald-500/80 text-white' : pct > 0.5 ? 'bg-emerald-300/70' : pct > 0 ? 'bg-amber-200/80' : 'bg-muted';
              return (
                <div key={r.id} className={`min-w-24 rounded-md px-2 py-1.5 text-xs ${tone}`} title={`${r.filled} filled / ${r.seats} seats`}>
                  <div className="font-medium">{r.quota} · {r.category}</div>
                  <div>{r.filled}/{r.seats} · {r.vacant} vacant</div>
                </div>
              );
            })}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

// ---- applicants table --------------------------------------------------------------------------------------------------------
export function ApplicantsTable({ cycleId }: { cycleId?: string }) {
  const navigate = useNavigate();
  const { can } = usePermission();
  const [params, setParams] = useState<Record<string, string | number | boolean | undefined | null>>({ page: 1, page_size: 25 });
  const list = useApplicants({ ...params, cycle_id: cycleId });
  const set = (patch: Record<string, string | boolean | undefined>) => setParams((p) => ({ ...p, ...patch, page: 1 }));
  const columns = useMemo<ColumnDef<ApplicantListItem, unknown>[]>(
    () => [
      { accessorKey: 'application_number', header: 'Application no', cell: ({ getValue }) => <span className="font-mono text-xs">{String(getValue())}</span> },
      { accessorKey: 'first_name', header: 'Name', cell: ({ row }) => row.original.name },
      { accessorKey: 'category', header: 'Category', cell: ({ row }) => <span>{row.original.category ?? '—'} {row.original.is_pwd && <Badge variant="outline">PwD</Badge>}</span> },
      { accessorKey: 'quota_claimed', header: 'Quota' },
      { id: 'pref', header: '1st preference', enableSorting: false, cell: ({ row }) => row.original.first_preference ?? '—' },
      { accessorKey: 'merit_score', header: 'Merit score' },
      { accessorKey: 'phone', header: 'Phone', enableSorting: false },
      { accessorKey: 'entry_type', header: 'Entry', cell: ({ getValue }) => label(String(getValue())) },
      { accessorKey: 'status', header: 'Status', cell: ({ getValue }) => <StatusBadge status={String(getValue())} /> },
    ],
    [],
  );
  const vis = list.data?.meta.visibility;
  const exportJob = async () => {
    try {
      const r = await admissionsApi.exportXlsx({ cycle_id: cycleId, status: params.status as string | undefined });
      toast.success(`Export queued (job ${r.data.job_id.slice(0, 8)}) — the file arrives in the jobs tray`);
    } catch (e) {
      toast.error(getApiError(e));
    }
  };
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <ScopeTabs visibility={vis} value={params.scope as string | undefined} onChange={(scope) => set({ scope })} labels={{ own: 'Mine', all: 'All' }} />
        <Input className="w-56" placeholder="Search no. / name / phone…" value={(params.search as string) ?? ''} onChange={(e) => set({ search: e.target.value || undefined })} />
        <Select className="w-44" aria-label="Status" placeholder="All statuses" options={APPLICANT_STATUSES.map((s) => ({ value: s, label: label(s) }))} value={(params.status as string) ?? ''} onChange={(e) => set({ status: e.target.value || undefined })} />
        <Select className="w-32" aria-label="Entry" placeholder="Any entry" options={['regular', 'lateral'].map((s) => ({ value: s, label: label(s) }))} value={(params.entry_type as string) ?? ''} onChange={(e) => set({ entry_type: e.target.value || undefined })} />
        <Input className="w-28" placeholder="Category" value={(params.category as string) ?? ''} onChange={(e) => set({ category: e.target.value || undefined })} />
        {vis && !vis.pii && <span className="text-xs text-muted-foreground">Phone / e-mail masked for your role.</span>}
      </div>
      <DataTable
        columns={columns}
        data={list.data?.data ?? []}
        isLoading={list.isLoading}
        pagination={list.data?.meta.pagination}
        onPageChange={(page) => setParams((p) => ({ ...p, page }))}
        onPageSizeChange={(page_size) => setParams((p) => ({ ...p, page_size, page: 1 }))}
        sort={params.sort as string | undefined}
        onSortChange={(sort) => setParams((p) => ({ ...p, sort }))}
        onExport={can('admissions', 'export') ? exportJob : undefined}
        onRowClick={(r) => navigate(`/admin/admissions/applicants/${r.id}`)}
        rowKey={(r) => r.id}
      />
    </div>
  );
}

// ---- verification queue ----------------------------------------------------------------------------------------------------------
export function DocumentReview({ applicant, canVerify }: { applicant: Applicant; canVerify: boolean }) {
  const [remarks, setRemarks] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<string | null>(applicant.documents[0]?.file_url ?? null);
  const act = useAdmissionsMutation((v: { doc: string; status: string }) =>
    admissionsApi.verifyDocument(applicant.id, v.doc, { status: v.status, remarks: remarks[v.doc] || undefined }),
  );
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <div className="space-y-2">
        {applicant.documents.map((d) => (
          <div key={d.doc_type} className="rounded-md border p-2">
            <div className="flex items-center justify-between gap-2">
              <button type="button" className="text-sm font-medium underline-offset-2 hover:underline" onClick={() => setPreview(d.file_url)}>{label(d.doc_type)}</button>
              <StatusBadge status={d.status} />
            </div>
            {d.remarks && <p className="text-xs text-muted-foreground">{d.remarks}</p>}
            {canVerify && d.status !== 'verified' && (
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Input className="h-8 flex-1" placeholder="Remarks" value={remarks[d.doc_type] ?? ''} onChange={(e) => setRemarks((r) => ({ ...r, [d.doc_type]: e.target.value }))} />
                <Button size="sm" onClick={() => toast$(act.mutateAsync({ doc: d.doc_type, status: 'verified' }), 'Verified')}><Check className="h-4 w-4" /> Verify</Button>
                <Button size="sm" variant="outline" onClick={() => toast$(act.mutateAsync({ doc: d.doc_type, status: 'rejected' }), 'Rejected')}><X className="h-4 w-4" /> Reject</Button>
              </div>
            )}
          </div>
        ))}
        {applicant.missing_documents.length > 0 && <p className="text-xs text-amber-600">Missing: {applicant.missing_documents.map(label).join(', ')}</p>}
      </div>
      <div className="min-h-64 rounded-md border bg-muted/30">
        {preview && !preview.startsWith('demo://') ? (
          <iframe title="Document preview" src={preview} className="h-96 w-full rounded-md" />
        ) : (
          <p className="p-6 text-sm text-muted-foreground">{preview ? 'Demo document (no file stored).' : 'Select a document to preview.'}</p>
        )}
      </div>
    </div>
  );
}

export function VerificationQueue({ cycleId }: { cycleId?: string }) {
  const { can } = usePermission();
  const q = useVerificationQueue({ cycle_id: cycleId, page_size: 20 });
  const [open, setOpen] = useState<string | null>(null);
  const rows = q.data?.data ?? [];
  const current = rows.find((a) => a.id === open) ?? rows[0];
  return (
    <div className="grid gap-3 lg:grid-cols-[18rem_1fr]">
      <div className="space-y-1">
        {rows.map((a) => (
          <button key={a.id} type="button" onClick={() => setOpen(a.id)} className={`w-full rounded-md border px-3 py-2 text-left text-sm ${current?.id === a.id ? 'border-primary bg-accent' : ''}`}>
            <div className="font-mono text-xs">{a.application_number}</div>
            <div className="flex items-center justify-between">{a.name} <StatusBadge status={a.status} /></div>
          </button>
        ))}
        {!rows.length && <p className="text-sm text-muted-foreground">Nothing waiting for verification.</p>}
      </div>
      {current && <DocumentReview key={current.id} applicant={current} canVerify={can('admissions', 'verify')} />}
    </div>
  );
}

// ---- merit lists ---------------------------------------------------------------------------------------------------------------
export function MeritTab({ cycleId }: { cycleId: string }) {
  const { can } = usePermission();
  const lists = useMeritLists(cycleId);
  const progs = useCyclePrograms(cycleId);
  const [wizard, setWizard] = useState(false);
  const [form, setForm] = useState({ name: '', program_id: '', category: '' });
  const [view, setView] = useState<string | undefined>();
  const detail = useMeritList(view);
  const gen = useAdmissionsMutation(() =>
    admissionsApi.generateMerit(cycleId, { name: form.name, program_ids: form.program_id ? [form.program_id] : undefined, category: form.category || undefined }),
  );
  const pub = useAdmissionsMutation((id: string) => admissionsApi.publishMerit(id));
  return (
    <div className="space-y-3">
      {can('admissions', 'merit') && (
        <Button onClick={() => setWizard(true)}><Plus className="h-4 w-4" /> Generate merit list</Button>
      )}
      <SimpleTable
        head={['Name', 'Scope', 'Entries', 'Status', 'Generated', '']}
        rows={(lists.data?.data ?? []).map((m) => [
          <button key="n" type="button" className="text-left font-medium hover:underline" onClick={() => setView(m.id)}>{m.name}</button>,
          [m.program_id ? 'programme' : 'all programmes', m.category].filter(Boolean).join(' · '),
          m.entries_count,
          <StatusBadge key="s" status={m.generated_at ? m.status : 'generating'} />,
          m.generated_at ? new Date(m.generated_at).toLocaleString() : '…',
          m.status === 'draft' && m.generated_at && can('admissions', 'merit') ? (
            <Button key="p" size="sm" onClick={() => toast$(pub.mutateAsync(m.id), 'Published — applicants notified')}>Publish</Button>
          ) : null,
        ])}
        empty="No merit lists yet."
      />
      {detail.data && (
        <Card>
          <CardHeader><CardTitle className="text-base">{detail.data.data.name}</CardTitle></CardHeader>
          <CardContent>
            <SimpleTable
              head={['Rank', 'Cat. rank', 'Application', 'Name', 'Category', 'Score']}
              rows={detail.data.data.entries.slice(0, 200).map((e) => [e.rank, e.category_rank ?? '—', e.application_number, e.name, `${e.category ?? '—'}${e.is_pwd ? ' · PwD' : ''}`, e.score ?? '—'])}
            />
          </CardContent>
        </Card>
      )}
      <Modal
        open={wizard}
        onOpenChange={setWizard}
        title="Generate merit list"
        description="Ranks verified applicants with the programme's formula and tie-breaks (runs as a background job)."
        footer={<Button disabled={form.name.length < 3 || gen.isPending} onClick={async () => { if (await toast$(gen.mutateAsync(undefined), 'Merit list queued — it appears when the job finishes')) setWizard(false); }}>Generate</Button>}
      >
        <div className="space-y-3">
          <FormField label="Name" required value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
          <Select aria-label="Programme" placeholder="All programmes" options={(progs.data?.data ?? []).map((p) => ({ value: p.program_id, label: p.program_code ?? p.program_id }))} value={form.program_id} onChange={(e) => setForm((f) => ({ ...f, program_id: e.target.value }))} />
          <Input placeholder="Category (optional, e.g. SC)" value={form.category} onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))} />
        </div>
      </Modal>
    </div>
  );
}

// ---- counselling rounds --------------------------------------------------------------------------------------------------------
function SummaryView({ s }: { s: AllotmentSummary }) {
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2 text-sm">
        <Badge variant="outline">{s.dry_run ? 'Preview' : 'Result'}</Badge>
        <span>Allotted {s.allotted}</span>· <span>Upgraded {s.upgraded}</span>· <span>Unallotted {s.unallotted}</span>
      </div>
      <SimpleTable head={['Programme', 'Quota', 'Category', 'Seats', 'Filled', 'This round']} rows={s.rows.map((r) => [r.program_code, r.quota, r.category, r.seats, r.filled, r.allotted_now])} />
      {s.conversions.length > 0 && (
        <p className="text-sm">De-reservation: {s.conversions.map((c) => `${c.program_code} ${c.quota} ${c.from_category}→${c.to_category} ×${c.seats}`).join('; ')}</p>
      )}
    </div>
  );
}

export function RoundsTab({ cycleId }: { cycleId: string }) {
  const { can } = usePermission();
  const rounds = useRounds(cycleId);
  const [sel, setSel] = useState<string | undefined>();
  const [preview, setPreview] = useState<AllotmentSummary | null>(null);
  const [form, setForm] = useState({ open: false, number: '1', deadline: '', final: false });
  const allots = useAllotments(sel);
  const create = useAdmissionsMutation(() =>
    admissionsApi.createRound(cycleId, { round_number: Number(form.number), is_final: form.final, reporting_deadline: form.deadline ? new Date(form.deadline).toISOString() : undefined }),
  );
  const status = useAdmissionsMutation((v: { id: string; s: string }) => admissionsApi.roundStatus(v.id, v.s));
  const run = useAdmissionsMutation((v: { id: string; dry: boolean }) => admissionsApi.runAllotment(v.id, v.dry));
  const allot = can('admissions', 'allot');
  const dry = async (id: string) => {
    try {
      const r = await run.mutateAsync({ id, dry: true });
      setPreview(r.data);
      setSel(id);
    } catch (e) {
      toast.error(getApiError(e));
    }
  };
  return (
    <div className="space-y-3">
      {allot && <Button onClick={() => setForm((f) => ({ ...f, open: true, number: String((rounds.data?.data.length ?? 0) + 1) }))}><Plus className="h-4 w-4" /> New round</Button>}
      <SimpleTable
        head={['Round', 'Status', 'Allotments', 'Reporting deadline', '']}
        rows={(rounds.data?.data ?? []).map((r) => [
          <button key="n" type="button" className="font-medium hover:underline" onClick={() => setSel(r.id)}>{r.name ?? `Round ${r.round_number}`} {r.is_final && <Badge variant="outline">final</Badge>}</button>,
          <StatusBadge key="s" status={r.status} />,
          r.allotments_count,
          r.reporting_deadline ? new Date(r.reporting_deadline).toLocaleString() : '—',
          allot ? (
            <div key="a" className="flex flex-wrap gap-1">
              {r.status !== 'closed' && <Button size="sm" variant="outline" onClick={() => dry(r.id)}><Play className="h-3.5 w-3.5" /> Dry run</Button>}
              {(ROUND_NEXT[r.status] ?? []).map((s) => (
                <Button key={s} size="sm" variant="ghost" onClick={() => toast$(status.mutateAsync({ id: r.id, s }), `Round ${label(s)}`)}>{label(s)}</Button>
              ))}
            </div>
          ) : null,
        ])}
        empty="No rounds yet."
      />
      {preview && (
        <Card>
          <CardHeader><CardTitle className="flex items-center justify-between text-base">Allotment preview — round {preview.round_number}
            {allot && <Button size="sm" onClick={async () => { if (await toast$(run.mutateAsync({ id: preview.round_id, dry: false }), 'Allotment queued — follow it in the jobs tray')) setPreview(null); }}>Confirm &amp; run</Button>}
          </CardTitle></CardHeader>
          <CardContent><SummaryView s={preview} /></CardContent>
        </Card>
      )}
      {sel && (
        <Card>
          <CardHeader><CardTitle className="text-base">Allotments</CardTitle></CardHeader>
          <CardContent>
            <SimpleTable
              head={['Application', 'Name', 'Programme', 'Quota / category', 'Pref.', 'Status']}
              rows={(allots.data?.data ?? []).map((a) => [a.application_number, a.applicant_name, a.program_code, `${a.quota} · ${a.category}`, a.priority ?? '—', <StatusBadge key="s" status={a.status} />])}
              empty="No allotments in this round."
            />
          </CardContent>
        </Card>
      )}
      <Modal
        open={form.open}
        onOpenChange={(o) => setForm((f) => ({ ...f, open: o }))}
        title="New counselling round"
        footer={<Button disabled={create.isPending} onClick={async () => { if (await toast$(create.mutateAsync(undefined), 'Round created')) setForm((f) => ({ ...f, open: false })); }}>Create</Button>}
      >
        <div className="space-y-3">
          <FormField label="Round number" type="number" value={form.number} onChange={(e) => setForm((f) => ({ ...f, number: e.target.value }))} />
          <FormField label="Reporting deadline" type="datetime-local" value={form.deadline} onChange={(e) => setForm((f) => ({ ...f, deadline: e.target.value }))} />
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.final} onChange={(e) => setForm((f) => ({ ...f, final: e.target.checked }))} /> Final round (de-reservation applies)</label>
        </div>
      </Modal>
    </div>
  );
}

export function OffersTab({ cycleId }: { cycleId: string }) {
  const q = useOffers(cycleId);
  return (
    <SimpleTable
      head={['Application', 'Name', 'Programme', 'Type', 'Valid until', 'Status']}
      rows={(q.data?.data ?? []).map((o) => [o.application_number, o.applicant_name, o.program_code, label(o.offer_type), o.valid_until ?? '—', <StatusBadge key="s" status={o.status} />])}
      empty="No offers issued."
    />
  );
}

// ---- counselling CSV import -------------------------------------------------------------------------------------------------------
export function ImportModal({ cycleId, open, onOpenChange }: { cycleId: string; open: boolean; onOpenChange: (o: boolean) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [mapping, setMapping] = useState('');
  const [report, setReport] = useState<ImportResult | null>(null);
  const [busy, setBusy] = useState(false);
  const go = async (dry: boolean) => {
    if (!file) return;
    setBusy(true);
    try {
      const r = await admissionsApi.importCsv(cycleId, file, dry, mapping || undefined);
      if (dry) setReport(r.data);
      else {
        toast.success('Import queued — the report arrives in the jobs tray');
        onOpenChange(false);
      }
    } catch (e) {
      toast.error(getApiError(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Import counselling CSV" size="lg"
      footer={<div className="flex gap-2"><Button variant="outline" disabled={!file || busy} onClick={() => go(true)}><RotateCcw className="h-4 w-4" /> Dry run</Button><Button disabled={!report || busy || report.succeeded === 0} onClick={() => go(false)}><Upload className="h-4 w-4" /> Import</Button></div>}>
      <div className="space-y-3">
        <input type="file" accept=".csv" aria-label="CSV file" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setReport(null); }} />
        <Textarea rows={3} placeholder='Optional mapping JSON, e.g. {"application_number": "Roll No", "first_name": "Name"}' value={mapping} onChange={(e) => setMapping(e.target.value)} />
        {report && (
          <div className="space-y-2 text-sm">
            <p>{report.total} rows · {report.succeeded} valid · {report.allotted} with allotment · {report.failed.length} errors</p>
            <SimpleTable head={['Row', 'Error']} rows={report.failed.map((f) => [f.row, f.error])} empty="No errors." />
          </div>
        )}
      </div>
    </Modal>
  );
}
