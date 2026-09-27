import { useState } from 'react';
import FullCalendar from '@fullcalendar/react';
import dayGridPlugin from '@fullcalendar/daygrid';
import { CalendarDays, Download, List, Plus, Trash2, Upload } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { DateField, FormField } from '@/components/shared/FormField';
import { PageHeader } from '@/components/shared/PageHeader';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Select, Textarea } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs';
import { toast } from '@/components/ui/Toaster';
import { usePermission } from '@/hooks/usePermission';
import { institutionApi } from '../api';
import { useHolidays, useInstMutation } from '../hooks';
import { HOLIDAY_TYPES, type HolidayBulkResult } from '../types';

const TEMPLATE = 'name,date,end_date,type,applies_to\nIndependence Day,2026-08-15,,public,all';

/** /admin/holidays — calendar + table, bulk CSV import (partial success report), iCal download. */
export default function HolidaysPage() {
  const { can } = usePermission();
  const manage = can('institutions', 'manage');
  const holidays = useHolidays({ page_size: 200 });
  const [adding, setAdding] = useState(false);
  const [importing, setImporting] = useState(false);
  const [csv, setCsv] = useState(TEMPLATE);
  const [report, setReport] = useState<HolidayBulkResult | null>(null);
  const [draft, setDraft] = useState({ name: '', holiday_date: '', end_date: '', holiday_type: 'public', applies_to: 'all' });
  const create = useInstMutation((b: Record<string, unknown>) => institutionApi.createHoliday(b), ['holidays']);
  const remove = useInstMutation((id: string) => institutionApi.deleteHoliday(id), ['holidays']);
  const bulk = useInstMutation((text: string) => institutionApi.importHolidays(text), ['holidays']);
  const rows = holidays.data?.data ?? [];
  const onErr = (e: unknown) => toast.error(getApiError(e));

  const downloadIcs = async () => {
    const res = (await institutionApi.holidaysIcs()) as unknown as Blob;
    const url = URL.createObjectURL(res instanceof Blob ? res : new Blob([String(res)], { type: 'text/calendar' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = 'holidays.ics';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Holidays"
        description="Institution-wide and college holidays used by the timetable and attendance."
        actions={
          <>
            <Button variant="outline" onClick={downloadIcs}>
              <Download className="h-4 w-4" /> iCal
            </Button>
            {manage && (
              <>
                <Button variant="outline" onClick={() => { setReport(null); setImporting(true); }}>
                  <Upload className="h-4 w-4" /> Bulk import
                </Button>
                <Button onClick={() => setAdding(true)}>
                  <Plus className="h-4 w-4" /> Add
                </Button>
              </>
            )}
          </>
        }
      />
      <Tabs defaultValue="calendar">
        <TabsList>
          <TabsTrigger value="calendar">
            <CalendarDays className="mr-1 h-4 w-4" /> Calendar
          </TabsTrigger>
          <TabsTrigger value="table">
            <List className="mr-1 h-4 w-4" /> Table
          </TabsTrigger>
        </TabsList>
        <TabsContent value="calendar">
          <div className="rounded-md border bg-card p-2">
            <FullCalendar
              plugins={[dayGridPlugin]}
              initialView="dayGridMonth"
              height="auto"
              events={rows.map((h) => ({
                id: h.id,
                title: h.name,
                start: h.holiday_date,
                end: h.end_date ? new Date(new Date(h.end_date).getTime() + 86400000).toISOString().slice(0, 10) : undefined,
                allDay: true,
              }))}
            />
          </div>
        </TabsContent>
        <TabsContent value="table">
          <table className="w-full text-sm">
            <thead className="text-left text-muted-foreground">
              <tr>
                <th className="p-2">Date</th>
                <th className="p-2">Name</th>
                <th className="p-2">Type</th>
                <th className="p-2">Applies to</th>
                <th />
              </tr>
            </thead>
            <tbody className="divide-y">
              {rows.map((h) => (
                <tr key={h.id}>
                  <td className="p-2">
                    {h.holiday_date}
                    {h.end_date ? ` → ${h.end_date}` : ''}
                  </td>
                  <td className="p-2">{h.name}</td>
                  <td className="p-2">
                    <Badge variant="outline">{h.holiday_type}</Badge>
                  </td>
                  <td className="p-2">{h.applies_to}</td>
                  <td className="p-2 text-right">
                    {manage && (
                      <Button size="icon" variant="ghost" aria-label={`Delete ${h.name}`} onClick={() => remove.mutate(h.id, { onError: onErr })}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TabsContent>
      </Tabs>

      <Modal
        open={adding}
        onOpenChange={setAdding}
        title="Add holiday"
        footer={
          <Button
            loading={create.isPending}
            onClick={() =>
              create.mutate(
                { ...draft, end_date: draft.end_date || null },
                { onSuccess: () => { toast.success('Holiday added'); setAdding(false); }, onError: onErr },
              )
            }
          >
            Add
          </Button>
        }
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <FormField label="Name" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
          <DateField label="Date" value={draft.holiday_date} onChange={(v) => setDraft({ ...draft, holiday_date: v ?? '' })} />
          <DateField label="Until (optional)" value={draft.end_date} onChange={(v) => setDraft({ ...draft, end_date: v ?? '' })} />
          <label className="space-y-1.5 text-sm font-medium">
            Type
            <Select value={draft.holiday_type} options={HOLIDAY_TYPES.map((t) => ({ value: t, label: t.replace('_', ' ') }))} onChange={(e) => setDraft({ ...draft, holiday_type: e.target.value })} />
          </label>
          <label className="space-y-1.5 text-sm font-medium">
            Applies to
            <Select value={draft.applies_to} options={['all', 'students', 'staff'].map((t) => ({ value: t, label: t }))} onChange={(e) => setDraft({ ...draft, applies_to: e.target.value })} />
          </label>
        </div>
      </Modal>

      <Modal
        open={importing}
        onOpenChange={setImporting}
        size="lg"
        title="Bulk import holidays"
        description="CSV: name,date,end_date,type,applies_to — valid rows are imported even when others fail."
        footer={
          <Button loading={bulk.isPending} onClick={() => bulk.mutate(csv, { onSuccess: (r) => setReport(r.data), onError: onErr })}>
            Import
          </Button>
        }
      >
        <Textarea rows={8} className="font-mono text-xs" value={csv} onChange={(e) => setCsv(e.target.value)} />
        {report && (
          <div className="mt-3 text-sm">
            <p>
              <b>{report.succeeded}</b> imported, <b>{report.failed.length}</b> failed.
            </p>
            <ul className="mt-1 list-disc pl-5 text-destructive">
              {report.failed.map((f) => (
                <li key={f.index}>
                  Row {f.index + 1}: {f.code} — {f.message}
                </li>
              ))}
            </ul>
          </div>
        )}
      </Modal>
    </div>
  );
}
