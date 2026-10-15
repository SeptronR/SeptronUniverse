import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { getApiError } from '@/api/axios';
import { FormField } from '@/components/shared/FormField';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Select } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { usePermission } from '@/hooks/usePermission';
import { institutionApi } from '@/features/institution/api';
import { SimpleTable } from '@/features/hr/components/shared';
import { admissionsApi } from '../api';
import { useAdmissionsMutation, useCycles } from '../hooks';
import { CYCLE_STATUSES, label, rupees } from '../types';

const SLUG = /^[a-z0-9][a-z0-9-]{1,58}[a-z0-9]$/;

/** /admin/admissions/cycles — admission cycles with status, intake and applicants; create dialog. */
export default function CyclesPage() {
  const navigate = useNavigate();
  const { can } = usePermission();
  const [status, setStatus] = useState('');
  const cycles = useCycles({ status: status || undefined });
  const years = useQuery({ queryKey: ['academic-years'], queryFn: () => institutionApi.years() });
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: '', slug: '', level: 'ug', academic_year_id: '', fee: '1000', opens_at: '', closes_at: '' });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const create = useAdmissionsMutation(() =>
    admissionsApi.createCycle({
      name: form.name,
      slug: form.slug,
      level: form.level,
      academic_year_id: form.academic_year_id,
      application_fee_paise: Math.round(Number(form.fee || 0) * 100),
      opens_at: form.opens_at ? new Date(form.opens_at).toISOString() : undefined,
      closes_at: form.closes_at ? new Date(form.closes_at).toISOString() : undefined,
    }),
  );
  useEffect(() => {
    document.title = 'Admission cycles';
  }, []);
  const submit = async () => {
    const e: Record<string, string> = {};
    if (form.name.trim().length < 3) e.name = 'At least 3 characters';
    if (!SLUG.test(form.slug)) e.slug = 'Lower-case letters, digits and hyphens';
    if (!form.academic_year_id) e.academic_year_id = 'Pick the academic year';
    if (form.opens_at && form.closes_at && form.closes_at <= form.opens_at) e.closes_at = 'Must be after the opening';
    setErrors(e);
    if (Object.keys(e).length) return;
    try {
      const r = await create.mutateAsync(undefined);
      toast.success('Cycle created');
      setOpen(false);
      navigate(`/admin/admissions/cycles/${r.data.id}`);
    } catch (err) {
      toast.error(getApiError(err));
    }
  };
  const yearOptions = ((years.data?.data ?? []) as { id: string; name: string }[]).map((y) => ({ value: y.id, label: y.name }));
  return (
    <div className="space-y-4">
      <PageHeader
        title="Admission cycles"
        description="Cycles per level with programme intakes, seat matrix, merit lists and counselling."
        actions={can('admissions', 'manage') && <Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> New cycle</Button>}
      />
      <Select className="w-44" aria-label="Status" placeholder="All statuses" options={CYCLE_STATUSES.map((s) => ({ value: s, label: label(s) }))} value={status} onChange={(e) => setStatus(e.target.value)} />
      <SimpleTable
        head={['Cycle', 'Level', 'Window', 'Fee', 'Programmes', 'Intake', 'Applicants', 'Status']}
        rows={(cycles.data?.data ?? []).map((c) => [
          <button key="n" type="button" className="text-left font-medium hover:underline" onClick={() => navigate(`/admin/admissions/cycles/${c.id}`)}>{c.name}<div className="font-mono text-xs text-muted-foreground">{c.slug}</div></button>,
          label(c.level),
          `${c.opens_at ? new Date(c.opens_at).toLocaleDateString() : '—'} → ${c.closes_at ? new Date(c.closes_at).toLocaleDateString() : '—'}`,
          rupees(c.application_fee_paise),
          c.programs_count,
          c.intake_total,
          c.applicants_count,
          <StatusBadge key="s" status={c.status} />,
        ])}
        empty={cycles.isLoading ? 'Loading…' : 'No admission cycles yet.'}
      />
      <Modal open={open} onOpenChange={setOpen} title="New admission cycle" footer={<Button disabled={create.isPending} onClick={submit}>Create</Button>}>
        <div className="grid gap-3 sm:grid-cols-2">
          <FormField label="Name" required error={errors.name} value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
          <FormField label="Slug" required error={errors.slug} value={form.slug} onChange={(e) => setForm((f) => ({ ...f, slug: e.target.value.toLowerCase() }))} />
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="lvl">Level</label>
            <Select id="lvl" options={['ug', 'pg', 'phd', 'diploma', 'lateral', 'certificate'].map((l) => ({ value: l, label: label(l) }))} value={form.level} onChange={(e) => setForm((f) => ({ ...f, level: e.target.value }))} />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="yr">Academic year</label>
            <Select id="yr" placeholder="Select…" options={yearOptions} value={form.academic_year_id} onChange={(e) => setForm((f) => ({ ...f, academic_year_id: e.target.value }))} />
            {errors.academic_year_id && <p className="text-xs text-destructive">{errors.academic_year_id}</p>}
          </div>
          <FormField label="Application fee (₹)" type="number" value={form.fee} onChange={(e) => setForm((f) => ({ ...f, fee: e.target.value }))} />
          <span />
          <FormField label="Opens" type="datetime-local" value={form.opens_at} onChange={(e) => setForm((f) => ({ ...f, opens_at: e.target.value }))} />
          <FormField label="Closes" type="datetime-local" error={errors.closes_at} value={form.closes_at} onChange={(e) => setForm((f) => ({ ...f, closes_at: e.target.value }))} />
        </div>
      </Modal>
    </div>
  );
}
