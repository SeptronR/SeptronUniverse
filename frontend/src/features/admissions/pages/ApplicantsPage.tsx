import { useEffect, useMemo, useState } from 'react';
import { PageHeader } from '@/components/shared/PageHeader';
import { Select } from '@/components/ui/Input';
import { ApplicantsTable, VerificationQueue } from '../components/workspace';
import { useCycles } from '../hooks';

function CyclePicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const cycles = useCycles();
  const list = useMemo(() => cycles.data?.data ?? [], [cycles.data]);
  useEffect(() => {
    if (!value && list.length) onChange((list.find((c) => c.status === 'open') ?? list.find((c) => c.status !== 'archived') ?? list[0]).id);
  }, [value, list, onChange]);
  return (
    <Select className="w-64" aria-label="Cycle" options={list.map((c) => ({ value: c.id, label: `${c.name} (${c.status})` }))} value={value} onChange={(e) => onChange(e.target.value)} />
  );
}

/** /admin/admissions/applicants — applicants across a cycle with scope tabs (Mine | Department | College | All). */
export default function ApplicantsPage() {
  const [cycle, setCycle] = useState('');
  useEffect(() => {
    document.title = 'Applicants';
  }, []);
  return (
    <div className="space-y-4">
      <PageHeader title="Applicants" description="Search, filter and open applications; HODs see applicants preferring their department's programmes." actions={<CyclePicker value={cycle} onChange={setCycle} />} />
      {cycle && <ApplicantsTable key={cycle} cycleId={cycle} />}
    </div>
  );
}

/** /admin/admissions/verification — document verification queue with a side-by-side viewer. */
export function VerificationPage() {
  const [cycle, setCycle] = useState('');
  useEffect(() => {
    document.title = 'Document verification';
  }, []);
  return (
    <div className="space-y-4">
      <PageHeader title="Verification queue" description="Verify, reject or ask for a resubmission per document; the applicant is notified." actions={<CyclePicker value={cycle} onChange={setCycle} />} />
      {cycle && <VerificationQueue key={cycle} cycleId={cycle} />}
    </div>
  );
}

export { CyclePicker };
