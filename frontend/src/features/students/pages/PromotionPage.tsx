import { useState } from 'react';
import { ArrowRight, Play } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Select } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { useBatches, usePrograms } from '@/features/academics/hooks';
import { SimpleTable } from '@/features/hr/components/shared';
import { studentsApi } from '../api';
import { StudentLink } from '../components/shared';
import { useStudentMutation } from '../hooks';
import type { PromotionPreview, PromotionRow } from '../types';

const rowsOf = (rows: PromotionRow[], reason?: (r: PromotionRow) => string) =>
  rows.map((r) => [<StudentLink key="l" id={r.student_id}>{r.registration_number}</StudentLink>, r.name, r.section_name ?? '—', r.backlogs, reason ? reason(r) : '']);

/** /admin/students/promotion — batch picker → dry-run preview (promoted / detained with reasons / on break) → confirm
 *  queues `students.promote`; progress shows in the jobs tray. Re-running is idempotent. */
export default function PromotionPage() {
  const [programId, setProgramId] = useState('');
  const [batchId, setBatchId] = useState('');
  const [preview, setPreview] = useState<PromotionPreview | null>(null);
  const [confirm, setConfirm] = useState(false);
  const programs = usePrograms({ page_size: 200 });
  const batches = useBatches({ page_size: 100, program_id: programId || undefined, status: 'active' });
  const dry = useStudentMutation(() => studentsApi.promote(batchId, true), []);
  const run = useStudentMutation(() => studentsApi.promote(batchId, false), ['students', 'batches']);
  const load = () => dry.mutate(undefined, { onSuccess: (r) => setPreview(r.data), onError: (e) => toast.error(getApiError(e)) });

  return (
    <div className="space-y-4">
      <PageHeader title="Promotion" description="Move a batch to its next term. Students over the backlog limit are detained; students on break stay where they are." />
      <div className="flex flex-wrap items-end gap-2">
        <Select className="w-48" aria-label="Programme" placeholder="All programmes" options={(programs.data?.data ?? []).map((p) => ({ value: p.id, label: p.code }))} value={programId} onChange={(e) => { setProgramId(e.target.value); setBatchId(''); setPreview(null); }} />
        <Select className="w-56" aria-label="Batch" placeholder="Choose a batch…" options={(batches.data?.data ?? []).map((b) => ({ value: b.id, label: `${b.code} · term ${b.current_term_number}` }))} value={batchId} onChange={(e) => { setBatchId(e.target.value); setPreview(null); }} />
        <Button disabled={!batchId} loading={dry.isPending} onClick={load}>Preview (dry run)</Button>
      </div>
      {preview && (
        <>
          <Card>
            <CardContent className="flex flex-wrap items-center gap-3 pt-4 sm:pt-4 text-sm">
              <span className="font-semibold">{preview.batch_code}</span>
              <span>term {preview.from_term_number}</span>
              <ArrowRight className="h-4 w-4" />
              <span>term {preview.to_term_number}</span>
              <Badge variant="success">{preview.promoted.length} promoted</Badge>
              <Badge variant="destructive">{preview.detained.length} detained</Badge>
              <Badge variant="secondary">{preview.on_break.length} on break</Badge>
              {preview.already_promoted > 0 && <Badge variant="info">{preview.already_promoted} already promoted</Badge>}
              <span className="text-muted-foreground">backlog limit {preview.max_backlogs}</span>
              <Button className="ml-auto" disabled={!!preview.blocking || preview.promoted.length + preview.detained.length === 0} onClick={() => setConfirm(true)}>
                <Play className="h-4 w-4" /> Run promotion
              </Button>
            </CardContent>
          </Card>
          {preview.blocking && <p role="alert" className="text-sm text-destructive">{preview.blocking}</p>}
          <h3 className="text-sm font-semibold">Detained</h3>
          <SimpleTable head={['Reg. no', 'Name', 'Section', 'Backlogs', 'Reason']} rows={rowsOf(preview.detained, (r) => `${r.backlogs} backlogs > ${preview.max_backlogs} allowed`)} empty="Nobody is detained." />
          <h3 className="text-sm font-semibold">On break (not moved)</h3>
          <SimpleTable head={['Reg. no', 'Name', 'Section', 'Backlogs', '']} rows={rowsOf(preview.on_break)} empty="Nobody is on break." />
          <h3 className="text-sm font-semibold">Promoted</h3>
          <SimpleTable head={['Reg. no', 'Name', 'Section', 'Backlogs', '']} rows={rowsOf(preview.promoted)} empty="Nobody to promote." />
        </>
      )}
      <Modal
        open={confirm}
        onOpenChange={setConfirm}
        title="Run promotion?"
        description={preview ? `${preview.promoted.length} students move to term ${preview.to_term_number}; ${preview.detained.length} are detained. Runs as a background job.` : ''}
        footer={
          <Button
            loading={run.isPending}
            onClick={() =>
              run.mutate(undefined, {
                onSuccess: (r) => {
                  toast.success(`Promotion queued (job ${r.data.job_id?.slice(0, 8)}) — follow it in the jobs tray`);
                  setConfirm(false);
                  setPreview(null);
                },
                onError: (e) => toast.error(getApiError(e)),
              })
            }
          >
            Confirm
          </Button>
        }
      >
        <p className="text-sm text-muted-foreground">Students already in the target term are skipped, so running it again is safe.</p>
      </Modal>
    </div>
  );
}
