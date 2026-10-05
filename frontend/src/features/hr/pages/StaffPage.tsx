import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { ColumnDef } from '@tanstack/react-table';
import { Plus, Upload } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { DataTable } from '@/components/shared/DataTable';
import { FormField } from '@/components/shared/FormField';
import { PageHeader } from '@/components/shared/PageHeader';
import { ScopeTabs } from '@/components/shared/ScopeTabs';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input, Select, Textarea } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { usePermission } from '@/hooks/usePermission';
import { useDepartments } from '@/features/institution/hooks';
import { hrApi } from '../api';
import { downloadBlob } from '../download';
import { useDesignations, useHrMutation, useStaffList } from '../hooks';
import { label, type Staff } from '../types';

const TYPES = ['regular', 'contract', 'guest', 'visiting', 'adjunct', 'outsourced'];
const CSV_HEADER = 'first_name,last_name,department_code,designation,employment_type,joining_date,email,phone,gender';

/** /admin/hr/staff — staff master with masked PII, filters, create, bulk import (job) and XLSX export. */
export default function StaffPage() {
  const { can } = usePermission();
  const navigate = useNavigate();
  const [params, setParams] = useState<Record<string, string | number | undefined | null>>({ page: 1, page_size: 25 });
  const list = useStaffList(params);
  const departments = useDepartments({ scope: 'all', page_size: 200 });
  const designations = useDesignations();
  const [creating, setCreating] = useState(false);
  const [importing, setImporting] = useState(false);
  const [csv, setCsv] = useState(`${CSV_HEADER}\n`);
  const [draft, setDraft] = useState({ first_name: '', last_name: '', department_id: '', designation_id: '', employment_type: 'regular', joining_date: '', email: '', phone: '', hourly_rate_paise: '' });
  const [created, setCreated] = useState<{ username: string | null; temp_password: string | null } | null>(null);
  const set = (patch: Record<string, string | undefined>) => setParams((p) => ({ ...p, ...patch, page: 1 }));
  const create = useHrMutation(
    () =>
      hrApi.createStaff({
        ...draft,
        department_id: draft.department_id || undefined,
        designation_id: draft.designation_id || undefined,
        joining_date: draft.joining_date || undefined,
        email: draft.email || undefined,
        phone: draft.phone || undefined,
        last_name: draft.last_name || undefined,
        hourly_rate_paise: draft.hourly_rate_paise ? Number(draft.hourly_rate_paise) * 100 : undefined,
      }),
    ['staff'],
  );
  const columns = useMemo<ColumnDef<Staff, unknown>[]>(
    () => [
      { accessorKey: 'employee_id', header: 'Emp. id', cell: ({ row }) => <span className="font-medium">{row.original.employee_id}</span> },
      { accessorKey: 'first_name', header: 'Name', cell: ({ row }) => <span>{row.original.full_name} {row.original.is_self && <Badge variant="outline">me</Badge>}</span> },
      { id: 'dept', header: 'Department', enableSorting: false, cell: ({ row }) => row.original.department_code ?? '—' },
      { id: 'desig', header: 'Designation', enableSorting: false, cell: ({ row }) => row.original.designation_name ?? '—' },
      { accessorKey: 'employment_type', header: 'Type', cell: ({ getValue }) => label(String(getValue())) },
      { accessorKey: 'phone', header: 'Phone', enableSorting: false },
      { accessorKey: 'email', header: 'E-mail', enableSorting: false },
      { accessorKey: 'status', header: 'Status', cell: ({ getValue }) => <StatusBadge status={String(getValue())} /> },
    ],
    [],
  );
  const onExport = async () => {
    try {
      downloadBlob(await hrApi.exportStaff({ ...params, page: undefined, page_size: undefined }), 'staff.xlsx');
    } catch (e) {
      toast.error(getApiError(e));
    }
  };
  const submitImport = async () => {
    try {
      const r = await hrApi.bulkImport(csv);
      toast.success(`Import queued (job ${r.data.job_id.slice(0, 8)}) — the report arrives in the jobs tray`);
      setImporting(false);
    } catch (e) {
      toast.error(getApiError(e));
    }
  };
  const hourly = draft.employment_type === 'guest' || draft.employment_type === 'visiting';

  return (
    <div className="space-y-4">
      <PageHeader
        title="Staff"
        description="Staff master — PII is masked unless you hold hr:view_pii."
        actions={
          can('hr', 'create') && (
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => setImporting(true)}>
                <Upload className="h-4 w-4" /> Bulk import
              </Button>
              <Button onClick={() => setCreating(true)}>
                <Plus className="h-4 w-4" /> New staff
              </Button>
            </div>
          )
        }
      />
      <div className="flex flex-wrap items-center gap-2">
        <ScopeTabs visibility={list.data?.meta.visibility} value={params.scope as string | undefined} onChange={(scope) => set({ scope })} />
        <Input className="w-56" placeholder="Search name / employee id…" value={(params.q as string) ?? ''} onChange={(e) => set({ q: e.target.value || undefined })} />
        <Select className="w-40" placeholder="All departments" options={(departments.data?.data ?? []).map((d) => ({ value: d.id, label: d.code }))} value={(params.department_id as string) ?? ''} onChange={(e) => set({ department_id: e.target.value || undefined })} />
        <Select className="w-48" placeholder="All designations" options={(designations.data?.data ?? []).map((d) => ({ value: d.id, label: d.name }))} value={(params.designation_id as string) ?? ''} onChange={(e) => set({ designation_id: e.target.value || undefined })} />
        <Select className="w-36" placeholder="All types" options={TYPES.map((t) => ({ value: t, label: label(t) }))} value={(params.employment_type as string) ?? ''} onChange={(e) => set({ employment_type: e.target.value || undefined })} />
        <Select className="w-32" placeholder="All statuses" options={['active', 'on_leave', 'suspended', 'exited'].map((t) => ({ value: t, label: label(t) }))} value={(params.status as string) ?? ''} onChange={(e) => set({ status: e.target.value || undefined })} />
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
        onExport={can('hr', 'export') || can('hr', 'view_all') ? onExport : undefined}
        onRowClick={(r) => navigate(`/admin/hr/staff/${r.id}`)}
        rowKey={(r) => r.id}
      />

      <Modal
        open={creating}
        onOpenChange={setCreating}
        title="New staff member"
        description="A user account is created (username = employee id) with a temporary password."
        size="lg"
        footer={
          <Button
            loading={create.isPending}
            disabled={!draft.first_name || (hourly && !draft.hourly_rate_paise)}
            onClick={() =>
              create.mutate(undefined, {
                onSuccess: (r) => {
                  setCreating(false);
                  setCreated({ username: r.data.username, temp_password: r.data.temp_password });
                },
                onError: (e) => toast.error(getApiError(e)),
              })
            }
          >
            Create
          </Button>
        }
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <FormField label="First name" required value={draft.first_name} onChange={(e) => setDraft({ ...draft, first_name: e.target.value })} />
          <FormField label="Last name" value={draft.last_name} onChange={(e) => setDraft({ ...draft, last_name: e.target.value })} />
          <label className="space-y-1.5 text-sm font-medium">
            Department
            <Select placeholder="—" options={(departments.data?.data ?? []).map((d) => ({ value: d.id, label: `${d.code} · ${d.name}` }))} value={draft.department_id} onChange={(e) => setDraft({ ...draft, department_id: e.target.value })} />
          </label>
          <label className="space-y-1.5 text-sm font-medium">
            Designation
            <Select placeholder="—" options={(designations.data?.data ?? []).map((d) => ({ value: d.id, label: d.name }))} value={draft.designation_id} onChange={(e) => setDraft({ ...draft, designation_id: e.target.value })} />
          </label>
          <label className="space-y-1.5 text-sm font-medium">
            Employment type
            <Select options={TYPES.map((t) => ({ value: t, label: label(t) }))} value={draft.employment_type} onChange={(e) => setDraft({ ...draft, employment_type: e.target.value })} />
          </label>
          <FormField label="Joining date" type="date" value={draft.joining_date} onChange={(e) => setDraft({ ...draft, joining_date: e.target.value })} />
          <FormField label="E-mail" type="email" value={draft.email} onChange={(e) => setDraft({ ...draft, email: e.target.value })} />
          <FormField label="Phone" value={draft.phone} onChange={(e) => setDraft({ ...draft, phone: e.target.value })} />
          {hourly && <FormField label="Hourly rate (₹)" required type="number" value={draft.hourly_rate_paise} error={!draft.hourly_rate_paise ? 'Required for guest / visiting staff' : undefined} onChange={(e) => setDraft({ ...draft, hourly_rate_paise: e.target.value })} />}
        </div>
      </Modal>

      <Modal open={created !== null} onOpenChange={(o) => !o && setCreated(null)} title="Staff member created" description="Hand these over securely — the password is shown only once.">
        <p className="text-sm">
          Username <span className="font-mono font-semibold">{created?.username ?? '—'}</span>
          <br />
          Temporary password <span className="font-mono font-semibold">{created?.temp_password ?? '—'}</span>
        </p>
      </Modal>

      <Modal open={importing} onOpenChange={setImporting} title="Bulk import staff" description={`CSV with the header: ${CSV_HEADER}`} size="lg" footer={<Button onClick={submitImport}>Queue import</Button>}>
        <input type="file" accept=".csv,text/csv" aria-label="CSV file" onChange={async (e) => e.target.files?.[0] && setCsv(await e.target.files[0].text())} />
        <Textarea aria-label="CSV" rows={10} className="mt-2 font-mono text-xs" value={csv} onChange={(e) => setCsv(e.target.value)} />
      </Modal>
    </div>
  );
}
