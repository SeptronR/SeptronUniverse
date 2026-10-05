import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { FileDown, LogIn, LogOut, Plus } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { FormField } from '@/components/shared/FormField';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent, CardHeader, CardTitle, StatCard } from '@/components/ui/Card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs';
import { toast } from '@/components/ui/Toaster';
import { useFeature } from '@/hooks/useFeature';
import { hrApi } from '../api';
import { LeaveApplyModal, SimpleTable } from '../components/shared';
import { downloadBlob } from '../download';
import { useHrMutation, useLeaves, useMyBalance, useMyPayslips, useMyStaff } from '../hooks';
import { MONTHS, inr, num, localDate } from '../types';

const geo = () =>
  new Promise<{ lat: number; lng: number; accuracy_m?: number } | undefined>((resolve) => {
    if (!navigator.geolocation) return resolve(undefined);
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude, accuracy_m: p.coords.accuracy }),
      () => resolve(undefined),
      { enableHighAccuracy: true, timeout: 10_000 },
    );
  });

/** /me — My profile, leaves (apply, balances, history), attendance (self check-in with geo), payslips, appraisal. */
export default function MySpacePage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get('tab') ?? 'profile';
  const me = useMyStaff();
  const balance = useMyBalance();
  const leaves = useLeaves({ scope: 'self', page_size: 50 });
  const payslips = useMyPayslips();
  const month = localDate().slice(0, 7);
  const att = useQuery({ queryKey: ['staff-attendance', { scope: 'self', month }], queryFn: () => hrApi.attendance({ scope: 'self', month, page_size: 31 }) });
  const geoOn = useFeature('attendance.geo_app');
  const [applying, setApplying] = useState(false);
  const [phone, setPhone] = useState('');
  const cancel = useHrMutation((id: string) => hrApi.cancelLeave(id), ['leaves']);
  const checkIn = useHrMutation(async () => hrApi.checkIn(geoOn ? await geo() : undefined), ['staff-attendance']);
  const checkOut = useHrMutation(() => hrApi.checkOut(), ['staff-attendance']);
  const save = useHrMutation(() => hrApi.updateMe({ phone }), ['staff']);

  if (me.isError) {
    return (
      <div className="space-y-4">
        <PageHeader title="My space" />
        <p className="text-sm text-muted-foreground">{getApiError(me.error)}</p>
      </div>
    );
  }
  const s = me.data?.data;
  const today = localDate();
  const todayRow = att.data?.data.find((r) => r.attendance_date === today);
  return (
    <div className="space-y-4">
      <PageHeader title="My space" description={s ? `${s.full_name} · ${s.employee_id} · ${s.designation_name ?? ''}` : ''} />
      <Tabs value={tab} onValueChange={(t) => setParams({ tab: t })}>
        <TabsList>
          <TabsTrigger value="profile">My profile</TabsTrigger>
          <TabsTrigger value="leaves">My leaves</TabsTrigger>
          <TabsTrigger value="attendance">My attendance</TabsTrigger>
          <TabsTrigger value="payslips">My payslips</TabsTrigger>
        </TabsList>
        <TabsContent value="profile">
          <Card>
            <CardContent className="grid gap-3 pt-4 sm:grid-cols-3">
              <div className="text-sm">Department<br /><b>{s?.department_code ?? '—'}</b></div>
              <div className="text-sm">PAN<br /><b>{s?.pan ?? '—'}</b></div>
              <div className="text-sm">E-mail<br /><b>{s?.email ?? '—'}</b></div>
              <div className="flex items-end gap-2 sm:col-span-3">
                <FormField label="Phone" placeholder={s?.phone ?? ''} value={phone} onChange={(e) => setPhone(e.target.value)} />
                <Button disabled={!phone} loading={save.isPending} onClick={() => save.mutate(undefined, { onSuccess: () => toast.success('Phone updated'), onError: (e) => toast.error(getApiError(e)) })}>Save</Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="leaves" className="space-y-3">
          <div className="flex justify-end">
            <Button onClick={() => setApplying(true)}><Plus className="h-4 w-4" /> Apply for leave</Button>
          </div>
          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {(balance.data?.data ?? []).filter((b) => b.available !== null).map((b) => (
              <StatCard key={b.code} label={`${b.code} · ${b.name}`} value={num(b.available)} hint={`balance ${num(b.balance)} · used ${num(b.used)} · pending ${num(b.pending)}`} />
            ))}
          </div>
          <SimpleTable
            head={['Type', 'From', 'To', 'Days', 'Status', '']}
            rows={(leaves.data?.data ?? []).map((l) => [
              l.leave_type_code,
              l.from_date,
              l.to_date,
              num(l.days_count),
              <StatusBadge key="s" status={l.status} />,
              (l.status === 'pending' || (l.status === 'approved' && l.from_date > today)) && (
                <Button key="c" size="sm" variant="outline" onClick={() => cancel.mutate(l.id, { onSuccess: () => toast.success('Leave cancelled'), onError: (e) => toast.error(getApiError(e)) })}>Cancel</Button>
              ),
            ])}
          />
          <LeaveApplyModal open={applying} onOpenChange={setApplying} />
        </TabsContent>
        <TabsContent value="attendance" className="space-y-3">
          <Card>
            <CardHeader><CardTitle className="text-base">Today</CardTitle></CardHeader>
            <CardContent className="flex flex-wrap items-center gap-3">
              <span className="text-sm">{todayRow ? `${todayRow.status}${todayRow.check_in_time ? ` · in ${new Date(todayRow.check_in_time).toLocaleTimeString()}` : ''}${todayRow.check_out_time ? ` · out ${new Date(todayRow.check_out_time).toLocaleTimeString()}` : ''}` : 'Not checked in'}</span>
              <Button disabled={!!todayRow?.check_in_time} loading={checkIn.isPending} onClick={() => checkIn.mutate(undefined, { onSuccess: () => toast.success('Checked in'), onError: (e) => toast.error(getApiError(e)) })}>
                <LogIn className="h-4 w-4" /> Check in{geoOn ? ' (location)' : ''}
              </Button>
              <Button variant="outline" disabled={!todayRow?.check_in_time || !!todayRow?.check_out_time} onClick={() => checkOut.mutate(undefined, { onSuccess: () => toast.success('Checked out'), onError: (e) => toast.error(getApiError(e)) })}>
                <LogOut className="h-4 w-4" /> Check out
              </Button>
            </CardContent>
          </Card>
          <SimpleTable head={['Date', 'Status', 'In', 'Out', 'Source']} rows={(att.data?.data ?? []).map((r) => [r.attendance_date, <StatusBadge key="s" status={r.status} />, r.check_in_time ? new Date(r.check_in_time).toLocaleTimeString() : '—', r.check_out_time ? new Date(r.check_out_time).toLocaleTimeString() : '—', r.source])} />
        </TabsContent>
        <TabsContent value="payslips">
          <SimpleTable
            head={['Period', 'Gross', 'Deductions', 'Net', 'Status', '']}
            rows={(payslips.data?.data ?? []).map((p) => [
              `${MONTHS[p.month - 1]} ${p.year}`,
              inr(p.gross_paise),
              inr(p.deductions_paise),
              <b key="n">{inr(p.net_paise)}</b>,
              <StatusBadge key="s" status={p.status} />,
              <Button key="d" size="sm" variant="outline" onClick={async () => { try { downloadBlob(await hrApi.payslip(p.id), `payslip-${p.year}-${p.month}.pdf`, true); } catch (e) { toast.error(getApiError(e)); } }}>
                <FileDown className="h-4 w-4" /> Payslip
              </Button>,
            ])}
            empty="No approved payslips yet."
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
