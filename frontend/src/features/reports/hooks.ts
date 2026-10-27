import { useState } from 'react';
import { getApiError } from '@/api/axios';
import { toast } from '@/components/ui/Toaster';
import { repApi, type ReportFormat } from './api';

/**
 * `useReportRun()` — queue `POST /reports/run` as a job; progress and the download arrive in the JobsTray.
 * DataTable "Export" buttons call it with the page's current filters (`key = <module>.list_export`); `allowed` keeps
 * only the filters the report declares (the API rejects unknown parameters with 422).
 */
export function useReportRun() {
  const [busy, setBusy] = useState(false);
  const run = async (key: string, params: Record<string, unknown> = {}, format: ReportFormat = 'xlsx', allowed?: string[]) => {
    const clean = Object.fromEntries(
      Object.entries(params).filter(([k, v]) => v !== undefined && v !== null && v !== '' && (!allowed || allowed.includes(k))),
    );
    setBusy(true);
    try {
      const r = await repApi.run({ key, params: clean, format });
      toast.success(`Report queued (job ${String(r.data?.job_id ?? '').slice(0, 8)}) — the file arrives in the jobs tray`);
      return r.data;
    } catch (e) {
      toast.error(getApiError(e));
      return undefined;
    } finally {
      setBusy(false);
    }
  };
  return { run, busy };
}
