import { useMemo, useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Plus } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { DataTable } from '@/components/shared/DataTable';
import { PageHeader } from '@/components/shared/PageHeader';
import { ScopeTabs } from '@/components/shared/ScopeTabs';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input, Select } from '@/components/ui/Input';
import { toast } from '@/components/ui/Toaster';
import { usePermission } from '@/hooks/usePermission';
import { useDepartments } from '@/features/institution/hooks';
import { academicsApi } from '../api';
import { CourseDrawer } from '../components/CourseDrawer';
import { BulkImportButton } from '../components/BulkImportButton';
import { downloadBlob } from '../download';
import { useCourses, useRegulations } from '../hooks';
import { COURSE_STATUSES, COURSE_TYPES, label, num, type Course } from '../types';

/** /admin/academics/courses — search by code/title (typo-tolerant), filters, detail drawer, export. */
export default function CoursesPage() {
  const { can } = usePermission();
  const [params, setParams] = useState<{
    page: number;
    page_size: number;
    scope?: string;
    q?: string;
    regulation_id?: string;
    department_id?: string;
    course_type?: string;
    status?: string;
    sort?: string | null;
  }>({ page: 1, page_size: 25 });
  const list = useCourses(params);
  const regulations = useRegulations({ page_size: 100 });
  const departments = useDepartments({ scope: 'all', page_size: 200 });
  const [open, setOpen] = useState<string | 'new' | null>(null);
  const set = (patch: Partial<typeof params>) => setParams((p) => ({ ...p, ...patch, page: 1 }));

  const columns = useMemo<ColumnDef<Course, unknown>[]>(
    () => [
      { accessorKey: 'code', header: 'Code', cell: ({ row }) => <span className="font-medium">{row.original.code}</span> },
      { accessorKey: 'title', header: 'Title' },
      { accessorKey: 'course_type', header: 'Type', cell: ({ getValue }) => <Badge variant="outline">{label(String(getValue()))}</Badge> },
      { id: 'ltpc', header: 'L-T-P-C', enableSorting: false, cell: ({ row }) => row.original.ltpc },
      { accessorKey: 'credits', header: 'Credits', cell: ({ getValue }) => num(getValue() as string) },
      { id: 'reg', header: 'Regulation', enableSorting: false, cell: ({ row }) => row.original.regulation_code },
      { id: 'dept', header: 'Department', enableSorting: false, cell: ({ row }) => row.original.department_code },
      { accessorKey: 'status', header: 'Status', cell: ({ getValue }) => <StatusBadge status={String(getValue())} /> },
    ],
    [],
  );

  const onExport = async () => {
    try {
      downloadBlob(await academicsApi.exportCourses({ ...params, page: undefined, page_size: undefined, scope: undefined }), 'courses.xlsx');
    } catch (e) {
      toast.error(getApiError(e));
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Courses"
        description="Courses are owned by a regulation — the same code under two regulations is two course rows."
        actions={
          <div className="flex gap-2">
            {can('courses', 'create') && params.regulation_id && <BulkImportButton regulationId={params.regulation_id} />}
            {can('courses', 'create') && (
              <Button onClick={() => setOpen('new')} disabled={!params.regulation_id} title={params.regulation_id ? undefined : 'Pick a regulation first'}>
                <Plus className="h-4 w-4" /> New course
              </Button>
            )}
          </div>
        }
      />
      <div className="flex flex-wrap items-center gap-2">
        <ScopeTabs visibility={list.data?.meta.visibility} value={params.scope} onChange={(scope) => set({ scope })} />
        <Input className="w-60" placeholder="Search code or title…" value={params.q ?? ''} onChange={(e) => set({ q: e.target.value || undefined })} />
        <Select className="w-44" placeholder="All regulations" options={(regulations.data?.data ?? []).map((r) => ({ value: r.id, label: `${r.code} (${r.status})` }))} value={params.regulation_id ?? ''} onChange={(e) => set({ regulation_id: e.target.value || undefined })} />
        <Select className="w-40" placeholder="All departments" options={(departments.data?.data ?? []).map((d) => ({ value: d.id, label: d.code }))} value={params.department_id ?? ''} onChange={(e) => set({ department_id: e.target.value || undefined })} />
        <Select className="w-44" placeholder="All types" options={COURSE_TYPES.map((t) => ({ value: t, label: label(t) }))} value={params.course_type ?? ''} onChange={(e) => set({ course_type: e.target.value || undefined })} />
        <Select className="w-36" placeholder="All statuses" options={COURSE_STATUSES.map((t) => ({ value: t, label: t }))} value={params.status ?? ''} onChange={(e) => set({ status: e.target.value || undefined })} />
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
        onExport={can('courses', 'export') || can('courses', 'view_all') ? onExport : undefined}
        onRowClick={(r) => setOpen(r.id)}
        rowKey={(r) => r.id}
      />
      <CourseDrawer courseId={open} regulationId={params.regulation_id} open={open !== null} onClose={() => setOpen(null)} />
    </div>
  );
}
