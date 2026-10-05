import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Plus } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { FormField } from '@/components/shared/FormField';
import { PageHeader } from '@/components/shared/PageHeader';
import { ScopeTabs } from '@/components/shared/ScopeTabs';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Select } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { usePermission } from '@/hooks/usePermission';
import { hrApi } from '../api';
import { SimpleTable } from '../components/shared';
import { useHrMutation, useStaffList } from '../hooks';
import { inr, label, localDate } from '../types';

const TYPES = ['festival', 'vehicle', 'housing', 'salary_advance', 'computer'];

/** /admin/hr/loans — loans & advances; payroll managers record active loans, staff request them (workflow hr.loan). */
export default function LoansPage() {
  const { can } = usePermission();
  const manager = can('payroll', 'manage');
  const [scope, setScope] = useState<string | undefined>();
  const loans = useQuery({ queryKey: ['loans', scope], queryFn: () => hrApi.loans({ scope, page_size: 100 }) });
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ staff_id: '', loan_type: 'festival', principal: '', emi: '', start_month: localDate().slice(0, 8) + '01' });
  const staff = useStaffList({ scope: 'all', page_size: 200 }, open && manager);
  const create = useHrMutation(
    () =>
      hrApi.createLoan({
        staff_id: manager && form.staff_id ? form.staff_id : undefined,
        loan_type: form.loan_type,
        principal_paise: Math.round(Number(form.principal) * 100),
        emi_paise: Math.round(Number(form.emi) * 100),
        start_month: form.start_month,
      }),
    ['loans'],
  );
  const foreclose = useHrMutation((id: string) => hrApi.foreclose(id), ['loans']);
  return (
    <div className="space-y-4">
      <PageHeader title="Loans & advances" description="EMIs are deducted in payroll until the balance is cleared." actions={<Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> {manager ? 'Record loan' : 'Request loan'}</Button>} />
      <ScopeTabs visibility={loans.data?.meta.visibility} value={scope} onChange={setScope} />
      <SimpleTable
        head={['Staff', 'Type', 'Principal', 'EMI', 'Balance', 'EMIs left', 'Status', '']}
        rows={(loans.data?.data ?? []).map((l) => [
          `${l.employee_id ?? ''} · ${l.staff_name ?? ''}`,
          label(l.loan_type),
          inr(l.principal_paise),
          inr(l.emi_paise),
          inr(l.balance_paise),
          l.emis_remaining,
          <StatusBadge key="s" status={l.status} />,
          manager && l.status === 'active' ? <Button key="f" size="sm" variant="outline" onClick={() => foreclose.mutate(l.id, { onSuccess: () => toast.success('Foreclosed'), onError: (e) => toast.error(getApiError(e)) })}>Foreclose</Button> : null,
        ])}
      />
      <Modal open={open} onOpenChange={setOpen} title={manager ? 'Record a loan' : 'Request a loan'} footer={<Button loading={create.isPending} disabled={!form.principal || !form.emi || Number(form.emi) > Number(form.principal)} onClick={() => create.mutate(undefined, { onSuccess: () => { toast.success('Saved'); setOpen(false); }, onError: (e) => toast.error(getApiError(e)) })}>Save</Button>}>
        <div className="grid gap-3 sm:grid-cols-2">
          {manager && (
            <label className="space-y-1.5 text-sm font-medium sm:col-span-2">
              Staff (empty = myself)
              <Select placeholder="Myself" options={(staff.data?.data ?? []).map((s) => ({ value: s.id, label: `${s.employee_id} · ${s.full_name}` }))} value={form.staff_id} onChange={(e) => setForm({ ...form, staff_id: e.target.value })} />
            </label>
          )}
          <label className="space-y-1.5 text-sm font-medium">
            Type
            <Select options={TYPES.map((t) => ({ value: t, label: label(t) }))} value={form.loan_type} onChange={(e) => setForm({ ...form, loan_type: e.target.value })} />
          </label>
          <FormField label="Start month" type="date" value={form.start_month} onChange={(e) => setForm({ ...form, start_month: e.target.value })} />
          <FormField label="Principal (₹)" type="number" value={form.principal} onChange={(e) => setForm({ ...form, principal: e.target.value })} />
          <FormField label="EMI (₹)" type="number" value={form.emi} error={Number(form.emi) > Number(form.principal) ? 'EMI exceeds the principal' : undefined} onChange={(e) => setForm({ ...form, emi: e.target.value })} />
        </div>
      </Modal>
    </div>
  );
}
