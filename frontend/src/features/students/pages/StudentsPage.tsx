import { useMemo, useState } from 'react';
import { InsightsPanel } from '@/features/analytics/components/InsightsPanel';
import { useNavigate } from 'react-router-dom';
import type { ColumnDef } from '@tanstack/react-table';
import { CreditCard, FileSpreadsheet, Plus, Upload } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { DataTable } from '@/components/shared/DataTable';
import { PageHeader } from '@/components/shared/PageHeader';
import { ScopeTabs } from '@/components/shared/ScopeTabs';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Input, Select } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { useFeature } from '@/hooks/useFeature';
import { usePermission } from '@/hooks/usePermission';
import { useBatches, usePrograms } from '@/features/academics/hooks';
import { downloadBlob } from '@/features/hr/download';
import { SimpleTable } from '@/features/hr/components/shared';
import { studentsApi } from '../api';
import { HoldsBadge, StandingChip } from '../components/shared';
import { useStudentStats, useStudents } from '../hooks';
import { STANDINGS, STUDENT_STATUSES, label, type BulkImportResult, type StudentListItem } from '../types';

/** Bulk import wizard: file → dry run (report with row errors) → apply (job; the report arrives in the jobs tray). */
function ImportWizard({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<BulkImportResult | null>(null);
  const [busy, setBusy] = useState(false);
  const reset = () => {
    setFile(null);
    setReport(null);
  };
  const run = async (dryRun: boolean) => {
    if (!file) return;
    setBusy(true);
    try {
      const r = await studentsApi.bulkImport(file, dryRun);
      if (dryRun) setReport(r.data);
      else {
        toast.success(`Import queued (job ${r.data.job_id?.slice(0, 8)}) — the report arrives in the jobs tray`);
        reset();
        onOpenChange(false);
      }
    } catch (e) {
      toast.error(getApiError(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      open={open}
      onOpenChange={(o) => {
        if (!o) reset();
        onOpenChange(o);
      }}
      title="Bulk import students"
      description="Upload the XLSX template (or CSV). Step 1 validates every row; step 2 queues the import job for the valid rows."
      size="xl"
      footer={
        <div className="flex w-full flex-wrap justify-between gap-2">
          <Button variant="ghost" onClick={async () => downloadBlob(await studentsApi.importTemplate(), 'students-import-template.xlsx')}>
            <FileSpreadsheet className="h-4 w-4" /> Template
          </Button>
          <div className="flex gap-2">
            <Button variant="outline" disabled={!file} loading={busy && !report} onClick={() => run(true)}>
              1 · Dry run
            </Button>
            <Button disabled={!report || report.succeeded === 0} loading={busy && !!report} onClick={() => run(false)}>
              2 · Import {report ? `${report.succeeded} row(s)` : ''}
            </Button>
          </div>
        </div>
      }
    >
      <input
        type="file"
        aria-label="Import file"
        accept=".xlsx,.csv"
        onChange={(e) => {
          setFile(e.target.files?.[0] ?? null);
          setReport(null);
        }}
      />
      {report && (
        <div className="mt-4 space-y-2">
          <p className="text-sm">
            <Badge variant="success">{report.succeeded} valid</Badge> <Badge variant={report.failed.length ? 'destructive' : 'secondary'}>{report.failed.length} with errors</Badge>{' '}
            <span className="text-muted-foreground">of {report.total} rows</span>
          </p>
          {report.failed.length > 0 && (
            <SimpleTable head={['Row', 'Field', 'Problem']} rows={report.failed.map((f) => [f.row, f.field ?? '—', f.reason])} />
          )}
        </div>
      )}
    </Modal>
  );
}

/** /admin/students — student master: scope tabs, filters, stats strip, bulk import wizard, export, ID cards job. */
export default function StudentsPage() {
  const { can } = usePermission();
  const navigate = useNavigate();
  const [params, setParams] = useState<Record<string, string | number | boolean | undefined | null>>({ page: 1, page_size: 25 });
  const list = useStudents(params);
  const stats = useStudentStats(can('students', 'view_all'));
  const programs = usePrograms({ page_size: 200 });
  const batches = useBatches({ page_size: 200, program_id: (params.program_id as string) || undefined });
  const [importing, setImporting] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const idCardsOn = useFeature('students.id_cards');
  const importOn = useFeature('students.bulk_import');
  const set = (patch: Record<string, string | boolean | undefined>) => setParams((p) => ({ ...p, ...patch, page: 1 }));
  const rows = useMemo(() => list.data?.data ?? [], [list.data]);
  const toggle = (id: string) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  const canCards = idCardsOn && can('students', 'id_card');
  const columns = useMemo<ColumnDef<StudentListItem, unknown>[]>(
    () => [
      ...(canCards
        ? [
            {
              id: 'pick',
              enableSorting: false,
              header: () => (
                <input
                  type="checkbox"
                  aria-label="Select page"
                  checked={rows.length > 0 && rows.every((r) => selected.has(r.id))}
                  onChange={(e) => setSelected((s) => {
                    const n = new Set(s);
                    rows.forEach((r) => (e.target.checked ? n.add(r.id) : n.delete(r.id)));
                    return n;
                  })}
                />
              ),
              cell: ({ row }) => (
                <input type="checkbox" aria-label={`Select ${row.original.registration_number}`} checked={selected.has(row.original.id)} onClick={(e) => e.stopPropagation()} onChange={() => toggle(row.original.id)} />
              ),
            } as ColumnDef<StudentListItem, unknown>,
          ]
        : []),
      { accessorKey: 'registration_number', header: 'Reg. no', cell: ({ row }) => <span className="font-mono text-xs font-medium">{row.original.registration_number}</span> },
      { accessorKey: 'first_name', header: 'Name', cell: ({ row }) => <span>{row.original.full_name} {row.original.is_self && <Badge variant="outline">me</Badge>}</span> },
      { id: 'program', header: 'Programme', enableSorting: false, cell: ({ row }) => row.original.program_code ?? '—' },
      { id: 'batch', header: 'Batch / section', enableSorting: false, cell: ({ row }) => `${row.original.batch_code ?? '—'}${row.original.section_name ? ` · ${row.original.section_name}` : ''}` },
      { id: 'term', header: 'Term', enableSorting: false, cell: ({ row }) => row.original.term_number ?? '—' },
      { accessorKey: 'phone', header: 'Phone', enableSorting: false },
      { accessorKey: 'status', header: 'Status', cell: ({ getValue }) => <StatusBadge status={String(getValue())} /> },
      { id: 'standing', header: 'Standing', enableSorting: false, cell: ({ row }) => <StandingChip standing={row.original.academic_standing} /> },
      { id: 'holds', header: 'Holds', enableSorting: false, cell: ({ row }) => <HoldsBadge count={row.original.open_holds} /> },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [canCards, rows, selected],
  );
  const onExport = async () => {
    try {
      downloadBlob(await studentsApi.exportXlsx({ ...params, page: undefined, page_size: undefined }), 'students.xlsx');
    } catch (e) {
      toast.error(getApiError(e));
    }
  };
  const idCards = async () => {
    try {
      const r = await studentsApi.idCards([...selected]);
      toast.success(`ID cards queued (job ${r.data.job_id.slice(0, 8)}) — the ZIP arrives in the jobs tray`);
      setSelected(new Set());
    } catch (e) {
      toast.error(getApiError(e));
    }
  };
  const vis = list.data?.meta.visibility;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Students"
        description={vis && !vis.pii ? 'Student master — Aadhaar, phone and bank details are masked for your role.' : 'Student master.'}
        actions={
          <div className="flex flex-wrap gap-2">
            {canCards && (
              <Button variant="outline" disabled={!selected.size} onClick={idCards}>
                <CreditCard className="h-4 w-4" /> ID cards{selected.size ? ` (${selected.size})` : ''}
              </Button>
            )}
            {importOn && can('students', 'bulk_import') && (
              <Button variant="outline" onClick={() => setImporting(true)}>
                <Upload className="h-4 w-4" /> Bulk import
              </Button>
            )}
            {can('students', 'create') && (
              <Button onClick={() => navigate('/admin/students/new')}>
                <Plus className="h-4 w-4" /> New student
              </Button>
            )}
          </div>
        }
      />
      <InsightsPanel module="students" filters={{ program_id: params.program_id, department_id: params.department_id, batch_id: params.batch_id }} />
      {stats.data && (
        <div className="grid gap-3 sm:grid-cols-4">
          <Card><CardContent className="pt-4 sm:pt-4"><p className="text-xs text-muted-foreground">Students</p><p className="text-2xl font-semibold">{stats.data.data.total}</p></CardContent></Card>
          {['active', 'on_break', 'detained'].map((k) => (
            <Card key={k}><CardContent className="pt-4 sm:pt-4"><p className="text-xs text-muted-foreground">{label(k)}</p><p className="text-2xl font-semibold">{stats.data!.data.by_status.find((b) => b.key === k)?.count ?? 0}</p></CardContent></Card>
          ))}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <ScopeTabs visibility={vis} value={params.scope as string | undefined} onChange={(scope) => set({ scope })} labels={{ own: 'Mine', all: 'All' }} />
        <Input className="w-56" placeholder="Search name / reg. no…" value={(params.q as string) ?? ''} onChange={(e) => set({ q: e.target.value || undefined })} />
        <Select className="w-40" aria-label="Programme" placeholder="All programmes" options={(programs.data?.data ?? []).map((p) => ({ value: p.id, label: p.code }))} value={(params.program_id as string) ?? ''} onChange={(e) => set({ program_id: e.target.value || undefined, batch_id: undefined })} />
        <Select className="w-44" aria-label="Batch" placeholder="All batches" options={(batches.data?.data ?? []).map((b) => ({ value: b.id, label: b.code }))} value={(params.batch_id as string) ?? ''} onChange={(e) => set({ batch_id: e.target.value || undefined })} />
        <Select className="w-36" aria-label="Status" placeholder="All statuses" options={STUDENT_STATUSES.map((t) => ({ value: t, label: label(t) }))} value={(params.status as string) ?? ''} onChange={(e) => set({ status: e.target.value || undefined })} />
        <Select className="w-36" aria-label="Standing" placeholder="Any standing" options={STANDINGS.map((t) => ({ value: t, label: label(t) }))} value={(params.standing as string) ?? ''} onChange={(e) => set({ standing: e.target.value || undefined })} />
        <label className="flex items-center gap-1.5 text-sm">
          <input type="checkbox" checked={!!params.has_holds} onChange={(e) => set({ has_holds: e.target.checked || undefined })} /> With holds
        </label>
      </div>
      <DataTable
        columns={columns}
        data={rows}
        isLoading={list.isLoading}
        pagination={list.data?.meta.pagination}
        onPageChange={(page) => setParams((p) => ({ ...p, page }))}
        onPageSizeChange={(page_size) => setParams((p) => ({ ...p, page_size, page: 1 }))}
        sort={params.sort as string | undefined}
        onSortChange={(sort) => setParams((p) => ({ ...p, sort }))}
        onExport={can('students', 'export') || can('students', 'view_all') ? onExport : undefined}
        onRowClick={(r) => navigate(`/admin/students/${r.id}`)}
        rowKey={(r) => r.id}
        emptyDescription={vis && !vis.scopes.length && !vis.self ? 'You have no advisees yet.' : undefined}
      />
      <ImportWizard open={importing} onOpenChange={setImporting} />
    </div>
  );
}
