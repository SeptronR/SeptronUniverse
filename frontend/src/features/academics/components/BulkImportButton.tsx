import { useState } from 'react';
import { Upload } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { Button } from '@/components/ui/Button';
import { Textarea } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { academicsApi } from '../api';

const HEADER = 'code,title,type,L,T,P,credits,department_code,scheme_code';

/** CSV bulk import → background job ``courses.bulk_import`` (progress and the report appear in the jobs tray). */
export function BulkImportButton({ regulationId }: { regulationId: string }) {
  const [open, setOpen] = useState(false);
  const [csv, setCsv] = useState(`${HEADER}\n`);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      const r = await academicsApi.bulkImport(regulationId, csv);
      toast.success(`Import queued (job ${r.data.job_id.slice(0, 8)}) — the report arrives in the jobs tray`);
      setOpen(false);
    } catch (e) {
      toast.error(getApiError(e));
    } finally {
      setBusy(false);
    }
  };
  const onFile = async (f: File | undefined) => f && setCsv(await f.text());
  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)}>
        <Upload className="h-4 w-4" /> Bulk import
      </Button>
      <Modal
        open={open}
        onOpenChange={setOpen}
        size="lg"
        title="Bulk import courses"
        description={`CSV columns: ${HEADER}. Rows are imported one by one — the report lists every failed row with its reason.`}
        footer={<Button onClick={submit} loading={busy} disabled={csv.trim().split('\n').length < 2}>Queue import</Button>}
      >
        <div className="space-y-2">
          <input type="file" accept=".csv,text/csv" aria-label="CSV file" onChange={(e) => onFile(e.target.files?.[0])} className="text-sm" />
          <Textarea aria-label="CSV" rows={12} className="font-mono text-xs" value={csv} onChange={(e) => setCsv(e.target.value)} />
        </div>
      </Modal>
    </>
  );
}
