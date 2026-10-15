import { useEffect, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { Upload } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs';
import { toast } from '@/components/ui/Toaster';
import { useFeature } from '@/hooks/useFeature';
import { usePermission } from '@/hooks/usePermission';
import { admissionsApi } from '../api';
import {
  ApplicantsTable,
  ImportModal,
  MeritTab,
  OffersTab,
  ProgramsTab,
  RoundsTab,
  SeatHeatmap,
  SeatMatrixTab,
  VerificationQueue,
} from '../components/workspace';
import { useAdmissionsMutation, useCycle, useSeatStatus } from '../hooks';
import { CYCLE_NEXT, label, rupees } from '../types';

/** /admin/admissions/cycles/:id — Programmes & intake | Seat matrix | Applicants | Verification | Merit lists |
 * Counselling rounds | Offers | Seat status. */
export default function CycleWorkspacePage() {
  const { id } = useParams();
  const [search, setSearch] = useSearchParams();
  const { can } = usePermission();
  const cycle = useCycle(id);
  const seats = useSeatStatus(id);
  const [importing, setImporting] = useState(false);
  const status = useAdmissionsMutation((s: string) => admissionsApi.cycleStatus(id!, s));
  const counsellingOn = useFeature('admissions.counselling_allotment');
  const meritOn = useFeature('admissions.merit_lists');
  const importOn = useFeature('admissions.entrance_import');
  const c = cycle.data?.data;
  useEffect(() => {
    document.title = c ? `${c.name} — admissions` : 'Admission cycle';
  }, [c]);
  if (!c) return <p className="text-sm text-muted-foreground">{cycle.isError ? getApiError(cycle.error) : 'Loading…'}</p>;
  const manage = can('admissions', 'manage');
  const editable = manage && !['completed', 'archived'].includes(c.status);
  const tab = search.get('tab') ?? 'programs';
  const move = async (s: string) => {
    try {
      await status.mutateAsync(s);
      toast.success(`Cycle ${label(s)}`);
    } catch (e) {
      toast.error(getApiError(e));
    }
  };
  return (
    <div className="space-y-4">
      <PageHeader
        title={c.name}
        description={`${label(c.level)} · application fee ${rupees(c.application_fee_paise)} · ${c.applicants_count} applicants · intake ${c.intake_total}`}
        breadcrumbs={[{ label: 'Admission cycles', to: '/admin/admissions/cycles' }, { label: c.name }]}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={c.status} />
            {manage && (CYCLE_NEXT[c.status] ?? []).map((s) => (
              <Button key={s} size="sm" variant={s === 'open' ? 'default' : 'outline'} disabled={status.isPending} onClick={() => move(s)}>{label(s)}</Button>
            ))}
            {importOn && can('admissions', 'import') && (
              <Button size="sm" variant="outline" onClick={() => setImporting(true)}><Upload className="h-4 w-4" /> Import CSV</Button>
            )}
          </div>
        }
      />
      {seats.data && seats.data.data.programs.some((p) => !p.balanced) && (
        <Card><CardContent className="pt-4 text-sm text-amber-700 sm:pt-4">The seat matrix does not match the intake for {seats.data.data.programs.filter((p) => !p.balanced).map((p) => p.program_code).join(', ')} — the cycle cannot open until Σ seats = intake + lateral intake.</CardContent></Card>
      )}
      <Tabs value={tab} onValueChange={(v) => setSearch({ tab: v }, { replace: true })}>
        <TabsList className="flex-wrap">
          <TabsTrigger value="programs">Programmes &amp; intake</TabsTrigger>
          <TabsTrigger value="seats">Seat matrix</TabsTrigger>
          <TabsTrigger value="applicants">Applicants</TabsTrigger>
          <TabsTrigger value="verification">Verification queue</TabsTrigger>
          {meritOn && <TabsTrigger value="merit">Merit lists</TabsTrigger>}
          {counsellingOn && <TabsTrigger value="rounds">Counselling rounds</TabsTrigger>}
          <TabsTrigger value="offers">Offers</TabsTrigger>
          <TabsTrigger value="status">Seat status</TabsTrigger>
        </TabsList>
        <TabsContent value="programs"><ProgramsTab cycleId={c.id} editable={editable} /></TabsContent>
        <TabsContent value="seats"><SeatMatrixTab cycleId={c.id} editable={editable} /></TabsContent>
        <TabsContent value="applicants"><ApplicantsTable cycleId={c.id} /></TabsContent>
        <TabsContent value="verification"><VerificationQueue cycleId={c.id} /></TabsContent>
        {meritOn && <TabsContent value="merit"><MeritTab cycleId={c.id} /></TabsContent>}
        {counsellingOn && <TabsContent value="rounds"><RoundsTab cycleId={c.id} /></TabsContent>}
        <TabsContent value="offers"><OffersTab cycleId={c.id} /></TabsContent>
        <TabsContent value="status"><SeatHeatmap data={seats.data?.data} /></TabsContent>
      </Tabs>
      <ImportModal cycleId={c.id} open={importing} onOpenChange={setImporting} />
    </div>
  );
}
