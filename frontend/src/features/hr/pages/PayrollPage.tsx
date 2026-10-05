import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { ColumnDef } from '@tanstack/react-table';
import { CheckCheck, FileDown, Play } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { DataTable } from '@/components/shared/DataTable';
import { FormField } from '@/components/shared/FormField';
import { PageHeader } from '@/components/shared/PageHeader';
import { ScopeTabs } from '@/components/shared/ScopeTabs';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Select } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs';
import { toast } from '@/components/ui/Toaster';
import { useFeature } from '@/hooks/useFeature';
import { usePermission } from '@/hooks/usePermission';
import { useColleges } from '@/features/institution/hooks';
import { hrApi } from '../api';
import { SimpleTable } from '../components/shared';
import { downloadBlob } from '../download';
import { useHrMutation, usePayroll, useStaffList } from '../hooks';
import { MONTHS, inr, label, num, type Payroll } from '../types';

const now = new Date();

/** /admin/hr/payroll — runs (generate wizard → job), approve / mark paid / payslip, components, registers, Form 16. */
export default function PayrollPage() {
  const { can } = usePermission();
  const statutoryOn = useFeature('hr.statutory_payroll');
  const [period, setPeriod] = useState({ month: now.getMonth() + 1, year: now.getFullYear() });
  const [scope, setScope] = useState<string | undefined>();
  const [status, setStatus] = useState<string | undefined>();
  const [page, setPage] = useState(1);
  const runs = usePayroll({ ...period, scope, status, page, page_size: 50 });
  const [wizard, setWizard] = useState<0 | 1 | 2>(0);
  const [genScope, setGenScope] = useState<{ college_id: string }>({ college_id: '' });
  const colleges = useColleges({ page_size: 50 }, wizard > 0);
  const [detail, setDetail] = useState<Payroll | null>(null);
  const [payRef, setPayRef] = useState('');
  const [registerKind, setRegisterKind] = useState('pf');
  const register = useQuery({ queryKey: ['payroll', 'register', registerKind, period], queryFn: () => hrApi.register(registerKind, period.month, period.year), enabled: statutoryOn && can('payroll', 'statutory') });
  const components = useQuery({ queryKey: ['payroll', 'components'], queryFn: hrApi.components });
  const [f16Staff, setF16Staff] = useState('');
  const staff = useStaffList({ scope: 'all', page_size: 200 }, statutoryOn);
  const form16 = useQuery({ queryKey: ['payroll', 'f16', f16Staff], queryFn: () => hrApi.form16(period.month >= 4 ? period.year : period.year - 1, f16Staff), enabled: !!f16Staff });
  const one = useQuery({ queryKey: ['payroll', 'one', detail?.id], queryFn: () => hrApi.payrollOne(detail!.id), enabled: !!detail });
  const generate = useHrMutation(() => hrApi.generate({ ...period, college_id: genScope.college_id || undefined }), ['payroll', 'jobs']);
  const approve = useHrMutation((id: string) => hrApi.approvePayroll(id), ['payroll']);
  const approveAll = useHrMutation((ids: string[]) => hrApi.approveMany(ids), ['payroll']);
  const pay = useHrMutation(({ id, ref }: { id: string; ref: string }) => hrApi.markPaid(id, ref), ['payroll', 'jobs']);
  const drafts = (runs.data?.data ?? []).filter((r) => r.status === 'draft');
  const columns = useMemo<ColumnDef<Payroll, unknown>[]>(
    () => [
      { id: 'emp', header: 'Staff', enableSorting: false, cell: ({ row }) => `${row.original.employee_id} · ${row.original.staff_name}` },
      { id: 'dept', header: 'Dept', enableSorting: false, cell: ({ row }) => row.original.department_code ?? '—' },
      { accessorKey: 'paid_days', header: 'Paid days', cell: ({ getValue }) => num(getValue() as string) },
      { accessorKey: 'lop_days', header: 'LOP', cell: ({ getValue }) => num(getValue() as string) },
      { accessorKey: 'gross_paise', header: 'Gross', cell: ({ getValue }) => inr(getValue() as number) },
      { accessorKey: 'deductions_paise', header: 'Deductions', cell: ({ getValue }) => inr(getValue() as number) },
      { accessorKey: 'net_paise', header: 'Net', cell: ({ getValue }) => <b>{inr(getValue() as number)}</b> },
      { accessorKey: 'status', header: 'Status', cell: ({ getValue }) => <StatusBadge status={String(getValue())} /> },
    ],
    [],
  );
  const years = [now.getFullYear() - 1, now.getFullYear(), now.getFullYear() + 1];
  return (
    <div className="space-y-4">
      <PageHeader
        title="Payroll"
        description="Monthly runs with statutory deductions (PF / ESI / PT / TDS / LWF), LOP from attendance and loan EMIs."
        actions={
          <div className="flex gap-2">
            {can('payroll', 'approve') && drafts.length > 0 && (
              <Button variant="outline" onClick={() => approveAll.mutate(drafts.map((d) => d.id), { onSuccess: (r) => toast.success(`${r.data.succeeded.length} approved`), onError: (e) => toast.error(getApiError(e)) })}>
                <CheckCheck className="h-4 w-4" /> Approve {drafts.length} draft(s)
              </Button>
            )}
            {can('payroll', 'mark_paid') && (
              <Button variant="outline" onClick={async () => { try { downloadBlob(await hrApi.bankAdvice(period.month, period.year), `bank-advice-${period.year}-${period.month}.csv`); } catch (e) { toast.error(getApiError(e)); } }}>
                <FileDown className="h-4 w-4" /> Bank advice
              </Button>
            )}
            {can('payroll', 'generate') && <Button onClick={() => setWizard(1)}><Play className="h-4 w-4" /> Generate</Button>}
          </div>
        }
      />
      <div className="flex flex-wrap items-center gap-2">
        <Select aria-label="Month" className="w-28" options={MONTHS.map((mm, i) => ({ value: String(i + 1), label: mm }))} value={String(period.month)} onChange={(e) => setPeriod({ ...period, month: Number(e.target.value) })} />
        <Select aria-label="Year" className="w-28" options={years.map((yy) => ({ value: String(yy), label: String(yy) }))} value={String(period.year)} onChange={(e) => setPeriod({ ...period, year: Number(e.target.value) })} />
        <ScopeTabs visibility={runs.data?.meta.visibility} value={scope} onChange={setScope} labels={{ department: 'Team' }} />
        <Select aria-label="Status" className="w-32" placeholder="All statuses" options={['draft', 'approved', 'paid'].map((s) => ({ value: s, label: s }))} value={status ?? ''} onChange={(e) => setStatus(e.target.value || undefined)} />
      </div>
      <Tabs defaultValue="runs">
        <TabsList>
          <TabsTrigger value="runs">Runs</TabsTrigger>
          <TabsTrigger value="components">Components</TabsTrigger>
          {statutoryOn && can('payroll', 'statutory') && <TabsTrigger value="registers">Registers</TabsTrigger>}
          {statutoryOn && can('payroll', 'statutory') && <TabsTrigger value="form16">Form 16</TabsTrigger>}
        </TabsList>
        <TabsContent value="runs">
          <DataTable columns={columns} data={runs.data?.data ?? []} isLoading={runs.isLoading} pagination={runs.data?.meta.pagination} onPageChange={setPage} onRowClick={setDetail} rowKey={(r) => r.id} emptyTitle="No runs for this month" emptyDescription="Use Generate to compute the month." />
        </TabsContent>
        <TabsContent value="components">
          <SimpleTable head={['Code', 'Name', 'Type', 'Calculation', 'Statutory', 'Taxable']} rows={(components.data?.data ?? []).map((c) => [c.code, c.name, label(c.component_type), `${c.calc_type}${c.formula ? ` ${JSON.stringify(c.formula)}` : ''}`, c.statutory_kind ?? '—', c.is_taxable ? 'yes' : 'no'])} />
        </TabsContent>
        <TabsContent value="registers" className="space-y-2">
          <Select aria-label="Register" className="w-40" options={[['pf', 'PF (ECR)'], ['esi', 'ESI'], ['pt', 'Professional tax'], ['tds', 'TDS (24Q)']].map(([v, l]) => ({ value: v, label: l }))} value={registerKind} onChange={(e) => setRegisterKind(e.target.value)} />
          <SimpleTable
            head={register.data?.data.columns ?? []}
            rows={(register.data?.data.rows ?? []).map((r) => (register.data?.data.columns ?? []).map((c) => (typeof r[c] === 'number' && c !== 'ncp_days' && c !== 'paid_days' ? inr(r[c] as number) : String(r[c] ?? '—'))))}
            empty="No rows for this period."
          />
        </TabsContent>
        <TabsContent value="form16" className="space-y-2">
          <Select aria-label="Staff" className="w-80" placeholder="Choose a staff member…" options={(staff.data?.data ?? []).map((s) => ({ value: s.id, label: `${s.employee_id} · ${s.full_name}` }))} value={f16Staff} onChange={(e) => setF16Staff(e.target.value)} />
          {form16.data && (
            <div className="space-y-2 text-sm">
              <p>
                <b>{form16.data.data.staff_name}</b> · PAN {form16.data.data.pan ?? '—'} · FY {form16.data.data.financial_year} (AY {form16.data.data.assessment_year}) · {form16.data.data.regime} regime
              </p>
              <SimpleTable head={['Month', 'Gross', 'TDS']} rows={form16.data.data.months.map((mm) => [mm.period, inr(mm.gross), inr(mm.tds)])} />
              <p>Gross {inr(form16.data.data.gross_salary_paise)} · standard deduction {inr(form16.data.data.standard_deduction_paise)} · taxable {inr(form16.data.data.taxable_income_paise)} · tax {inr(form16.data.data.tax_on_income_paise)} · TDS deducted {inr(form16.data.data.tds_deducted_paise)}</p>
            </div>
          )}
        </TabsContent>
      </Tabs>

      <Modal open={wizard > 0} onOpenChange={(o) => !o && setWizard(0)} title={`Generate payroll · ${MONTHS[period.month - 1]} ${period.year}`} description={wizard === 1 ? 'Step 1 of 2 — scope' : 'Step 2 of 2 — confirm'}
        footer={
          wizard === 1 ? <Button onClick={() => setWizard(2)}>Next</Button> : (
            <Button loading={generate.isPending} onClick={() => generate.mutate(undefined, { onSuccess: (r) => { toast.success(`Generation queued (job ${r.data.job_id.slice(0, 8)}) — follow it in the jobs tray`); setWizard(0); }, onError: (e) => toast.error(getApiError(e)) })}>Generate</Button>
          )
        }
      >
        {wizard === 1 ? (
          <label className="block space-y-1.5 text-sm font-medium">
            College
            <Select placeholder="All colleges" options={(colleges.data?.data ?? []).map((c) => ({ value: c.id, label: `${c.code} · ${c.name}` }))} value={genScope.college_id} onChange={(e) => setGenScope({ college_id: e.target.value })} />
          </label>
        ) : (
          <p className="text-sm">Drafts of this month are recomputed; approved and paid runs are left untouched. Paid days come from the attendance summary (absences and unpaid leave are LOP).</p>
        )}
      </Modal>

      <Modal open={detail !== null} onOpenChange={(o) => !o && setDetail(null)} title={detail ? `${detail.staff_name} · ${MONTHS[detail.month - 1]} ${detail.year}` : ''} size="lg"
        footer={
          <div className="flex flex-wrap gap-2">
            {detail && (
              <Button variant="outline" onClick={async () => { try { downloadBlob(await hrApi.payslip(detail.id), 'payslip.pdf', true); } catch (e) { toast.error(getApiError(e)); } }}>
                <FileDown className="h-4 w-4" /> Payslip
              </Button>
            )}
            {one.data?.data.status === 'draft' && can('payroll', 'approve') && <Button onClick={() => approve.mutate(detail!.id, { onSuccess: () => { toast.success('Approved'); one.refetch(); }, onError: (e) => toast.error(getApiError(e)) })}>Approve</Button>}
            {one.data?.data.status === 'approved' && can('payroll', 'mark_paid') && (
              <>
                <FormField aria-label="Payment reference" placeholder="Payment reference" value={payRef} onChange={(e) => setPayRef(e.target.value)} />
                <Button disabled={payRef.length < 3} onClick={() => pay.mutate({ id: detail!.id, ref: payRef }, { onSuccess: () => { toast.success('Marked paid — payslip is being generated'); one.refetch(); }, onError: (e) => toast.error(getApiError(e)) })}>Mark paid</Button>
              </>
            )}
          </div>
        }
      >
        {one.data && (
          <div className="space-y-2 text-sm">
            <p>Status <StatusBadge status={one.data.data.status} /> · working days {one.data.data.working_days} · paid {num(one.data.data.paid_days)} · LOP {num(one.data.data.lop_days)}</p>
            <SimpleTable head={['Item', 'Type', 'Amount']} rows={one.data.data.items.map((i) => [i.label, label(i.component_type), inr(i.amount_paise)])} />
            <p className="font-semibold">Gross {inr(one.data.data.gross_paise)} · Deductions {inr(one.data.data.deductions_paise)} · Net {inr(one.data.data.net_paise)}</p>
          </div>
        )}
      </Modal>
    </div>
  );
}
