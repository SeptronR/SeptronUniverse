import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Banknote, Copy, Download, Plus, Printer, QrCode, RefreshCw, Search, Upload } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { ScopeTabs } from '@/components/shared/ScopeTabs';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Input, Select, Textarea } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs';
import { toast } from '@/components/ui/Toaster';
import { usePermission } from '@/hooks/usePermission';
import { localDate } from '@/features/hr/types';
import { SimpleTable, WorkflowPanel } from '@/features/hr/components/shared';
import { feesApi, noDuesApi, openBlob, scholarshipsApi } from '../api';
import {
  useApplications,
  useCancelQueue,
  useDayBook,
  useDiscounts,
  useFeeDashboard,
  useFeesMutation,
  useFines,
  useHeads,
  useInvoice,
  useInvoices,
  useNoDues,
  usePayments,
  usePendingDiscounts,
  useReconcile,
  useRefunds,
  useReport,
  useSchemes,
  useStructures,
} from '../hooks';
import {
  DEPARTMENT_KEYS,
  INVOICE_VARIANT,
  PAYMENT_MODES,
  inr,
  toPaise,
  type FeeStructure,
  type FineConfig,
  type Invoice,
  type NoDues,
  type Payment,
  type StructureItem,
  type UpiQr,
} from '../types';

const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));
const InvBadge = ({ s }: { s: string }) => <Badge variant={INVOICE_VARIANT[s] ?? 'secondary'}>{s}</Badge>;

function Stat({ label, value, tone }: { label: string; value: string | number; tone?: string }) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className={`text-xl font-semibold ${tone ?? ''}`}>{value}</p>
      </CardContent>
    </Card>
  );
}

// ---- /admin/fees -----------------------------------------------------------------------------------------------------
export function FeesDashboardPage() {
  useTitle('Fees');
  const d = useFeeDashboard().data?.data;
  const navigate = useNavigate();
  return (
    <div className="space-y-4">
      <PageHeader title="Fees" description="Today's collection, dues and the queues waiting for you." />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Collected today" value={inr(d?.today_total)} />
        <Stat label="Outstanding dues" value={inr(d?.dues_total)} />
        <Stat label={`Overdue (${d?.overdue_count ?? 0} invoices)`} value={inr(d?.overdue_total)} tone="text-destructive" />
        <Stat label="Online orders pending" value={d?.online_initiated ?? 0} />
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <Button variant="outline" onClick={() => navigate('/admin/fees/reconcile')}>Reconciliation pending: {d?.reconcile_pending ?? 0}</Button>
        <Button variant="outline" onClick={() => navigate('/admin/fees/refunds')}>Refunds pending: {d?.refunds_pending ?? 0}</Button>
        <Button variant="outline" onClick={() => navigate('/admin/fees/payments')}>Receipt cancellations: {d?.cancel_pending ?? 0}</Button>
      </div>
      <SimpleTable
        head={['Mode', 'Collected today']}
        rows={Object.entries(d?.today_by_mode ?? {}).map(([m, v]) => [m, inr(v)])}
        empty="Nothing collected yet today."
      />
    </div>
  );
}

// ---- /admin/fees/structures --------------------------------------------------------------------------------------------
function HeadsTab() {
  const heads = useHeads();
  const [form, setForm] = useState({ code: '', name: '', head_type: 'other', is_taxable: false, gst_rate: '', is_refundable: false });
  const save = useFeesMutation(() => feesApi.saveHead({ ...form, gst_rate: form.gst_rate ? Number(form.gst_rate) : null }));
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <Input className="w-28" placeholder="Code" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })} />
        <Input className="w-56" placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <Input className="w-36" placeholder="Type" value={form.head_type} onChange={(e) => setForm({ ...form, head_type: e.target.value })} />
        <label className="flex items-center gap-1 text-sm">
          <input type="checkbox" checked={form.is_taxable} onChange={(e) => setForm({ ...form, is_taxable: e.target.checked })} /> GST
        </label>
        <Input className="w-20" placeholder="Rate %" value={form.gst_rate} onChange={(e) => setForm({ ...form, gst_rate: e.target.value })} />
        <Button disabled={!form.code || !form.name} onClick={() => save.mutate(undefined, { onSuccess: () => toast.success('Head saved'), onError: fail })}>
          <Plus className="h-4 w-4" /> Add head
        </Button>
      </div>
      <SimpleTable
        head={['Code', 'Name', 'Type', 'GST', 'Refundable', 'Active']}
        rows={(heads.data?.data ?? []).map((h) => [h.code, h.name, h.head_type, h.is_taxable ? `${h.gst_rate ?? 0}%` : '—', h.is_refundable ? 'yes' : '—', h.is_active ? 'yes' : 'no'])}
      />
    </div>
  );
}

function StructureBuilder({ open, onOpenChange, base }: { open: boolean; onOpenChange: (o: boolean) => void; base?: FeeStructure | null }) {
  const heads = useHeads().data?.data ?? [];
  const [form, setForm] = useState({ name: '', program_id: '', batch_id: '', category: '', quota: '', term_number: '', effective_from: localDate(), effective_to: '', per_credit: '' });
  const [items, setItems] = useState<StructureItem[]>([]);
  useEffect(() => {
    if (!open) return;
    setForm({
      name: base?.name ?? '',
      program_id: base?.program_id ?? '',
      batch_id: base?.batch_id ?? '',
      category: base?.category ?? '',
      quota: base?.quota ?? '',
      term_number: base?.term_number ? String(base.term_number) : '',
      effective_from: base?.effective_from ?? localDate(),
      effective_to: base?.effective_to ?? '',
      per_credit: base?.per_credit_paise ? String(base.per_credit_paise / 100) : '',
    });
    setItems(base?.items ?? []);
  }, [open, base]);
  const save = useFeesMutation(() => {
    const payload = {
      name: form.name,
      effective_from: form.effective_from,
      effective_to: form.effective_to || null,
      per_credit_paise: form.per_credit ? toPaise(form.per_credit) : null,
      items: items.map(({ fee_head_id, amount_paise, instalment_no, due_date, due_offset_days, is_optional }) => ({ fee_head_id, amount_paise, instalment_no, due_date: due_date || null, due_offset_days: due_offset_days ?? null, is_optional })),
    };
    return base
      ? feesApi.updateStructure(base.id, { ...payload, version: base.version })
      : feesApi.createStructure({
          ...payload,
          program_id: form.program_id || null,
          batch_id: form.batch_id || null,
          category: form.category || null,
          quota: form.quota || null,
          term_number: form.term_number ? Number(form.term_number) : null,
        });
  });
  const total = items.filter((i) => !i.is_optional).reduce((a, i) => a + i.amount_paise, 0);
  return (
    <Modal open={open} onOpenChange={onOpenChange} title={base ? `Edit ${base.name}` : 'New fee structure'} size="xl"
      footer={<Button disabled={!form.name || !items.length} onClick={() => save.mutate(undefined, { onSuccess: () => { toast.success('Structure saved'); onOpenChange(false); }, onError: fail })}>Save</Button>}>
      <div className="grid gap-2 md:grid-cols-3">
        <Input placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <Input placeholder="Programme id" disabled={!!base} value={form.program_id} onChange={(e) => setForm({ ...form, program_id: e.target.value })} />
        <Input placeholder="Batch id (most specific)" disabled={!!base} value={form.batch_id} onChange={(e) => setForm({ ...form, batch_id: e.target.value })} />
        <Input placeholder="Category (e.g. SC)" disabled={!!base} value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} />
        <Input placeholder="Quota" disabled={!!base} value={form.quota} onChange={(e) => setForm({ ...form, quota: e.target.value })} />
        <Input placeholder="Term number" disabled={!!base} value={form.term_number} onChange={(e) => setForm({ ...form, term_number: e.target.value })} />
        <label className="text-xs">Effective from<Input type="date" value={form.effective_from} disabled={!!base} onChange={(e) => setForm({ ...form, effective_from: e.target.value })} /></label>
        <label className="text-xs">Effective to<Input type="date" value={form.effective_to} onChange={(e) => setForm({ ...form, effective_to: e.target.value })} /></label>
        <label className="text-xs">Per-credit arrear fee (₹)<Input value={form.per_credit} onChange={(e) => setForm({ ...form, per_credit: e.target.value })} /></label>
      </div>
      <div className="mt-3 space-y-2">
        {items.map((it, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2">
            <Select className="w-48" value={it.fee_head_id} options={heads.map((h) => ({ value: h.id, label: `${h.code} · ${h.name}` }))} placeholder="Head"
              onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, fee_head_id: e.target.value } : x)))} />
            <Input className="w-28" placeholder="₹" value={it.amount_paise / 100 || ''} onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, amount_paise: toPaise(e.target.value) } : x)))} />
            <Input className="w-20" type="number" min={1} title="Instalment" value={it.instalment_no} onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, instalment_no: Number(e.target.value) } : x)))} />
            <Input className="w-24" type="number" placeholder="+days" title="Due offset from term start" value={it.due_offset_days ?? ''} onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, due_offset_days: e.target.value ? Number(e.target.value) : null } : x)))} />
            <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={it.is_optional} onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, is_optional: e.target.checked } : x)))} /> optional</label>
            <Button size="sm" variant="ghost" onClick={() => setItems(items.filter((_, j) => j !== i))}>Remove</Button>
          </div>
        ))}
        <Button size="sm" variant="outline" onClick={() => setItems([...items, { fee_head_id: heads[0]?.id ?? '', amount_paise: 0, instalment_no: 1, due_offset_days: 15, is_optional: false }])}>
          <Plus className="h-4 w-4" /> Item
        </Button>
        <p className="text-sm">Total (mandatory): <strong>{inr(total)}</strong></p>
      </div>
    </Modal>
  );
}

function StructuresTab() {
  const list = useStructures();
  const [edit, setEdit] = useState<FeeStructure | null | undefined>(undefined);
  const [assign, setAssign] = useState<FeeStructure | null>(null);
  const [batch, setBatch] = useState('');
  const [tester, setTester] = useState({ enrollment_id: '', term_number: '' });
  const [tested, setTested] = useState<string>('');
  const clone = useFeesMutation((s: FeeStructure) => {
    const from = new Date(s.effective_from);
    from.setFullYear(from.getFullYear() + 1);
    return feesApi.cloneStructure(s.id, { effective_from: localDate(from), name: `${s.name} (next year)`, increase_pct: 5 });
  });
  const doAssign = useFeesMutation((dry: boolean) => feesApi.assign(assign!.id, { batch_id: batch, dry_run: dry }));
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => setEdit(null)}><Plus className="h-4 w-4" /> New structure</Button>
        <Input className="w-72" placeholder="Applicability tester: enrolment id" value={tester.enrollment_id} onChange={(e) => setTester({ ...tester, enrollment_id: e.target.value })} />
        <Input className="w-24" placeholder="Term #" value={tester.term_number} onChange={(e) => setTester({ ...tester, term_number: e.target.value })} />
        <Button variant="outline" disabled={!tester.enrollment_id}
          onClick={() => feesApi.applicable({ enrollment_id: tester.enrollment_id, term_number: tester.term_number || undefined }).then((r) => setTested(r.data.structure ? `${r.data.structure.name} — matched on ${r.data.matched_on.join(', ') || 'institution default'}` : 'No structure applies')).catch(fail)}>
          Test
        </Button>
        {tested && <span className="self-center text-sm">{tested}</span>}
      </div>
      <SimpleTable
        head={['Name', 'Dimensions', 'Effective', 'Total', 'Assigned', '']}
        rows={(list.data?.data ?? []).map((s) => [
          s.name,
          [s.batch_id && 'batch', s.program_regulation_id && 'regulation', s.program_id && 'programme', s.category, s.quota, s.term_number && `term ${s.term_number}`].filter(Boolean).map((d) => <Badge key={String(d)} variant="outline" className="mr-1">{d}</Badge>),
          `${s.effective_from} → ${s.effective_to ?? '…'}`,
          inr(s.total_paise),
          s.assigned_count,
          <div key="a" className="flex gap-1">
            <Button size="sm" variant="outline" onClick={() => setEdit(s)}>Edit</Button>
            <Button size="sm" variant="outline" onClick={() => clone.mutate(s, { onSuccess: () => toast.success('Cloned to next year (+5 %)'), onError: fail })}><Copy className="h-3 w-3" /> Clone</Button>
            <Button size="sm" variant="outline" onClick={() => setAssign(s)}>Assign</Button>
          </div>,
        ])}
      />
      <StructureBuilder open={edit !== undefined} onOpenChange={(o) => !o && setEdit(undefined)} base={edit} />
      <Modal open={!!assign} onOpenChange={(o) => !o && setAssign(null)} title={`Assign ${assign?.name ?? ''}`}
        footer={
          <div className="flex gap-2">
            <Button variant="outline" disabled={!batch} onClick={() => doAssign.mutate(true, { onSuccess: (r) => toast.info(`Preview: ${JSON.stringify(r.data)}`), onError: fail })}>Dry run</Button>
            <Button disabled={!batch} onClick={() => doAssign.mutate(false, { onSuccess: () => { toast.success('Assigned — invoices generated (large batches run as a job)'); setAssign(null); }, onError: fail })}>Assign + invoice</Button>
          </div>
        }>
        <Input placeholder="Batch id" value={batch} onChange={(e) => setBatch(e.target.value)} />
      </Modal>
    </div>
  );
}

export function FeeStructuresPage() {
  useTitle('Fee structures');
  return (
    <div className="space-y-4">
      <PageHeader title="Fee structures" description="Heads, effective-dated structures by programme × batch × category × quota, instalments." />
      <Tabs defaultValue="structures">
        <TabsList>
          <TabsTrigger value="structures">Structures</TabsTrigger>
          <TabsTrigger value="heads">Heads</TabsTrigger>
        </TabsList>
        <TabsContent value="structures"><StructuresTab /></TabsContent>
        <TabsContent value="heads"><HeadsTab /></TabsContent>
      </Tabs>
    </div>
  );
}

// ---- /admin/fees/discounts + fines ---------------------------------------------------------------------------------------
export function FeeDiscountsPage() {
  useTitle('Discounts & concessions');
  const { can } = usePermission();
  const list = useDiscounts();
  const pending = usePendingDiscounts(can('fees', 'concession') || can('fees', 'approve'));
  const [form, setForm] = useState({ code: '', name: '', discount_type: 'percentage', value: '', requires_approval: true });
  const [assign, setAssign] = useState({ discount_id: '', enrollment_id: '', reason: '' });
  const save = useFeesMutation(() => feesApi.saveDiscount({ ...form, value: Number(form.value) }));
  const doAssign = useFeesMutation(() => feesApi.assignDiscount(assign.discount_id, { enrollment_id: assign.enrollment_id, reason: assign.reason }));
  const decide = useFeesMutation(({ id, d }: { id: string; d: 'approve' | 'reject' }) => feesApi.decideDiscount(id, d));
  return (
    <div className="space-y-4">
      <PageHeader title="Discounts & concessions" description="Percentage / fixed discounts; assignments needing approval run the fees.concession workflow." />
      <div className="flex flex-wrap items-end gap-2">
        <Input className="w-28" placeholder="Code" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })} />
        <Input className="w-56" placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <Select className="w-36" value={form.discount_type} options={[{ value: 'percentage', label: 'Percentage' }, { value: 'fixed', label: 'Fixed (₹)' }]} onChange={(e) => setForm({ ...form, discount_type: e.target.value })} />
        <Input className="w-24" placeholder="Value" value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} />
        <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={form.requires_approval} onChange={(e) => setForm({ ...form, requires_approval: e.target.checked })} /> needs approval</label>
        <Button disabled={!form.code || !form.value} onClick={() => save.mutate(undefined, { onSuccess: () => toast.success('Discount saved'), onError: fail })}>Add</Button>
      </div>
      <SimpleTable head={['Code', 'Name', 'Type', 'Value', 'Approval']} rows={(list.data?.data ?? []).map((d) => [d.code, d.name, d.discount_type, d.discount_type === 'percentage' ? `${d.value}%` : `₹${d.value}`, d.requires_approval ? 'workflow' : 'direct'])} />
      <h3 className="font-medium">Assign to a student</h3>
      <div className="flex flex-wrap gap-2">
        <Select className="w-48" value={assign.discount_id} placeholder="Discount" options={(list.data?.data ?? []).map((d) => ({ value: d.id, label: d.code }))} onChange={(e) => setAssign({ ...assign, discount_id: e.target.value })} />
        <Input className="w-72" placeholder="Enrolment id" value={assign.enrollment_id} onChange={(e) => setAssign({ ...assign, enrollment_id: e.target.value })} />
        <Input className="w-72" placeholder="Reason" value={assign.reason} onChange={(e) => setAssign({ ...assign, reason: e.target.value })} />
        <Button disabled={!assign.discount_id || !assign.enrollment_id || !assign.reason} onClick={() => doAssign.mutate(undefined, { onSuccess: (r) => toast.success(`Assignment ${r.data.status}`), onError: fail })}>Assign</Button>
      </div>
      <h3 className="font-medium">Awaiting approval</h3>
      <SimpleTable
        head={['Discount', 'Reason', 'Requested', '', '']}
        rows={(pending.data?.data ?? []).map((a) => [
          a.discount_code,
          a.reason,
          new Date(a.created_at).toLocaleDateString(),
          <WorkflowPanel key="w" instanceId={a.workflow_instance_id} />,
          <div key="b" className="flex gap-1">
            <Button size="sm" onClick={() => decide.mutate({ id: a.id, d: 'approve' }, { onSuccess: () => toast.success('Approved'), onError: fail })}>Approve</Button>
            <Button size="sm" variant="outline" onClick={() => decide.mutate({ id: a.id, d: 'reject' }, { onError: fail })}>Reject</Button>
          </div>,
        ])}
        empty="No concessions waiting."
      />
    </div>
  );
}

export function FeeFinesPage() {
  useTitle('Fines');
  const list = useFines();
  const [rows, setRows] = useState<FineConfig[]>([]);
  useEffect(() => setRows(list.data?.data ?? []), [list.data]);
  const save = useFeesMutation(() => feesApi.saveFines(rows));
  return (
    <div className="max-w-3xl space-y-3">
      <PageHeader title="Fines" description="Late fee posting (nightly) after the grace days; other modules read their own rows." />
      {rows.map((r, i) => (
        <div key={r.id ?? i} className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">{r.applies_to}</Badge>
          <Select className="w-32" value={r.calc_type} options={['per_day', 'flat', 'slab'].map((v) => ({ value: v, label: v }))} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, calc_type: e.target.value } : x)))} />
          <label className="text-xs">₹<Input className="w-24" value={(r.amount_paise ?? 0) / 100} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, amount_paise: toPaise(e.target.value) } : x)))} /></label>
          <label className="text-xs">Grace days<Input className="w-20" type="number" value={r.grace_days} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, grace_days: Number(e.target.value) } : x)))} /></label>
          <label className="text-xs">Cap ₹<Input className="w-24" value={(r.max_paise ?? 0) / 100} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, max_paise: toPaise(e.target.value) || null } : x)))} /></label>
        </div>
      ))}
      <Button onClick={() => save.mutate(undefined, { onSuccess: () => toast.success('Saved'), onError: fail })}>Save</Button>
    </div>
  );
}

// ---- /admin/fees/invoices -------------------------------------------------------------------------------------------------
export function InvoiceDetail({ id, onClose }: { id: string | null; onClose: () => void }) {
  const inv = useInvoice(id ?? undefined).data?.data;
  const [reason, setReason] = useState('');
  const cancel = useFeesMutation(() => feesApi.cancelInvoice(id!, reason));
  const { can } = usePermission();
  return (
    <Modal open={!!id} onOpenChange={(o) => !o && onClose()} title={inv ? `Invoice ${inv.invoice_number}` : 'Invoice'} size="lg">
      {inv && (
        <div className="space-y-3 text-sm">
          <p>{inv.payer_name} {inv.registration_number && `(${inv.registration_number})`} · <InvBadge s={inv.status} /> {inv.source_type && <>· source <a className="underline" href={inv.source_link ?? '#'}>{inv.source_type}</a></>}</p>
          <SimpleTable head={['Item', 'Instalment', 'Due', 'Amount', 'GST']} rows={inv.items.map((i) => [i.description, i.instalment_no ?? '—', i.due_date ?? '—', inr(i.amount_paise), i.tax_paise ? inr(i.tax_paise) : '—'])} />
          <p>Total {inr(inv.total_paise)} − discount {inr(inv.discount_paise)} + tax {inr(inv.tax_paise)} + fine {inr(inv.fine_paise)} − paid {inr(inv.paid_paise)} = <strong>{inr(inv.balance_paise)}</strong>{inv.gst_number && ` · GSTIN ${inv.gst_number}`}</p>
          <SimpleTable head={['Receipt', 'Date', 'Mode', 'Amount', 'Status']} rows={inv.payments.map((p) => [p.receipt_number, p.payment_date, p.payment_mode, inr(p.amount_paise), <StatusBadge key="s" status={p.status} />])} empty="No payments." />
          {can('fees', 'manage') && inv.paid_paise === 0 && !['cancelled', 'refunded'].includes(inv.status) && (
            <div className="flex gap-2">
              <Input placeholder="Cancel reason" value={reason} onChange={(e) => setReason(e.target.value)} />
              <Button variant="destructive" disabled={!reason} onClick={() => cancel.mutate(undefined, { onSuccess: () => { toast.success('Invoice cancelled'); onClose(); }, onError: fail })}>Cancel invoice</Button>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}

export function FeeInvoicesPage() {
  useTitle('Invoices');
  const [scope, setScope] = useState<string>();
  const [f, setF] = useState({ status: '', q: '', overdue: false, page: 1 });
  const list = useInvoices({ scope, status: f.status || undefined, q: f.q || undefined, overdue: f.overdue || undefined, page: f.page, page_size: 25 });
  const [open, setOpen] = useState<string | null>(null);
  const page = list.data?.meta.pagination;
  return (
    <div className="space-y-3">
      <PageHeader title="Invoices" description="Every fee invoice with its source (structure, registration, condonation, application …)." />
      <div className="flex flex-wrap items-center gap-2">
        <ScopeTabs visibility={list.data?.meta.visibility} value={scope} onChange={setScope} />
        <Select className="w-36" value={f.status} placeholder="Any status" options={Object.keys(INVOICE_VARIANT).map((s) => ({ value: s, label: s }))} onChange={(e) => setF({ ...f, status: e.target.value, page: 1 })} />
        <Input className="w-64" placeholder="Invoice no. / reg. no. / name" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value, page: 1 })} />
        <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={f.overdue} onChange={(e) => setF({ ...f, overdue: e.target.checked, page: 1 })} /> overdue only</label>
      </div>
      <SimpleTable
        head={['Invoice', 'Payer', 'Source', 'Due', 'Total', 'Balance', 'Status', '']}
        rows={(list.data?.data ?? []).map((i: Invoice) => [
          i.invoice_number,
          `${i.payer_name ?? '—'} ${i.registration_number ? `(${i.registration_number})` : ''}`,
          i.source_type ?? '—',
          i.due_date ?? '—',
          inr(i.total_paise - i.discount_paise + i.tax_paise + i.fine_paise),
          inr(i.balance_paise),
          <InvBadge key="s" s={i.status} />,
          <Button key="o" size="sm" variant="outline" onClick={() => setOpen(i.id)}>Open</Button>,
        ])}
      />
      {page && (
        <div className="flex items-center gap-2 text-sm">
          <Button size="sm" variant="outline" disabled={f.page <= 1} onClick={() => setF({ ...f, page: f.page - 1 })}>Prev</Button>
          Page {page.page} / {page.total_pages} ({page.total})
          <Button size="sm" variant="outline" disabled={f.page >= page.total_pages} onClick={() => setF({ ...f, page: f.page + 1 })}>Next</Button>
        </div>
      )}
      <InvoiceDetail id={open} onClose={() => setOpen(null)} />
    </div>
  );
}

// ---- /admin/fees/collect --------------------------------------------------------------------------------------------------
function UpiPanel({ invoice, onDone }: { invoice: Invoice; onDone: () => void }) {
  const [qr, setQr] = useState<UpiQr | null>(null);
  const [status, setStatus] = useState('');
  useEffect(() => {
    if (!qr) return;
    const t = setInterval(() => {
      feesApi.upiStatus(qr.ref).then((r) => {
        setStatus(r.data.status);
        if (r.data.status === 'success') {
          clearInterval(t);
          toast.success(`UPI received — ${r.data.receipt_numbers.join(', ')}`);
          onDone();
        }
      }).catch(() => undefined);
    }, 3000);
    return () => clearInterval(t);
  }, [qr, onDone]);
  return (
    <div className="space-y-2 rounded border p-3">
      <Button size="sm" variant="outline" onClick={() => feesApi.upiQr({ invoice_id: invoice.id }).then((r) => { setQr(r.data); setStatus('pending'); }).catch(fail)}>
        <QrCode className="h-4 w-4" /> Show UPI QR for {inr(invoice.balance_paise)}
      </Button>
      {qr && (
        <div className="flex items-center gap-3">
          {qr.qr_png ? <img src={qr.qr_png} alt="UPI QR" className="h-40 w-40" /> : <code className="text-xs">{qr.upi_uri}</code>}
          <div className="text-sm">
            <p>Ref {qr.ref} · {qr.vpa}</p>
            <p>Status: <StatusBadge status={status} /></p>
            {import.meta.env.DEV && <Button size="sm" variant="ghost" onClick={() => feesApi.devUpiCallback(qr.ref).catch(fail)}>Simulate payment (dev)</Button>}
          </div>
        </div>
      )}
    </div>
  );
}

export function FeeCollectPage() {
  useTitle('Collect fees');
  const [q, setQ] = useState('');
  const [search, setSearch] = useState('');
  const list = useInvoices({ q: search || undefined, page_size: 50, scope: 'all' }, !!search);
  const open = (list.data?.data ?? []).filter((i) => ['pending', 'partial', 'overdue'].includes(i.status));
  const [alloc, setAlloc] = useState<Record<string, string>>({});
  const [mode, setMode] = useState<string>('cash');
  const [ref, setRef] = useState({ reference: '', utr: '', bank: '', cheque_no: '', cheque_date: localDate(), counter: 'main' });
  const [receipt, setReceipt] = useState<{ numbers: string[]; payments: Payment[] } | null>(null);
  const total = Object.values(alloc).reduce((a, v) => a + toPaise(v), 0);
  const collect = useFeesMutation(() =>
    feesApi.collect({
      allocation: Object.entries(alloc).filter(([, v]) => toPaise(v) > 0).map(([invoice_id, v]) => ({ invoice_id, amount_paise: toPaise(v) })),
      amount_paise: total,
      mode,
      reference: ref.reference || null,
      utr: ref.utr || null,
      bank: ref.bank || null,
      cheque: ['cheque', 'dd'].includes(mode) ? { no: ref.cheque_no, date: ref.cheque_date, bank: ref.bank } : null,
      counter: ref.counter,
    }),
  );
  return (
    <div className="space-y-4">
      <PageHeader title="Collect fees" description="Search a student → allocate against open invoices (oldest first) → collect → print." />
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); setSearch(q); setAlloc({}); }}>
        <Input className="w-80" placeholder="Registration no. / name / invoice no." value={q} onChange={(e) => setQ(e.target.value)} />
        <Button type="submit"><Search className="h-4 w-4" /> Search</Button>
      </form>
      {search && (
        <SimpleTable
          head={['Invoice', 'Student', 'Due', 'Balance', 'Status', 'Collect ₹']}
          rows={open.map((i) => [
            i.invoice_number,
            `${i.payer_name ?? ''} (${i.registration_number ?? ''})`,
            i.due_date ?? '—',
            inr(i.balance_paise),
            <InvBadge key="s" s={i.status} />,
            <div key="a" className="flex gap-1">
              <Input className="w-28" value={alloc[i.id] ?? ''} onChange={(e) => setAlloc({ ...alloc, [i.id]: e.target.value })} />
              <Button size="sm" variant="ghost" onClick={() => setAlloc({ ...alloc, [i.id]: String(i.balance_paise / 100) })}>Full</Button>
            </div>,
          ])}
          empty="No open invoices for this search."
        />
      )}
      {open[0] && <UpiPanel invoice={open[0]} onDone={() => list.refetch()} />}
      <div className="flex flex-wrap items-end gap-2">
        <label className="text-xs">Mode<Select className="w-32" value={mode} options={PAYMENT_MODES.map((m) => ({ value: m, label: m }))} onChange={(e) => setMode(e.target.value)} /></label>
        {['upi', 'card', 'neft', 'challan'].includes(mode) && <Input className="w-48" placeholder="Reference / UTR" value={ref.utr} onChange={(e) => setRef({ ...ref, utr: e.target.value, reference: e.target.value })} />}
        {['cheque', 'dd'].includes(mode) && (
          <>
            <Input className="w-32" placeholder="Cheque / DD no." value={ref.cheque_no} onChange={(e) => setRef({ ...ref, cheque_no: e.target.value })} />
            <Input className="w-40" type="date" value={ref.cheque_date} onChange={(e) => setRef({ ...ref, cheque_date: e.target.value })} />
          </>
        )}
        {['cheque', 'dd', 'neft'].includes(mode) && <Input className="w-40" placeholder="Bank" value={ref.bank} onChange={(e) => setRef({ ...ref, bank: e.target.value })} />}
        <Input className="w-24" placeholder="Counter" value={ref.counter} onChange={(e) => setRef({ ...ref, counter: e.target.value })} />
        <Button disabled={total <= 0} onClick={() => collect.mutate(undefined, { onSuccess: (r) => { setReceipt({ numbers: r.data.receipt_numbers, payments: r.data.payments }); setAlloc({}); toast.success(`Receipt ${r.data.receipt_numbers.join(', ')}`); }, onError: fail })}>
          <Banknote className="h-4 w-4" /> Collect {inr(total)}
        </Button>
      </div>
      <Modal open={!!receipt} onOpenChange={(o) => !o && setReceipt(null)} title={`Receipt ${receipt?.numbers.join(', ') ?? ''}`}>
        <div className="space-y-2">
          {receipt?.payments.map((p) => (
            <div key={p.id} className="flex items-center justify-between text-sm">
              <span>{p.receipt_number} · {inr(p.amount_paise)} · {p.payment_mode}</span>
              <span className="flex gap-1">
                <Button size="sm" variant="outline" onClick={() => feesApi.receiptPdf(p.id).then((b) => openBlob(b)).catch(fail)}><Printer className="h-3 w-3" /> PDF</Button>
                <Button size="sm" variant="outline" onClick={() => feesApi.thermal(p.id).then((r) => { const w = window.open('', '_blank'); w?.document.write(`<pre>${r.data.text}</pre>`); }).catch(fail)}>Thermal</Button>
              </span>
            </div>
          ))}
        </div>
      </Modal>
    </div>
  );
}

// ---- /admin/fees/payments -------------------------------------------------------------------------------------------------
export function FeePaymentsPage() {
  useTitle('Payments');
  const { can } = usePermission();
  const [f, setF] = useState({ date: '', mode: '', status: '' });
  const list = usePayments({ date: f.date || undefined, mode: f.mode || undefined, status: f.status || undefined, page_size: 100 });
  const queue = useCancelQueue(can('fees', 'cancel_receipt') || can('fees', 'approve'));
  const [action, setAction] = useState<{ p: Payment; kind: 'cancel' | 'bounce' } | null>(null);
  const [text, setText] = useState({ reason: '', charges: '' });
  const go = useFeesMutation(() => (action!.kind === 'cancel' ? feesApi.cancelRequest(action!.p.id, text.reason) : feesApi.bounce(action!.p.id, { reason: text.reason, bank_charges_paise: toPaise(text.charges) })));
  const decide = useFeesMutation(({ id, d }: { id: string; d: 'approve' | 'reject' }) => feesApi.decideCancel(id, d));
  return (
    <div className="space-y-3">
      <PageHeader title="Payments" description="Receipt register; cancellations go to the principal (fees.receipt_cancel); cheque bounces reopen the invoice." />
      <div className="flex flex-wrap gap-2">
        <Input type="date" className="w-40" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} />
        <Select className="w-32" value={f.mode} placeholder="Any mode" options={[...PAYMENT_MODES, 'gateway', 'scholarship_credit', 'adjustment'].map((m) => ({ value: m, label: m }))} onChange={(e) => setF({ ...f, mode: e.target.value })} />
        <Select className="w-32" value={f.status} placeholder="Any status" options={['success', 'reconciled', 'initiated', 'failed', 'bounced', 'cancelled'].map((m) => ({ value: m, label: m }))} onChange={(e) => setF({ ...f, status: e.target.value })} />
      </div>
      <SimpleTable
        head={['Receipt', 'Invoice', 'Payer', 'Date', 'Mode', 'Amount', 'Status', '']}
        rows={(list.data?.data ?? []).map((p) => [
          p.receipt_number,
          p.invoice_number,
          p.payer_name,
          p.payment_date,
          p.payment_mode,
          inr(p.amount_paise),
          <StatusBadge key="s" status={p.status} />,
          <div key="a" className="flex gap-1">
            <Button size="sm" variant="ghost" onClick={() => feesApi.receiptPdf(p.id).then((b) => openBlob(b)).catch(fail)}><Printer className="h-3 w-3" /></Button>
            {can('fees', 'cancel_receipt') && ['success', 'reconciled'].includes(p.status) && <Button size="sm" variant="outline" onClick={() => setAction({ p, kind: 'cancel' })}>Cancel</Button>}
            {can('fees', 'cancel_receipt') && ['cheque', 'dd'].includes(p.payment_mode) && ['success', 'reconciled'].includes(p.status) && <Button size="sm" variant="outline" onClick={() => setAction({ p, kind: 'bounce' })}>Bounce</Button>}
          </div>,
        ])}
      />
      {(queue.data?.data ?? []).length > 0 && (
        <>
          <h3 className="font-medium">Cancellation requests</h3>
          <SimpleTable
            head={['Receipt', 'Amount', 'Reason', 'Workflow', '']}
            rows={(queue.data?.data ?? []).map((p) => [
              p.receipt_number,
              inr(p.amount_paise),
              p.cancel_reason,
              <WorkflowPanel key="w" instanceId={p.cancel_workflow_instance_id} />,
              <div key="b" className="flex gap-1">
                <Button size="sm" onClick={() => decide.mutate({ id: p.id, d: 'approve' }, { onSuccess: () => toast.success('Approved'), onError: fail })}>Approve</Button>
                <Button size="sm" variant="outline" onClick={() => decide.mutate({ id: p.id, d: 'reject' }, { onError: fail })}>Reject</Button>
              </div>,
            ])}
          />
        </>
      )}
      <Modal open={!!action} onOpenChange={(o) => !o && setAction(null)} title={action?.kind === 'cancel' ? `Request cancellation of ${action?.p.receipt_number}` : `Cheque bounce ${action?.p.receipt_number ?? ''}`}
        footer={<Button disabled={!text.reason} onClick={() => go.mutate(undefined, { onSuccess: () => { toast.success('Done'); setAction(null); }, onError: fail })}>Submit</Button>}>
        <Textarea placeholder="Reason" value={text.reason} onChange={(e) => setText({ ...text, reason: e.target.value })} />
        {action?.kind === 'bounce' && <Input className="mt-2" placeholder="Bank charges ₹" value={text.charges} onChange={(e) => setText({ ...text, charges: e.target.value })} />}
      </Modal>
    </div>
  );
}

export function FeeOnlinePage() {
  useTitle('Gateway orders');
  const list = usePayments({ mode: 'gateway', page_size: 100 });
  return (
    <div className="space-y-3">
      <PageHeader title="Gateway orders" description="Online orders (initiated rows are polled every 10 minutes)." />
      <SimpleTable head={['Order', 'Invoice', 'Payer', 'Amount', 'Status', 'Receipt']} rows={(list.data?.data ?? []).map((p) => [p.gateway_order_id, p.invoice_number, p.payer_name, inr(p.amount_paise), <StatusBadge key="s" status={p.status} />, p.status === 'success' ? p.receipt_number : '—'])} />
    </div>
  );
}

// ---- /admin/fees/reconcile ------------------------------------------------------------------------------------------------
export function FeeReconcilePage() {
  useTitle('Reconciliation');
  const [status, setStatus] = useState('unmatched');
  const list = useReconcile({ status });
  const [file, setFile] = useState<File | null>(null);
  const upload = useFeesMutation(() => feesApi.reconcileUpload(file!));
  const match = useFeesMutation(({ id, payment_id }: { id: string; payment_id: string }) => feesApi.match(id, { payment_id }));
  const ignore = useFeesMutation((id: string) => feesApi.ignore(id));
  return (
    <div className="space-y-3">
      <PageHeader title="Reconciliation" description="Upload a bank statement CSV (utr, amount, date, narration) → auto-match by UTR + amount → confirm." />
      <div className="flex flex-wrap items-center gap-2">
        <input type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <Button disabled={!file} onClick={() => upload.mutate(undefined, { onSuccess: (r) => toast.success(`${r.data.rows} rows queued — refresh in a moment`), onError: fail })}><Upload className="h-4 w-4" /> Upload</Button>
        <Select className="w-36" value={status} options={['unmatched', 'matched', 'ignored'].map((s) => ({ value: s, label: s }))} onChange={(e) => setStatus(e.target.value)} />
        <Button variant="ghost" onClick={() => list.refetch()}><RefreshCw className="h-4 w-4" /></Button>
      </div>
      <SimpleTable
        head={['Date', 'UTR', 'Amount', 'Narration', 'Proposed', '']}
        rows={(list.data?.data ?? []).map((r) => [
          r.statement_date ?? '—',
          r.utr ?? '—',
          inr(r.amount_paise),
          r.payer_hint ?? '',
          r.proposed_receipt ? <Badge key="p" variant="info">{r.proposed_receipt}</Badge> : r.status === 'matched' ? 'matched' : '—',
          r.status === 'unmatched' && (
            <div key="a" className="flex gap-1">
              {r.proposed_payment_id && <Button size="sm" onClick={() => match.mutate({ id: r.id, payment_id: r.proposed_payment_id! }, { onSuccess: () => toast.success('Reconciled'), onError: fail })}>Confirm</Button>}
              <Button size="sm" variant="outline" onClick={() => ignore.mutate(r.id, { onError: fail })}>Ignore</Button>
            </div>
          ),
        ])}
        empty="Nothing here."
      />
    </div>
  );
}

// ---- /admin/fees/day-book -------------------------------------------------------------------------------------------------
export function FeeDayBookPage() {
  useTitle('Day-book');
  const [date, setDate] = useState(localDate());
  const book = useDayBook({ date });
  const close = useFeesMutation(() => feesApi.closeDay({ date }));
  const d = book.data?.data;
  return (
    <div className="space-y-3">
      <PageHeader title="Day-book" description="Collections per counter / collector by mode; close the day and record the deposit." />
      <div className="flex flex-wrap gap-2">
        <Input type="date" className="w-40" value={date} onChange={(e) => setDate(e.target.value)} />
        <Button onClick={() => close.mutate(undefined, { onSuccess: () => toast.success('Day closed'), onError: fail })}>Close & deposit</Button>
        <Button variant="outline" onClick={() => feesApi.dayBookCsv({ date_from: date, date_to: date }).then((b) => openBlob(b, `day-book-${date}.csv`)).catch(fail)}><Download className="h-4 w-4" /> CSV</Button>
      </div>
      <SimpleTable head={['Counter', 'Collector', 'Receipts', 'Cash', 'Digital', 'Cheque', 'Deposited', 'Status']} rows={(d?.rows ?? []).map((r) => [r.counter ?? '—', r.collector_name ?? '—', r.receipts, inr(r.cash_paise), inr(r.digital_paise), inr(r.cheque_paise), inr(r.deposited_paise), <StatusBadge key="s" status={r.status} />])} empty="No collections on this day." />
      <p className="text-sm">Total {inr(d?.total_paise)} · {Object.entries(d?.by_mode ?? {}).map(([m, v]) => `${m} ${inr(v)}`).join(' · ')}</p>
    </div>
  );
}

// ---- /admin/fees/refunds --------------------------------------------------------------------------------------------------
export function FeeRefundsPage() {
  useTitle('Refunds');
  const [status, setStatus] = useState('');
  const list = useRefunds({ status: status || undefined });
  const [proc, setProc] = useState<string | null>(null);
  const [form, setForm] = useState({ refund_mode: 'neft', reference_no: '' });
  const decide = useFeesMutation(({ id, d }: { id: string; d: 'approve' | 'reject' }) => feesApi.decideRefund(id, d));
  const process = useFeesMutation(() => feesApi.processRefund(proc!, form));
  return (
    <div className="space-y-3">
      <PageHeader title="Refunds" description="Requests run fees.refund (accountant → principal); approved refunds are processed with a reference." />
      <Select className="w-40" value={status} placeholder="Any status" options={['requested', 'approved', 'processed', 'rejected'].map((s) => ({ value: s, label: s }))} onChange={(e) => setStatus(e.target.value)} />
      <SimpleTable
        head={['Invoice', 'Payer', 'Amount', 'Reason', 'Status', 'Workflow', '']}
        rows={(list.data?.data ?? []).map((r) => [
          r.invoice_number,
          r.payer_name,
          inr(r.amount_paise),
          r.reason,
          <StatusBadge key="s" status={r.status} />,
          <WorkflowPanel key="w" instanceId={r.workflow_instance_id} />,
          <div key="a" className="flex gap-1">
            {r.status === 'requested' && r.can_act && (
              <>
                <Button size="sm" onClick={() => decide.mutate({ id: r.id, d: 'approve' }, { onSuccess: () => toast.success('Approved'), onError: fail })}>Approve</Button>
                <Button size="sm" variant="outline" onClick={() => decide.mutate({ id: r.id, d: 'reject' }, { onError: fail })}>Reject</Button>
              </>
            )}
            {r.status === 'approved' && <Button size="sm" onClick={() => setProc(r.id)}>Process</Button>}
          </div>,
        ])}
      />
      <Modal open={!!proc} onOpenChange={(o) => !o && setProc(null)} title="Process refund"
        footer={<Button disabled={!form.reference_no} onClick={() => process.mutate(undefined, { onSuccess: () => { toast.success('Processed'); setProc(null); }, onError: fail })}>Process</Button>}>
        <Select value={form.refund_mode} options={['neft', 'cheque', 'cash', 'upi', 'gateway', 'adjustment'].map((m) => ({ value: m, label: m }))} onChange={(e) => setForm({ ...form, refund_mode: e.target.value })} />
        <Input className="mt-2" placeholder="Reference" value={form.reference_no} onChange={(e) => setForm({ ...form, reference_no: e.target.value })} />
      </Modal>
    </div>
  );
}

// ---- /admin/fees/scholarships ---------------------------------------------------------------------------------------------
export function FeeScholarshipsPage() {
  useTitle('Scholarships');
  const { can } = usePermission();
  const schemes = useSchemes();
  const [status, setStatus] = useState('');
  const apps = useApplications({ status: status || undefined });
  const [form, setForm] = useState({ name: '', provider: 'institution', amount: '', income_cap: '', min_cgpa: '', categories: '' });
  const save = useFeesMutation(() =>
    scholarshipsApi.saveScheme({
      name: form.name,
      provider: form.provider,
      amount_paise: toPaise(form.amount),
      eligibility_rules: {
        ...(form.income_cap ? { income_cap_paise: toPaise(form.income_cap) } : {}),
        ...(form.min_cgpa ? { min_cgpa: Number(form.min_cgpa) } : {}),
        ...(form.categories ? { categories: form.categories.split(',').map((c) => c.trim()) } : {}),
      },
    }),
  );
  const act = useFeesMutation(({ id, a }: { id: string; a: 'verify' | 'recommend' | 'sanction' | 'reject' }) => scholarshipsApi.act(id, a, {}));
  const disburse = useFeesMutation((id: string) => scholarshipsApi.disburse(id, { mode: 'fee_credit' }));
  return (
    <div className="space-y-4">
      <PageHeader title="Scholarships" description="Schemes with eligibility rules; applied → verified → recommended (HOD) → sanctioned → disbursed." />
      {(can('scholarships', 'disburse') || can('scholarships', 'manage')) && (
        <div className="flex flex-wrap gap-2">
          <Input className="w-64" placeholder="Scheme name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <Select className="w-36" value={form.provider} options={['central_govt', 'state_govt', 'institution', 'private', 'alumni'].map((p) => ({ value: p, label: p }))} onChange={(e) => setForm({ ...form, provider: e.target.value })} />
          <Input className="w-24" placeholder="Amount ₹" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
          <Input className="w-32" placeholder="Income cap ₹" value={form.income_cap} onChange={(e) => setForm({ ...form, income_cap: e.target.value })} />
          <Input className="w-24" placeholder="Min CGPA" value={form.min_cgpa} onChange={(e) => setForm({ ...form, min_cgpa: e.target.value })} />
          <Input className="w-36" placeholder="Categories (SC,ST)" value={form.categories} onChange={(e) => setForm({ ...form, categories: e.target.value })} />
          <Button disabled={!form.name} onClick={() => save.mutate(undefined, { onSuccess: () => toast.success('Scheme saved'), onError: fail })}>Add scheme</Button>
        </div>
      )}
      <SimpleTable head={['Scheme', 'Provider', 'Amount', 'Rules', 'Applications']} rows={(schemes.data?.data ?? []).map((s) => [s.name, s.provider, inr(s.amount_paise), JSON.stringify(s.eligibility_rules ?? {}), s.applications])} />
      <Select className="w-40" value={status} placeholder="Any status" options={['applied', 'verified', 'recommended', 'sanctioned', 'disbursed', 'rejected'].map((s) => ({ value: s, label: s }))} onChange={(e) => setStatus(e.target.value)} />
      <SimpleTable
        head={['Student', 'Scheme', 'Income', 'Status', 'Sanctioned', '']}
        rows={(apps.data?.data ?? []).map((a) => [
          `${a.student_name ?? ''} (${a.registration_number ?? ''})`,
          a.scholarship_name,
          inr(a.income_paise),
          <StatusBadge key="s" status={a.status} />,
          a.sanctioned_paise ? inr(a.sanctioned_paise) : '—',
          <div key="b" className="flex gap-1">
            {a.status === 'applied' && can('scholarships', 'verify') && <Button size="sm" onClick={() => act.mutate({ id: a.id, a: 'verify' }, { onError: fail })}>Verify</Button>}
            {['applied', 'verified'].includes(a.status) && can('scholarships', 'approve') && <Button size="sm" onClick={() => act.mutate({ id: a.id, a: 'recommend' }, { onError: fail })}>Recommend</Button>}
            {a.status === 'recommended' && can('scholarships', 'sanction') && <Button size="sm" onClick={() => act.mutate({ id: a.id, a: 'sanction' }, { onError: fail })}>Sanction</Button>}
            {a.status === 'sanctioned' && can('scholarships', 'disburse') && <Button size="sm" onClick={() => disburse.mutate(a.id, { onSuccess: () => toast.success('Credited to fees'), onError: fail })}>Disburse (fee credit)</Button>}
            {['applied', 'verified', 'recommended'].includes(a.status) && <Button size="sm" variant="outline" onClick={() => act.mutate({ id: a.id, a: 'reject' }, { onError: fail })}>Reject</Button>}
          </div>,
        ])}
      />
    </div>
  );
}

// ---- /admin/fees/no-dues --------------------------------------------------------------------------------------------------
function SignoffRow({ r }: { r: NoDues }) {
  const [dues, setDues] = useState('');
  const sign = useFeesMutation(({ key, status }: { key: string; status: string }) => noDuesApi.signoff(r.id, { department_key: key, status, dues_paise: toPaise(dues), remarks: status === 'dues_pending' ? 'Dues pending' : null }));
  return (
    <div className="flex flex-wrap gap-2">
      {r.signoffs.map((s) => (
        <div key={s.id} className="flex items-center gap-1 rounded border px-2 py-1 text-xs">
          {s.department_key} <StatusBadge status={s.status} /> {s.dues_paise > 0 && inr(s.dues_paise)}
          {s.can_sign && (
            <>
              <Button size="sm" variant="ghost" onClick={() => sign.mutate({ key: s.department_key, status: 'cleared' }, { onSuccess: () => toast.success('Cleared'), onError: fail })}>Clear</Button>
              <Input className="h-7 w-20" placeholder="₹ dues" value={dues} onChange={(e) => setDues(e.target.value)} />
              <Button size="sm" variant="ghost" onClick={() => sign.mutate({ key: s.department_key, status: 'dues_pending' }, { onError: fail })}>Dues</Button>
            </>
          )}
        </div>
      ))}
    </div>
  );
}

export function FeeNoDuesPage() {
  useTitle('No-dues');
  const { tab } = useParams();
  const [key, setKey] = useState<string>(tab ?? '');
  const [status, setStatus] = useState('');
  const list = useNoDues({ scope: key ? undefined : 'department', department_key: key || undefined, status: status || undefined });
  return (
    <div className="space-y-3">
      <PageHeader title="No-dues" description="Parallel sign-offs; each office signs only its own department (librarian → library, HOD → department / lab, warden → hostel, accounts → accounts)." />
      <div className="flex flex-wrap gap-2">
        <Select className="w-40" value={key} placeholder="My offices" options={DEPARTMENT_KEYS.map((k) => ({ value: k, label: k }))} onChange={(e) => setKey(e.target.value)} />
        <Select className="w-40" value={status} placeholder="Any status" options={['in_progress', 'blocked', 'cleared'].map((s) => ({ value: s, label: s }))} onChange={(e) => setStatus(e.target.value)} />
      </div>
      <SimpleTable
        head={['Student', 'Purpose', 'Status', 'Sign-offs', '']}
        rows={(list.data?.data ?? []).map((r) => [
          `${r.student_name ?? ''} (${r.registration_number ?? ''})`,
          r.purpose,
          <StatusBadge key="s" status={r.status} />,
          <SignoffRow key="o" r={r} />,
          r.status === 'cleared' && <Button key="c" size="sm" variant="outline" onClick={() => noDuesApi.certificate(r.id).then((b) => openBlob(b)).catch(fail)}>Certificate</Button>,
        ])}
        empty="No requests for your offices."
      />
    </div>
  );
}

// ---- /admin/fees/reports --------------------------------------------------------------------------------------------------
export function FeeReportsPage() {
  useTitle('Fee reports');
  const [name, setName] = useState('collection');
  const [p, setP] = useState({ group_by: '', date_from: '', date_to: '', batch_year: '' });
  const params = { group_by: p.group_by || undefined, date_from: p.date_from || undefined, date_to: p.date_to || undefined, batch_year: p.batch_year || undefined };
  const rep = useReport(name, params);
  const [exp, setExp] = useState({ date_from: localDate(), date_to: localDate(), format: 'tally_xml' });
  return (
    <div className="space-y-3">
      <PageHeader title="Fee reports" description="Collection, dues, defaulters, scholarships, refunds; CSV and accounting exports run as jobs." />
      <div className="flex flex-wrap gap-2">
        <Select className="w-40" value={name} options={['collection', 'dues', 'defaulters', 'scholarships', 'refunds'].map((r) => ({ value: r, label: r }))} onChange={(e) => setName(e.target.value)} />
        {name === 'collection' && <Select className="w-32" value={p.group_by} placeholder="by mode" options={['mode', 'head', 'college', 'day'].map((g) => ({ value: g, label: `by ${g}` }))} onChange={(e) => setP({ ...p, group_by: e.target.value })} />}
        {name === 'dues' && <Select className="w-36" value={p.group_by} placeholder="by programme" options={['program', 'batch', 'category'].map((g) => ({ value: g, label: `by ${g}` }))} onChange={(e) => setP({ ...p, group_by: e.target.value })} />}
        {name === 'defaulters' && <Input className="w-28" placeholder="Batch year" value={p.batch_year} onChange={(e) => setP({ ...p, batch_year: e.target.value })} />}
        <Input type="date" className="w-40" value={p.date_from} onChange={(e) => setP({ ...p, date_from: e.target.value })} />
        <Input type="date" className="w-40" value={p.date_to} onChange={(e) => setP({ ...p, date_to: e.target.value })} />
        <Button variant="outline" onClick={() => feesApi.reportExport(name, params).then(() => toast.success('Export queued — see Jobs')).catch(fail)}><Download className="h-4 w-4" /> CSV</Button>
      </div>
      <SimpleTable head={['Key', 'Label', 'Count', 'Amount']} rows={(rep.data?.data.rows ?? []).map((r) => [r.key, r.label ?? '', r.count, inr(r.amount_paise)])} />
      <p className="text-sm">Total {inr(rep.data?.data.total_paise)}</p>
      <h3 className="font-medium">Accounting export</h3>
      <div className="flex flex-wrap gap-2">
        <Input type="date" className="w-40" value={exp.date_from} onChange={(e) => setExp({ ...exp, date_from: e.target.value })} />
        <Input type="date" className="w-40" value={exp.date_to} onChange={(e) => setExp({ ...exp, date_to: e.target.value })} />
        <Select className="w-32" value={exp.format} options={[{ value: 'tally_xml', label: 'Tally XML' }, { value: 'csv', label: 'CSV' }]} onChange={(e) => setExp({ ...exp, format: e.target.value })} />
        <Button variant="outline" onClick={() => feesApi.accountingExport(exp).then(() => toast.success('Export queued — see Jobs')).catch(fail)}>Export vouchers</Button>
      </div>
    </div>
  );
}
