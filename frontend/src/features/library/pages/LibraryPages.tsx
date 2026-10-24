import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { SimpleTable } from '@/features/hr/components/shared';
import { libraryApi } from '../api';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));
const useQ = <T,>(key: unknown[], fn: () => Promise<T>, enabled = true) => useQuery({ queryKey: ['library', ...key], queryFn: fn, enabled, retry: false });
function useRun() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(), onSuccess: () => qc.invalidateQueries({ queryKey: ['library'] }) });
}
const rupees = (p: number | null | undefined) => `₹${((p ?? 0) / 100).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`;
const DueChip = ({ i }: { i: Any }) => (i.status === 'returned' ? <Badge variant="secondary">returned</Badge> : i.days_overdue > 0 ? <Badge variant="destructive">{i.days_overdue}d overdue</Badge> : <Badge variant="outline">due {i.due_on}</Badge>);

function Section({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <Card><CardContent className="space-y-3 p-4">
      <div className="flex items-center justify-between"><h2 className="text-sm font-semibold">{title}</h2>{action}</div>
      {children}
    </CardContent></Card>
  );
}

// ---- /admin/library/catalogue ------------------------------------------------------------------------------------------------
export function CataloguePage() {
  useTitle('Library catalogue');
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);
  const books = useQ(['books', q, page], () => libraryApi.books({ q: q || undefined, page, page_size: 50 }));
  const cats = useQ(['cats'], () => libraryApi.categories());
  const [sel, setSel] = useState<Any | null>(null);
  const copies = useQ(['copies', sel?.id], () => libraryApi.copies(sel.id), !!sel);
  const [form, setForm] = useState<Any | null>(null);
  const [imp, setImp] = useState<string | null>(null);
  const [add, setAdd] = useState({ count: 1, location: '' });
  const run = useRun();
  const total = Number((books.data as Any)?.meta?.total ?? 0);
  return (
    <div className="space-y-4">
      <PageHeader title="Catalogue" description="Books, journals, theses and reference — copies with accession numbers, barcodes and RFID tags." actions={<div className="flex gap-2"><Button variant="outline" onClick={() => setImp('title,authors,isbn,publisher,year,category,copies,location\n')}>Import CSV</Button><Button onClick={() => setForm({ title: '', authors: '', isbn: '', publisher: '', year: '', category_id: '', resource_type: 'book' })}>New book</Button></div>} />
      <div className="flex items-center gap-2"><Input className="w-96" placeholder="Search title / author / ISBN / subject" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} /><span className="text-xs text-muted-foreground">{total} titles</span></div>
      <SimpleTable head={['Title', 'Authors', 'ISBN', 'Category', 'Type', 'Available', '']} rows={(books.data?.data ?? []).map((b: Any) => [b.title, (b.authors ?? []).join(', '), b.isbn ?? '—', b.category ?? '—', b.resource_type, `${b.available_copies} / ${b.total_copies}`, <Button key="o" size="sm" variant="outline" onClick={() => setSel(b)}>Copies</Button>])} />
      <div className="flex gap-2"><Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>Prev</Button><Button size="sm" variant="outline" disabled={page * 50 >= total} onClick={() => setPage(page + 1)}>Next</Button></div>
      <Modal open={!!sel} onOpenChange={(o) => !o && setSel(null)} title={sel?.title ?? ''} size="lg">
        <div className="mb-3 flex items-center gap-2">
          <Input type="number" className="w-20" min={1} value={add.count} onChange={(e) => setAdd({ ...add, count: Number(e.target.value) || 1 })} />
          <Input className="w-40" placeholder="Location" value={add.location} onChange={(e) => setAdd({ ...add, location: e.target.value })} />
          <Button size="sm" onClick={() => run.mutate(() => libraryApi.addCopies(sel.id, { count: add.count, location: add.location || undefined }), { onSuccess: () => toast.success('Copies added'), onError: fail })}>Add copies</Button>
        </div>
        <SimpleTable head={['Accession', 'Barcode', 'Location', 'Status', '']} rows={(copies.data?.data ?? []).map((c: Any) => [c.accession_number, c.barcode, c.location ?? '—', <StatusBadge key="s" status={c.status} />,
          !['issued', 'reserved'].includes(c.status) ? (
            <select key="c" className="h-8 rounded-md border bg-background px-1 text-xs" value="" onChange={(e) => e.target.value && run.mutate(() => libraryApi.copyStatus(c.id, { status: e.target.value }), { onSuccess: () => toast.success('Status changed'), onError: fail })}>
              <option value="">Set status…</option>{['available', 'damaged', 'withdrawn', 'reference_only'].filter((s) => s !== c.status).map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          ) : null])} />
      </Modal>
      <Modal open={!!form} onOpenChange={(o) => !o && setForm(null)} title="New book"
        footer={<Button disabled={!form?.title} onClick={() => run.mutate(() => libraryApi.createBook({ title: form.title, authors: form.authors.split(';').map((s: string) => s.trim()).filter(Boolean), isbn: form.isbn || undefined, publisher: form.publisher || undefined, year: form.year ? Number(form.year) : undefined, category_id: form.category_id || undefined, resource_type: form.resource_type }).then((r: Any) => { if (r.data?.warnings?.length) toast.warning?.(`Saved — ${r.data.warnings.join(', ')}`); }), { onSuccess: () => { toast.success('Book created'); setForm(null); }, onError: fail })}>Create</Button>}>
        {form && (
          <div className="space-y-2 text-sm">
            <Input placeholder="Title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
            <Input placeholder="Authors (; separated)" value={form.authors} onChange={(e) => setForm({ ...form, authors: e.target.value })} />
            <Input placeholder="ISBN (10 or 13)" value={form.isbn} onChange={(e) => setForm({ ...form, isbn: e.target.value })} />
            <Input placeholder="Publisher" value={form.publisher} onChange={(e) => setForm({ ...form, publisher: e.target.value })} />
            <Input placeholder="Year" value={form.year} onChange={(e) => setForm({ ...form, year: e.target.value })} />
            <select className="h-9 w-full rounded-md border bg-background px-2" value={form.category_id} onChange={(e) => setForm({ ...form, category_id: e.target.value })}><option value="">Category…</option>{(cats.data?.data ?? []).map((c: Any) => <option key={c.id} value={c.id}>{c.ddc_code ? `${c.ddc_code} ` : ''}{c.name}</option>)}</select>
            <select className="h-9 w-full rounded-md border bg-background px-2" value={form.resource_type} onChange={(e) => setForm({ ...form, resource_type: e.target.value })}>{['book', 'journal', 'thesis', 'ebook', 'ejournal', 'cd', 'reference'].map((t) => <option key={t}>{t}</option>)}</select>
          </div>
        )}
      </Modal>
      <Modal open={imp !== null} onOpenChange={(o) => !o && setImp(null)} title="Import catalogue (CSV)" size="lg"
        footer={<Button disabled={!imp || imp.split('\n').length < 2} onClick={() => run.mutate(() => libraryApi.importBooks({ csv: imp }), { onSuccess: () => { toast.success('Import queued — see Background jobs for the report'); setImp(null); }, onError: fail })}>Import</Button>}>
        <textarea className="min-h-48 w-full rounded-md border bg-background p-2 font-mono text-xs" value={imp ?? ''} onChange={(e) => setImp(e.target.value)} />
      </Modal>
    </div>
  );
}

// ---- /admin/library/circulation (counter) ---------------------------------------------------------------------------------------
export function CirculationPage() {
  useTitle('Circulation');
  const [code, setCode] = useState('');
  const [member, setMember] = useState<Any | null>(null);
  const [scan, setScan] = useState('');
  const [log, setLog] = useState<string[]>([]);
  const scanRef = useRef<HTMLInputElement>(null);
  const memberIssues = useQ(['m-issues', member?.id], () => libraryApi.issues({ member_id: member.id }), !!member);
  const run = useRun();
  const note = (s: string) => setLog((l) => [`${new Date().toLocaleTimeString()} · ${s}`, ...l].slice(0, 30));
  const lookup = () => libraryApi.members({}).then((r: Any) => {
    const m = (r.data ?? []).find((x: Any) => x.member_code.toLowerCase() === code.trim().toLowerCase());
    if (!m) throw new Error('Member not found');
    setMember(m);
    setTimeout(() => scanRef.current?.focus(), 50);
  }).catch(fail);
  const act = (kind: 'issue' | 'return') => run.mutate(
    () => (kind === 'issue' ? libraryApi.issue({ member_code: member.member_code, barcode: scan.trim() }) : libraryApi.return({ barcode: scan.trim() })).then((r: Any) => {
      if (kind === 'issue') note(`Issued ${r.data.title} — due ${r.data.due_on}`);
      else note(`Returned ${r.data.issue.title}${r.data.fine_paise ? ` — fine ${rupees(r.data.fine_paise)}` : ''}${r.data.reservation_notified ? ' — held for a reservation' : ''}`);
      setScan('');
    }),
    { onError: fail },
  );
  return (
    <div className="space-y-4">
      <PageHeader title="Circulation" description="Scan the member card, then scan copies — Enter issues, Shift+Enter returns." />
      <div className="grid gap-4 lg:grid-cols-3">
        <Section title="Member">
          <div className="flex gap-2"><Input autoFocus placeholder="Member code (LM…)" value={code} onChange={(e) => setCode(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && lookup()} /><Button onClick={lookup}>Find</Button></div>
          {member && (
            <div className="space-y-1 text-sm">
              <p className="font-medium">{member.name} · {member.member_code} · {member.member_type}</p>
              <p>{member.active_issues} / {member.max_books_allowed} books · loan {member.loan_days} days · fines {rupees(member.outstanding_fine_paise)}</p>
              {member.is_blocked ? <div className="flex flex-wrap gap-1">{member.block_reasons.map((r: string) => <Badge key={r} variant="destructive">{r}</Badge>)}</div> : <Badge variant="success">can borrow</Badge>}
            </div>
          )}
        </Section>
        <Section title="Scan copy">
          <Input ref={scanRef} placeholder="Barcode / accession" value={scan} onChange={(e) => setScan(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && scan) { e.preventDefault(); act(e.shiftKey || !member ? 'return' : 'issue'); } }} />
          <div className="flex gap-2"><Button disabled={!member || !scan} onClick={() => act('issue')}>Issue</Button><Button variant="outline" disabled={!scan} onClick={() => act('return')}>Return</Button></div>
        </Section>
        <Section title="Session log"><div className="max-h-48 space-y-1 overflow-auto text-xs">{log.map((l) => <p key={l}>{l}</p>)}</div></Section>
      </div>
      {member && (
        <Section title="On loan">
          <SimpleTable head={['Title', 'Accession', 'Issued', 'Due', '']} rows={(memberIssues.data?.data ?? []).filter((i: Any) => ['issued', 'overdue'].includes(i.status)).map((i: Any) => [i.title, i.accession_number, i.issued_on, <DueChip key="d" i={i} />,
            <div key="a" className="flex gap-1">
              <Button size="sm" variant="outline" onClick={() => run.mutate(() => libraryApi.renew(i.id), { onSuccess: () => note(`Renewed ${i.title}`), onError: fail })}>Renew</Button>
              <Button size="sm" variant="destructive" onClick={() => run.mutate(() => libraryApi.lost({ issue_id: i.id }), { onSuccess: () => note(`Lost ${i.title}`), onError: fail })}>Lost</Button>
            </div>])} />
        </Section>
      )}
    </div>
  );
}

// ---- /admin/library/issues -------------------------------------------------------------------------------------------------------
export function IssuesPage() {
  useTitle('Library issues');
  const [tab, setTab] = useState<'issued' | 'overdue' | 'returned' | 'lost'>('overdue');
  const q = useQ(['issues', tab], () => libraryApi.issues(tab === 'overdue' ? { overdue: true } : { status: tab }));
  return (
    <div className="space-y-4">
      <PageHeader title="Issues" description="Active, overdue, returned and lost — HODs see their department's members." />
      <div className="flex gap-1">{(['issued', 'overdue', 'returned', 'lost'] as const).map((t) => <Button key={t} size="sm" variant={tab === t ? 'default' : 'outline'} onClick={() => setTab(t)}>{t}</Button>)}</div>
      {q.data?.meta?.visibility?.scopes?.length ? <p className="text-xs text-muted-foreground">Scope: {q.data.meta.visibility.scopes.join(', ')}</p> : null}
      <SimpleTable head={['Member', 'Name', 'Title', 'Accession', 'Issued', 'Due', 'Fine']} rows={(q.data?.data ?? []).map((i: Any) => [i.member_code, i.member_name, i.title, i.accession_number, i.issued_on, <DueChip key="d" i={i} />, i.fine_paise ? rupees(i.fine_paise) : '—'])} />
    </div>
  );
}

// ---- /admin/library/reservations ----------------------------------------------------------------------------------------------------
export function ReservationsPage() {
  useTitle('Reservations');
  const q = useQ(['res'], () => libraryApi.reservations({}));
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Reservations" description="FIFO queue per title; available holds expire after the pickup window." />
      <SimpleTable head={['Title', 'Member', 'Status', 'Position', 'Reserved', 'Expires', '']} rows={(q.data?.data ?? []).map((r: Any) => [r.title, `${r.member_code} ${r.member_name ?? ''}`, <StatusBadge key="s" status={r.status} />, r.position ?? '—', new Date(r.reserved_at).toLocaleDateString(), r.expires_at ? new Date(r.expires_at).toLocaleString() : '—',
        ['waiting', 'available'].includes(r.status) ? <Button key="c" size="sm" variant="ghost" onClick={() => run.mutate(() => libraryApi.cancelReservation(r.id), { onError: fail })}>Cancel</Button> : null])} />
    </div>
  );
}

// ---- /admin/library/fines ---------------------------------------------------------------------------------------------------------
export function FinesPage() {
  useTitle('Library fines');
  const [status, setStatus] = useState('outstanding');
  const q = useQ(['fines', status], () => libraryApi.fines({ status: status || undefined }));
  const [waive, setWaive] = useState<Any | null>(null);
  const [reason, setReason] = useState('');
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Fines" description="Overdue fines and lost-book charges are fee invoices — collect them at the fee counter; the librarian may waive unpaid fines." />
      <select className="h-9 rounded-md border bg-background px-2 text-sm" value={status} onChange={(e) => setStatus(e.target.value)}><option value="outstanding">Outstanding</option><option value="paid">Paid</option><option value="cancelled">Waived / cancelled</option><option value="">All</option></select>
      <SimpleTable head={['Member', 'Name', 'Title', 'Fine', 'Balance', 'Invoice', '']} rows={(q.data?.data ?? []).map((f: Any) => [f.member_code, f.member_name, f.title, rupees(f.fine_paise), rupees(f.balance_paise), <StatusBadge key="s" status={f.invoice_status} />,
        ['pending', 'partial', 'overdue'].includes(f.invoice_status) ? <Button key="w" size="sm" variant="outline" onClick={() => { setWaive(f); setReason(''); }}>Waive</Button> : null])} />
      <Modal open={!!waive} onOpenChange={(o) => !o && setWaive(null)} title="Waive fine" footer={<Button disabled={reason.length < 5} onClick={() => run.mutate(() => libraryApi.waive(waive.issue_id, reason), { onSuccess: () => { toast.success('Waived'); setWaive(null); }, onError: fail })}>Waive {rupees(waive?.balance_paise)}</Button>}>
        <textarea className="min-h-20 w-full rounded-md border bg-background p-2 text-sm" placeholder="Reason" value={reason} onChange={(e) => setReason(e.target.value)} />
      </Modal>
    </div>
  );
}

// ---- /admin/library/members --------------------------------------------------------------------------------------------------------
export function MembersPage() {
  useTitle('Library members');
  const [type, setType] = useState('');
  const q = useQ(['members', type], () => libraryApi.members({ type: type || undefined }));
  const [edit, setEdit] = useState<Any | null>(null);
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="Members" description="Auto-provisioned from students and staff; external / alumni members with a deposit." />
      <select className="h-9 rounded-md border bg-background px-2 text-sm" value={type} onChange={(e) => setType(e.target.value)}><option value="">All types</option>{['student', 'faculty', 'staff', 'scholar', 'alumni', 'external'].map((t) => <option key={t}>{t}</option>)}</select>
      <SimpleTable head={['Code', 'Name', 'Type', 'Limits', 'On loan', 'Fines', 'Status', '']} rows={(q.data?.data ?? []).slice(0, 500).map((m: Any) => [m.member_code, m.name, m.member_type, `${m.max_books_allowed} · ${m.loan_days}d`, `${m.active_issues}${m.overdue_issues ? ` (${m.overdue_issues} overdue)` : ''}`, rupees(m.outstanding_fine_paise),
        m.is_blocked ? <div key="b" className="flex flex-wrap gap-1">{m.block_reasons.map((r: string) => <Badge key={r} variant="destructive">{r}</Badge>)}</div> : <Badge key="b" variant="success">active</Badge>,
        <div key="a" className="flex gap-1">
          <Button size="sm" variant="ghost" onClick={() => setEdit({ ...m })}>Rules</Button>
          {m.is_active ? <Button size="sm" variant="outline" onClick={() => run.mutate(() => libraryApi.suspend(m.id), { onError: fail })}>Suspend</Button> : <Button size="sm" onClick={() => run.mutate(() => libraryApi.activate(m.id), { onError: fail })}>Activate</Button>}
        </div>])} />
      <Modal open={!!edit} onOpenChange={(o) => !o && setEdit(null)} title={`Limits — ${edit?.member_code ?? ''}`} footer={<Button onClick={() => run.mutate(() => libraryApi.memberRules(edit.id, { max_books_allowed: Number(edit.max_books_allowed), loan_days: Number(edit.loan_days), valid_to: edit.valid_to || undefined }), { onSuccess: () => { toast.success('Saved'); setEdit(null); }, onError: fail })}>Save</Button>}>
        {edit && <div className="space-y-2 text-sm">
          <label className="block">Max books <Input type="number" value={edit.max_books_allowed} onChange={(e) => setEdit({ ...edit, max_books_allowed: e.target.value })} /></label>
          <label className="block">Loan days <Input type="number" value={edit.loan_days} onChange={(e) => setEdit({ ...edit, loan_days: e.target.value })} /></label>
          <label className="block">Valid to <Input type="date" value={edit.valid_to ?? ''} onChange={(e) => setEdit({ ...edit, valid_to: e.target.value })} /></label>
        </div>}
      </Modal>
    </div>
  );
}

// ---- /admin/library/eresources -----------------------------------------------------------------------------------------------------
export function EresourcesPage() {
  useTitle('E-resources');
  const q = useQ(['eres'], () => libraryApi.eresources());
  const [form, setForm] = useState<Any | null>(null);
  const run = useRun();
  return (
    <div className="space-y-4">
      <PageHeader title="E-resources" description="Subscriptions (IP / remote / open access) with costs and usage for NAAC 4.2." actions={<Button onClick={() => setForm({ title: '', provider: '', resource_type: 'ejournal', url: '', access_type: 'ip', subscription_from: '', subscription_to: '', cost: '' })}>Add</Button>} />
      <SimpleTable head={['Title', 'Provider', 'Type', 'Access', 'Subscription', 'Cost', 'Opens', '']} rows={(q.data?.data ?? []).map((r: Any) => [r.title, r.provider ?? '—', r.resource_type, r.access_type, <span key="s">{r.subscription_to ?? '—'} {r.expired ? <Badge variant="destructive">expired</Badge> : r.expiring_soon ? <Badge variant="warning">expiring</Badge> : null}</span>, r.cost_paise ? rupees(r.cost_paise) : '—', r.usage_count,
        <a key="o" className="text-primary underline" href={`/api/v1/library/eresources/${r.id}/open`} target="_blank" rel="noreferrer">Open</a>])} />
      <Modal open={!!form} onOpenChange={(o) => !o && setForm(null)} title="Add e-resource" footer={<Button disabled={!form?.title || !form?.url} onClick={() => run.mutate(() => libraryApi.saveEresource({ title: form.title, provider: form.provider || undefined, resource_type: form.resource_type, url: form.url, access_type: form.access_type, subscription_from: form.subscription_from || undefined, subscription_to: form.subscription_to || undefined, cost_paise: form.cost ? Math.round(Number(form.cost) * 100) : undefined }), { onSuccess: () => { toast.success('Saved'); setForm(null); }, onError: fail })}>Save</Button>}>
        {form && <div className="space-y-2 text-sm">
          <Input placeholder="Title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          <Input placeholder="Provider" value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })} />
          <Input placeholder="URL" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} />
          <div className="flex gap-2">
            <select className="h-9 rounded-md border bg-background px-2" value={form.resource_type} onChange={(e) => setForm({ ...form, resource_type: e.target.value })}>{['ejournal', 'ebook_db', 'database', 'repository'].map((t) => <option key={t}>{t}</option>)}</select>
            <select className="h-9 rounded-md border bg-background px-2" value={form.access_type} onChange={(e) => setForm({ ...form, access_type: e.target.value })}>{['ip', 'remote', 'open'].map((t) => <option key={t}>{t}</option>)}</select>
          </div>
          <div className="flex gap-2"><Input type="date" value={form.subscription_from} onChange={(e) => setForm({ ...form, subscription_from: e.target.value })} /><Input type="date" value={form.subscription_to} onChange={(e) => setForm({ ...form, subscription_to: e.target.value })} /></div>
          <Input placeholder="Cost (₹)" value={form.cost} onChange={(e) => setForm({ ...form, cost: e.target.value })} />
        </div>}
      </Modal>
    </div>
  );
}

// ---- /admin/library/ill ---------------------------------------------------------------------------------------------------------------
export function IllPage() {
  useTitle('Inter-library loans');
  const q = useQ(['ill'], () => libraryApi.ill());
  const run = useRun();
  const next: Record<string, 'decide' | 'receive' | 'return'> = { requested: 'decide', approved: 'receive', received: 'return' };
  return (
    <div className="space-y-4">
      <PageHeader title="Inter-library loans" description="Requested → approved → received → returned." />
      <SimpleTable head={['Member', 'Title', 'Source', 'Cost', 'Status', '']} rows={(q.data?.data ?? []).map((r: Any) => [`${r.member_code} ${r.member_name ?? ''}`, r.title, r.source_library ?? '—', r.cost_paise ? rupees(r.cost_paise) : '—', <StatusBadge key="s" status={r.status} />,
        next[r.status] ? <div key="a" className="flex gap-1"><Button size="sm" onClick={() => run.mutate(() => libraryApi.illAction(r.id, next[r.status], next[r.status] === 'decide' ? { approve: true } : {}), { onError: fail })}>{next[r.status] === 'decide' ? 'Approve' : next[r.status]}</Button>{r.status === 'requested' && <Button size="sm" variant="ghost" onClick={() => run.mutate(() => libraryApi.illAction(r.id, 'decide', { approve: false }), { onError: fail })}>Decline</Button>}</div> : null])} />
    </div>
  );
}

// ---- /admin/library/stock-verification -------------------------------------------------------------------------------------------
export function StockVerificationPage() {
  useTitle('Stock verification');
  const [location, setLocation] = useState('');
  const [scans, setScans] = useState('');
  const [job, setJob] = useState<string | null>(null);
  const res = useQuery({ queryKey: ['library', 'stock', job], queryFn: () => libraryApi.stockResult(job!), enabled: !!job, refetchInterval: (s) => ((s.state.data as Any)?.data?.status === 'succeeded' ? false : 2000) });
  const r = (res.data as Any)?.data?.result;
  return (
    <div className="space-y-4">
      <PageHeader title="Stock verification" description="Scan every copy on the shelf (one barcode per line) — the report lists missing and unexpected copies." />
      <Input className="w-64" placeholder="Location (optional, e.g. Stack A)" value={location} onChange={(e) => setLocation(e.target.value)} />
      <textarea className="min-h-40 w-full rounded-md border bg-background p-2 font-mono text-xs" placeholder="Scanned barcodes" value={scans} onChange={(e) => setScans(e.target.value)} />
      <Button onClick={() => libraryApi.stockVerification({ location: location || undefined, scanned_barcodes: scans.split(/\s+/).filter(Boolean) }).then((x: Any) => setJob(x.data.job_id)).catch(fail)}>Verify</Button>
      {r && (
        <Section title={`Expected ${r.expected} · found ${r.found}`}>
          <SimpleTable head={['Missing accession', 'Title', 'Location']} rows={r.missing.slice(0, 500).map((m: Any) => [m.accession_number, m.title, m.location ?? '—'])} />
          <p className="text-xs">Unexpected: {r.unexpected.join(', ') || '—'}</p>
        </Section>
      )}
    </div>
  );
}

// ---- /admin/library/reports ------------------------------------------------------------------------------------------------------
export function LibraryReportsPage() {
  useTitle('Library reports');
  const stats = useQ(['stats'], () => libraryApi.stats());
  const s = stats.data?.data;
  const go = (kind: string) => libraryApi.report(kind).then(() => toast.success('Report queued — download it from Background jobs')).catch(fail);
  return (
    <div className="space-y-4">
      <PageHeader title="Library reports" description="Registers and NAAC 4.2 metrics (exports run as background jobs)." />
      {s && <div className="grid gap-3 sm:grid-cols-4">{[['Titles', s.books], ['Copies', s.copies], ['On loan', s.issued], ['Overdue', s.overdue], ['Lost', s.lost], ['Members', s.members], ['Holds waiting', s.reservations_waiting], ['Unpaid fines', rupees(s.outstanding_fine_paise)]].map(([k, v]) => <Card key={String(k)}><CardContent className="p-4"><p className="text-xs text-muted-foreground">{k}</p><p className="text-xl font-semibold">{String(v)}</p></CardContent></Card>)}</div>}
      <div className="flex flex-wrap gap-2">{['accession_register', 'circulation', 'overdue', 'eresource_usage', 'naac_4_2'].map((k) => <Button key={k} variant="outline" onClick={() => go(k)}>{k.replace(/_/g, ' ')}</Button>)}</div>
    </div>
  );
}

// ---- /student/library (and faculty / parent / alumni) -------------------------------------------------------------------------------
export function MyLibraryPage({ ward = false }: { ward?: boolean }) {
  useTitle('My library');
  const me = useQ(['me', ward], () => (ward ? libraryApi.wards() : libraryApi.me()));
  const issues = useQ(['me-issues'], () => libraryApi.myIssues(), !ward);
  const fines = useQ(['me-fines'], () => libraryApi.myFines(), !ward);
  const res = useQ(['me-res'], () => libraryApi.reservations({ mine: true }), !ward);
  const run = useRun();
  const cards: Any[] = ward ? me.data?.data ?? [] : me.data?.data ? [me.data.data] : [];
  return (
    <div className="space-y-4">
      <PageHeader title={ward ? "Ward's library" : 'My library'} description="Books on loan, due dates, renewals, reservations and fines." />
      {cards.map((m) => (
        <Card key={m.id}><CardContent className="space-y-1 p-4 text-sm">
          <p className="font-medium">{m.name} · {m.member_code}</p>
          <p>{m.active_issues} / {m.max_books_allowed} books · fines {rupees(m.outstanding_fine_paise)} {m.valid_to ? `· valid to ${m.valid_to}` : ''}</p>
          {m.is_blocked && <div className="flex flex-wrap gap-1">{m.block_reasons.map((r: string) => <Badge key={r} variant="destructive">{r}</Badge>)}</div>}
        </CardContent></Card>
      ))}
      {!ward && (
        <>
          <Section title="My books">
            <SimpleTable head={['Title', 'Issued', 'Due', 'Renewals', '']} rows={(issues.data?.data ?? []).filter((i: Any) => ['issued', 'overdue'].includes(i.status)).map((i: Any) => [i.title, i.issued_on, <DueChip key="d" i={i} />, i.renewals, <Button key="r" size="sm" variant="outline" onClick={() => run.mutate(() => libraryApi.selfRenew(i.id), { onSuccess: () => toast.success('Renewed'), onError: fail })}>Renew</Button>])} empty="No books on loan." />
          </Section>
          <Section title="Reservations"><SimpleTable head={['Title', 'Status', 'Position', 'Collect by', '']} rows={(res.data?.data ?? []).filter((r: Any) => ['waiting', 'available'].includes(r.status)).map((r: Any) => [r.title, <StatusBadge key="s" status={r.status} />, r.position ?? '—', r.expires_at ? new Date(r.expires_at).toLocaleString() : '—', <Button key="c" size="sm" variant="ghost" onClick={() => run.mutate(() => libraryApi.cancelReservation(r.id), { onError: fail })}>Cancel</Button>])} empty="No reservations." /></Section>
          <Section title="Fines"><SimpleTable head={['Title', 'Fine', 'Balance', 'Status']} rows={(fines.data?.data ?? []).map((f: Any) => [f.title, rupees(f.fine_paise), rupees(f.balance_paise), <StatusBadge key="s" status={f.invoice_status} />])} empty="No fines." /><p className="text-xs text-muted-foreground">Pay outstanding fines under Fees.</p></Section>
          <p className="text-sm"><a className="text-primary underline" href="/opac">Search the catalogue (OPAC)</a></p>
        </>
      )}
    </div>
  );
}

export function WardLibraryPage() {
  return <MyLibraryPage ward />;
}

// ---- /opac (public) ---------------------------------------------------------------------------------------------------------------------
export function OpacPage() {
  useTitle('Library catalogue');
  const params = new URLSearchParams(window.location.search);
  const [institution, setInstitution] = useState(params.get('institution') ?? '');
  const [q, setQ] = useState(params.get('q') ?? '');
  const [avail, setAvail] = useState(false);
  const [rt, setRt] = useState('');
  const [submitted, setSubmitted] = useState(!!params.get('q'));
  const res = useQuery({ queryKey: ['opac', institution, q, avail, rt, submitted], queryFn: () => libraryApi.opac({ institution, q: q || undefined, available_only: avail, resource_type: rt || undefined }), enabled: submitted && !!institution, retry: false });
  const d = (res.data as Any)?.data;
  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4">
      <h1 className="text-xl font-semibold">Library catalogue</h1>
      <div className="flex flex-wrap gap-2">
        {!params.get('institution') && <Input className="w-40" placeholder="Institution code" value={institution} onChange={(e) => setInstitution(e.target.value)} />}
        <Input className="w-96" placeholder="Title, author, ISBN or subject" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && setSubmitted(true)} />
        <select className="h-9 rounded-md border bg-background px-2 text-sm" value={rt} onChange={(e) => setRt(e.target.value)}><option value="">All types</option>{['book', 'journal', 'thesis', 'ebook', 'reference'].map((t) => <option key={t}>{t}</option>)}</select>
        <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={avail} onChange={(e) => setAvail(e.target.checked)} /> available now</label>
        <Button onClick={() => setSubmitted(true)}>Search</Button>
      </div>
      {res.isError && <p className="text-sm text-status-rejected">{getApiError(res.error)}</p>}
      {d && (
        <div className="grid gap-4 md:grid-cols-4">
          <div className="space-y-3 text-sm">
            {Object.entries(d.facets ?? {}).map(([k, vals]) => (
              <div key={k}><p className="font-medium capitalize">{k.replace('_', ' ')}</p>{(vals as Any[]).slice(0, 8).map((v) => <p key={String(v.value)} className="text-xs text-muted-foreground">{String(v.value)} ({v.count})</p>)}</div>
            ))}
          </div>
          <div className="space-y-2 md:col-span-3">
            <p className="text-xs text-muted-foreground">{d.total} result(s)</p>
            {d.items.map((b: Any) => (
              <Card key={b.id}><CardContent className="p-3 text-sm">
                <p className="font-medium">{b.title}</p>
                <p className="text-xs text-muted-foreground">{(b.authors ?? []).join(', ')} · {b.publisher ?? ''} {b.year ?? ''} · {b.resource_type}{b.isbn ? ` · ISBN ${b.isbn}` : ''}</p>
                <p className="text-xs">{b.available_copies > 0 ? <Badge variant="success">{b.available_copies} of {b.total_copies} available</Badge> : <Badge variant="warning">all {b.total_copies} on loan</Badge>} {b.locations.join(', ')}</p>
              </CardContent></Card>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
