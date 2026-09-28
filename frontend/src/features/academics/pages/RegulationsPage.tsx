import { useMemo, useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { useNavigate } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Lock, Plus } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { DataTable } from '@/components/shared/DataTable';
import { FormField } from '@/components/shared/FormField';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input, Select } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { usePermission } from '@/hooks/usePermission';
import { useColleges } from '@/features/institution/hooks';
import { academicsApi } from '../api';
import { useAcMutation, useRegulations } from '../hooks';
import type { Regulation } from '../types';

const schema = z.object({
  college_id: z.string().optional(),
  code: z.string().regex(/^[A-Za-z0-9][A-Za-z0-9_.-]{0,19}$/, '1–20 letters/digits, e.g. R2026'),
  name: z.string().min(2).max(120),
  effective_from_admission_year: z.coerce.number().int().min(1950).max(2100),
});
type FormValues = z.infer<typeof schema>;

const STATUSES = ['draft', 'approved', 'active', 'superseded'];

/** /admin/academics/regulations — versioned regulations with status chips; opens the regulation workspace. */
export default function RegulationsPage() {
  const { can } = usePermission();
  const navigate = useNavigate();
  const [params, setParams] = useState<{ page: number; page_size: number; status?: string; q?: string; sort?: string | null }>({ page: 1, page_size: 25 });
  const list = useRegulations(params);
  const colleges = useColleges({ scope: 'all', page_size: 200 });
  const [creating, setCreating] = useState(false);
  const create = useAcMutation((b: Record<string, unknown>) => academicsApi.createRegulation(b), ['regulations']);
  const form = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: { effective_from_admission_year: new Date().getFullYear() } });

  const columns = useMemo<ColumnDef<Regulation, unknown>[]>(
    () => [
      { accessorKey: 'code', header: 'Code', cell: ({ row }) => <span className="font-medium">{row.original.code}</span> },
      { accessorKey: 'name', header: 'Name' },
      { accessorKey: 'effective_from_admission_year', header: 'From batch' },
      { accessorKey: 'course_count', header: 'Courses', enableSorting: false },
      { accessorKey: 'program_count', header: 'Programmes', enableSorting: false },
      {
        accessorKey: 'status',
        header: 'Status',
        cell: ({ row }) => (
          <span className="flex items-center gap-1.5">
            <StatusBadge status={row.original.status} />
            {row.original.structure_locked && <Lock className="h-3.5 w-3.5 text-muted-foreground" aria-label="locked" />}
          </span>
        ),
      },
    ],
    [],
  );

  const onSubmit = form.handleSubmit((v) =>
    create.mutate(
      { ...v, college_id: v.college_id || null },
      {
        onSuccess: (r) => {
          toast.success(`Regulation ${r.data.code} created`);
          setCreating(false);
          navigate(`/admin/academics/regulations/${r.data.id}`);
        },
        onError: (e) => toast.error(getApiError(e)),
      },
    ),
  );

  return (
    <div className="space-y-4">
      <PageHeader
        title="Regulations"
        description="Versioned academic regulations: rules, courses, programme structures and electives. Active regulations are locked — clone to revise."
        actions={
          can('regulations', 'create') && (
            <Button onClick={() => { form.reset({ code: '', name: '', effective_from_admission_year: new Date().getFullYear(), college_id: '' }); setCreating(true); }}>
              <Plus className="h-4 w-4" /> New regulation
            </Button>
          )
        }
      />
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex gap-1" role="group" aria-label="Status">
          {[undefined, ...STATUSES].map((s) => (
            <Button key={s ?? 'all'} size="sm" variant={params.status === s ? 'default' : 'outline'} onClick={() => setParams((p) => ({ ...p, status: s, page: 1 }))}>
              {s ?? 'all'}
            </Button>
          ))}
        </div>
        <Input className="w-60" placeholder="Search code or name…" value={params.q ?? ''} onChange={(e) => setParams((p) => ({ ...p, q: e.target.value || undefined, page: 1 }))} />
      </div>
      <DataTable
        columns={columns}
        data={list.data?.data ?? []}
        isLoading={list.isLoading}
        pagination={list.data?.meta.pagination}
        onPageChange={(page) => setParams((p) => ({ ...p, page }))}
        onPageSizeChange={(page_size) => setParams((p) => ({ ...p, page_size, page: 1 }))}
        sort={params.sort}
        onSortChange={(sort) => setParams((p) => ({ ...p, sort }))}
        onRowClick={(r) => navigate(`/admin/academics/regulations/${r.id}`)}
        rowKey={(r) => r.id}
      />
      <Modal open={creating} onOpenChange={setCreating} title="New regulation" description="Rules are pre-filled from the institution's regulatory pack; the pack's assessment schemes are copied in." footer={<Button onClick={onSubmit} loading={create.isPending}>Create draft</Button>}>
        <form className="grid gap-3 sm:grid-cols-2" onSubmit={onSubmit}>
          <FormField label="Code" required placeholder="R2026" {...form.register('code')} error={form.formState.errors.code} />
          <FormField label="From admission year" type="number" required {...form.register('effective_from_admission_year')} error={form.formState.errors.effective_from_admission_year} />
          <FormField className="sm:col-span-2" label="Name" required placeholder="Regulations 2026 (NEP)" {...form.register('name')} error={form.formState.errors.name} />
          <label className="space-y-1.5 text-sm font-medium sm:col-span-2">
            Scope
            <Select placeholder="Institution-wide" options={(colleges.data?.data ?? []).map((c) => ({ value: c.id, label: `College ${c.code} · ${c.name}` }))} {...form.register('college_id')} />
          </label>
        </form>
      </Modal>
    </div>
  );
}
