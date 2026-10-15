import { useMemo, useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Plus } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { DataTable } from '@/components/shared/DataTable';
import { FormField } from '@/components/shared/FormField';
import { PageHeader } from '@/components/shared/PageHeader';
import { ScopeTabs } from '@/components/shared/ScopeTabs';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input, Select } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Checkbox } from '@/components/ui/Switch';
import { toast } from '@/components/ui/Toaster';
import { usePermission } from '@/hooks/usePermission';
import { institutionApi } from '../api';
import { useColleges, useInstMutation } from '../hooks';
import { COLLEGE_TYPES, type College } from '../types';

const schema = z.object({
  code: z.string().regex(/^[A-Za-z0-9][A-Za-z0-9_.-]{0,19}$/, '1–20 letters/digits'),
  name: z.string().min(2).max(200),
  college_type: z.enum(COLLEGE_TYPES),
  affiliation_number: z.string().max(40).optional().or(z.literal('')),
  exam_centre_code: z.string().max(20).optional().or(z.literal('')),
  is_exam_centre: z.boolean(),
  aishe_code: z.string().max(20).optional().or(z.literal('')),
});
type FormValues = z.infer<typeof schema>;

/** /admin/colleges — table + drawer (type badges, exam-centre flag); college admins edit only their own college. */
export default function CollegesPage() {
  const { can } = usePermission();
  const [params, setParams] = useState<{ page: number; page_size: number; scope?: string; q?: string; college_type?: string }>({
    page: 1,
    page_size: 25,
  });
  const list = useColleges(params);
  const [editing, setEditing] = useState<College | 'new' | null>(null);
  const create = useInstMutation((b: Record<string, unknown>) => institutionApi.createCollege(b), ['colleges']);
  const update = useInstMutation(({ id, ...b }: Record<string, unknown>) => institutionApi.updateCollege(String(id), b), ['colleges']);
  const form = useForm<FormValues>({ resolver: zodResolver(schema) });

  const open = (c: College | 'new') => {
    setEditing(c);
    form.reset(
      c === 'new'
        ? { code: '', name: '', college_type: 'constituent', is_exam_centre: false }
        : {
            code: c.code,
            name: c.name,
            college_type: c.college_type as FormValues['college_type'],
            affiliation_number: c.affiliation_number ?? '',
            exam_centre_code: c.exam_centre_code ?? '',
            is_exam_centre: c.is_exam_centre,
            aishe_code: c.aishe_code ?? '',
          },
    );
  };

  const columns = useMemo<ColumnDef<College, unknown>[]>(
    () => [
      { accessorKey: 'code', header: 'Code' },
      {
        accessorKey: 'name',
        header: 'Name',
        cell: ({ row }) => (
          <span className="flex items-center gap-2">
            {row.original.name}
            {row.original.is_main && <Badge variant="info">main</Badge>}
          </span>
        ),
      },
      { accessorKey: 'college_type', header: 'Type', cell: ({ getValue }) => <Badge variant="outline">{String(getValue())}</Badge> },
      { accessorKey: 'department_count', header: 'Departments', enableSorting: false },
      {
        accessorKey: 'is_exam_centre',
        header: 'Exam centre',
        cell: ({ row }) => (row.original.is_exam_centre ? row.original.exam_centre_code ?? 'yes' : '—'),
      },
      {
        id: 'actions',
        header: '',
        cell: ({ row }) =>
          row.original.can_edit && (
            <Button size="sm" variant="ghost" onClick={() => open(row.original)}>
              Edit
            </Button>
          ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const onSubmit = form.handleSubmit((v) => {
    const body = Object.fromEntries(Object.entries(v).map(([k, val]) => [k, val === '' ? null : val]));
    const done = {
      onSuccess: () => {
        toast.success(editing === 'new' ? 'College created' : 'College updated');
        setEditing(null);
      },
      onError: (e: unknown) => toast.error(getApiError(e)),
    };
    if (editing === 'new') create.mutate(body, done);
    else if (editing) update.mutate({ id: editing.id, ...body, code: undefined, version: editing.version }, done);
  });

  return (
    <div className="space-y-4">
      <PageHeader
        title="Colleges"
        description="Colleges, campuses and study centres of the institution."
        actions={
          can('colleges', 'create') && (
            <Button onClick={() => open('new')}>
              <Plus className="h-4 w-4" /> New college
            </Button>
          )
        }
      />
      <div className="flex flex-wrap items-center gap-2">
        <ScopeTabs visibility={list.data?.meta.visibility} value={params.scope} onChange={(scope) => setParams({ ...params, scope, page: 1 })} />
        <Input className="w-60" placeholder="Search code or name…" onChange={(e) => setParams({ ...params, q: e.target.value || undefined, page: 1 })} />
        <Select
          className="w-48"
          placeholder="All types"
          options={COLLEGE_TYPES.map((t) => ({ value: t, label: t.replace(/_/g, ' ') }))}
          onChange={(e) => setParams({ ...params, college_type: e.target.value || undefined, page: 1 })}
        />
      </div>
      <DataTable
        columns={columns}
        data={list.data?.data ?? []}
        isLoading={list.isLoading}
        pagination={list.data?.meta.pagination}
        onPageChange={(page) => setParams({ ...params, page })}
        onPageSizeChange={(page_size) => setParams({ ...params, page_size, page: 1 })}
        rowKey={(r) => r.id}
      />
      <Modal
        open={editing !== null}
        onOpenChange={(o) => !o && setEditing(null)}
        title={editing === 'new' ? 'New college' : `Edit ${editing?.code ?? ''}`}
        footer={
          <Button onClick={onSubmit} loading={create.isPending || update.isPending}>
            Save
          </Button>
        }
      >
        <form className="grid gap-3 sm:grid-cols-2" onSubmit={onSubmit}>
          <FormField label="Code" required disabled={editing !== 'new'} {...form.register('code')} error={form.formState.errors.code} />
          <FormField label="Name" required {...form.register('name')} error={form.formState.errors.name} />
          <label className="space-y-1.5 text-sm font-medium">
            Type
            <Select options={COLLEGE_TYPES.map((t) => ({ value: t, label: t.replace(/_/g, ' ') }))} {...form.register('college_type')} />
          </label>
          <FormField label="Affiliation number" {...form.register('affiliation_number')} />
          <FormField label="AISHE code" {...form.register('aishe_code')} />
          <FormField label="Exam centre code" {...form.register('exam_centre_code')} />
          <label className="flex items-center gap-2 text-sm">
            <Checkbox aria-label="Exam centre" checked={form.watch('is_exam_centre')} onCheckedChange={(c) => form.setValue('is_exam_centre', c === true)} />
            Exam centre
          </label>
        </form>
      </Modal>
    </div>
  );
}
