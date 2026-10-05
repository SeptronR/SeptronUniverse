import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Plus } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { FormField } from '@/components/shared/FormField';
import { PageHeader } from '@/components/shared/PageHeader';
import { ScopeTabs } from '@/components/shared/ScopeTabs';
import { Button } from '@/components/ui/Button';
import { Input, Select } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs';
import { toast } from '@/components/ui/Toaster';
import { useFeature } from '@/hooks/useFeature';
import { usePermission } from '@/hooks/usePermission';
import { cn } from '@/utils/cn';
import { hrApi } from '../api';
import { localDate } from '../types';
import { SimpleTable } from '../components/shared';
import { useAttendance, useHrMutation, useStaffList } from '../hooks';

const CODE: Record<string, [string, string]> = {
  present: ['P', 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200'],
  absent: ['A', 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200'],
  half_day: ['½', 'bg-amber-100 text-amber-800'],
  on_leave: ['L', 'bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-200'],
  on_duty: ['OD', 'bg-indigo-100 text-indigo-800'],
  holiday: ['H', 'bg-slate-200 text-slate-700'],
  week_off: ['W', 'bg-slate-100 text-slate-500'],
};

/** /admin/hr/attendance — monthly grid per scope (Mine | Team | All), devices (biometric), regularisation request. */
export default function AttendancePage() {
  const { can } = usePermission();
  const [month, setMonth] = useState(localDate().slice(0, 7));
  const [scope, setScope] = useState<string | undefined>();
  const [marking, setMarking] = useState(false);
  const [mark, setMark] = useState({ staff_id: '', date: '', status: 'present' });
  const [reg, setReg] = useState({ date: '', status: 'present', reason: '' });
  const [device, setDevice] = useState({ name: '', location: '' });
  const [token, setToken] = useState<string | null>(null);
  const rows = useAttendance({ month, scope, page_size: 200 });
  const summary = useQuery({ queryKey: ['staff-attendance', 'summary', month, scope], queryFn: () => hrApi.summary({ month, scope }) });
  const bio = useFeature('attendance.biometric');
  const devices = useQuery({ queryKey: ['staff-attendance', 'devices'], queryFn: hrApi.devices, enabled: bio && can('attendance', 'device_manage') });
  const staff = useStaffList({ scope: 'all', page_size: 200 }, marking);
  const doMark = useHrMutation(() => hrApi.mark(mark), ['staff-attendance']);
  const doReg = useHrMutation(() => hrApi.regularise(reg), ['staff-attendance', 'approvals']);
  const doDevice = useHrMutation(() => hrApi.createDevice({ ...device, device_type: 'biometric' }), ['staff-attendance']);
  const [y, m] = month.split('-').map(Number);
  const days = new Date(y, m, 0).getDate();
  const grid = useMemo(() => {
    const out = new Map<string, Map<number, string>>();
    for (const r of rows.data?.data ?? []) {
      const key = `${r.employee_id} · ${r.staff_name}`;
      if (!out.has(key)) out.set(key, new Map());
      out.get(key)!.set(Number(r.attendance_date.slice(8, 10)), r.status);
    }
    return out;
  }, [rows.data]);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Staff attendance"
        description="Monthly view per your scope; the LOP column feeds payroll."
        actions={(can('hr', 'manage') || can('attendance', 'manage')) && <Button onClick={() => setMarking(true)}><Plus className="h-4 w-4" /> Mark</Button>}
      />
      <div className="flex flex-wrap items-center gap-2">
        <ScopeTabs visibility={rows.data?.meta.visibility} value={scope} onChange={setScope} labels={{ department: 'Team', faculty: 'Team' }} />
        <Input aria-label="Month" type="month" className="w-44" value={month} onChange={(e) => setMonth(e.target.value)} />
      </div>
      <Tabs defaultValue="grid">
        <TabsList>
          <TabsTrigger value="grid">Monthly grid</TabsTrigger>
          <TabsTrigger value="summary">Summary</TabsTrigger>
          {bio && can('attendance', 'device_manage') && <TabsTrigger value="devices">Devices</TabsTrigger>}
          <TabsTrigger value="regularise">Regularisation</TabsTrigger>
        </TabsList>
        <TabsContent value="grid">
          <div className="overflow-x-auto rounded-md border">
            <table className="text-xs">
              <thead>
                <tr className="bg-muted/50">
                  <th className="sticky left-0 bg-muted px-2 py-1 text-left">Staff</th>
                  {Array.from({ length: days }, (_, i) => <th key={i} className="w-7 px-1 py-1 text-center">{i + 1}</th>)}
                </tr>
              </thead>
              <tbody>
                {[...grid.entries()].map(([who, byDay]) => (
                  <tr key={who} className="border-t">
                    <td className="sticky left-0 whitespace-nowrap bg-card px-2 py-1">{who}</td>
                    {Array.from({ length: days }, (_, i) => {
                      const s = byDay.get(i + 1);
                      const [c, cls] = s ? CODE[s] ?? ['?', ''] : ['', ''];
                      return <td key={i} title={s} className={cn('px-1 py-1 text-center', cls)}>{c}</td>;
                    })}
                  </tr>
                ))}
                {grid.size === 0 && <tr><td colSpan={days + 1} className="px-3 py-6 text-center text-muted-foreground">No attendance marked this month.</td></tr>}
              </tbody>
            </table>
          </div>
        </TabsContent>
        <TabsContent value="summary">
          <SimpleTable head={['Staff', 'Present', 'Absent', 'Leave', 'OD', 'Holiday', 'Week off', 'LOP', 'Unmarked']} rows={(summary.data?.data ?? []).map((r) => [`${r.employee_id} · ${r.staff_name}`, r.present, r.absent, r.on_leave, r.on_duty, r.holiday, r.week_off, <b key="l">{r.lop_days}</b>, r.unmarked])} />
        </TabsContent>
        <TabsContent value="devices" className="space-y-3">
          <SimpleTable head={['Name', 'Type', 'Location', 'Last seen']} rows={(devices.data?.data ?? []).map((d) => [d.name, d.device_type, d.location, d.last_seen_at ? new Date(d.last_seen_at).toLocaleString() : 'never'])} />
          <div className="flex flex-wrap items-end gap-2">
            <FormField label="Device name" value={device.name} onChange={(e) => setDevice({ ...device, name: e.target.value })} />
            <FormField label="Location" value={device.location} onChange={(e) => setDevice({ ...device, location: e.target.value })} />
            <Button disabled={device.name.length < 2} onClick={() => doDevice.mutate(undefined, { onSuccess: (r) => setToken(r.data.token), onError: (e) => toast.error(getApiError(e)) })}>Register device</Button>
          </div>
          {token && <p className="rounded-md border bg-muted p-2 font-mono text-xs">Device token (shown once): {token}</p>}
        </TabsContent>
        <TabsContent value="regularise">
          <div className="flex max-w-xl flex-wrap items-end gap-2">
            <FormField label="Date" type="date" value={reg.date} onChange={(e) => setReg({ ...reg, date: e.target.value })} />
            <label className="space-y-1.5 text-sm font-medium">
              Status
              <Select options={['present', 'half_day', 'on_duty'].map((s) => ({ value: s, label: s }))} value={reg.status} onChange={(e) => setReg({ ...reg, status: e.target.value })} />
            </label>
            <FormField label="Reason" value={reg.reason} onChange={(e) => setReg({ ...reg, reason: e.target.value })} />
            <Button disabled={!reg.date || reg.reason.length < 3} onClick={() => doReg.mutate(undefined, { onSuccess: () => toast.success('Sent to your HOD for approval'), onError: (e) => toast.error(getApiError(e)) })}>Request</Button>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">Requests go through the attendance.regularise workflow; approvers act from the Approvals inbox.</p>
        </TabsContent>
      </Tabs>

      <Modal open={marking} onOpenChange={setMarking} title="Mark attendance" footer={<Button loading={doMark.isPending} disabled={!mark.staff_id || !mark.date} onClick={() => doMark.mutate(undefined, { onSuccess: () => { toast.success('Saved'); setMarking(false); }, onError: (e) => toast.error(getApiError(e)) })}>Save</Button>}>
        <div className="grid gap-3 sm:grid-cols-3">
          <label className="space-y-1.5 text-sm font-medium sm:col-span-3">
            Staff
            <Select placeholder="Select…" options={(staff.data?.data ?? []).map((s) => ({ value: s.id, label: `${s.employee_id} · ${s.full_name}` }))} value={mark.staff_id} onChange={(e) => setMark({ ...mark, staff_id: e.target.value })} />
          </label>
          <FormField label="Date" type="date" value={mark.date} onChange={(e) => setMark({ ...mark, date: e.target.value })} />
          <label className="space-y-1.5 text-sm font-medium">
            Status
            <Select options={Object.keys(CODE).map((s) => ({ value: s, label: s }))} value={mark.status} onChange={(e) => setMark({ ...mark, status: e.target.value })} />
          </label>
        </div>
      </Modal>
    </div>
  );
}
