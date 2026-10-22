import { useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { BadgeCheck, ShieldX } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/Card';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { formatDate } from '@/utils/formatters';
import { studentsApi } from '../api';
import { label } from '../types';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;

/** /verify/:token — public verification of a student ID card / document QR (no sign-in). */
export default function VerifyPage() {
  const { token = '' } = useParams();
  const q = useQuery({ queryKey: ['verify', token], queryFn: () => studentsApi.verify(token), retry: false });
  if (q.isLoading) return <PageSkeleton />;
  const r = q.data?.data;
  const valid = !!r?.valid;
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardContent className="space-y-3 pt-6 sm:pt-6 text-center">
          {valid ? <BadgeCheck className="mx-auto h-12 w-12 text-status-approved" /> : <ShieldX className="mx-auto h-12 w-12 text-status-rejected" />}
          <h1 className="text-lg font-semibold">{valid ? `Valid ${label(r?.document_type)}` : 'Not valid'}</h1>
          {r && valid && r.document_type === 'grade_card' ? (
            <dl className="grid grid-cols-2 gap-2 text-left text-sm">
              <dt className="text-muted-foreground">Grade card</dt><dd className="font-mono">{(r as Any).document_number}</dd>
              <dt className="text-muted-foreground">Name</dt><dd>{r.holder_name}</dd>
              <dt className="text-muted-foreground">Registration no.</dt><dd className="font-mono">{r.registration_number}</dd>
              <dt className="text-muted-foreground">Term</dt><dd>{(r as Any).term_number}</dd>
              <dt className="text-muted-foreground">SGPA / CGPA</dt><dd>{(r as Any).sgpa ?? '—'} / {(r as Any).cgpa ?? '—'}</dd>
              <dt className="text-muted-foreground">Result hash</dt><dd className="break-all font-mono text-xs">{(r as Any).hash}</dd>
              <dt className="text-muted-foreground">Institution</dt><dd>{r.institution}</dd>
              {(r as Any).superseded && <dd className="col-span-2 text-status-pending">Superseded by a revised grade card</dd>}
            </dl>
          ) : r && valid ? (
            <dl className="grid grid-cols-2 gap-2 text-left text-sm">
              <dt className="text-muted-foreground">Name</dt><dd>{r.holder_name}</dd>
              <dt className="text-muted-foreground">Registration no.</dt><dd className="font-mono">{r.registration_number}</dd>
              <dt className="text-muted-foreground">Programme</dt><dd>{r.program ?? '—'}</dd>
              <dt className="text-muted-foreground">Status</dt><dd>{label(r.status)}</dd>
              <dt className="text-muted-foreground">Institution</dt><dd>{r.institution}{r.college ? ` · ${r.college}` : ''}</dd>
              <dt className="text-muted-foreground">Valid until</dt><dd>{formatDate(r.valid_until)}</dd>
            </dl>
          ) : (
            <p className="text-sm text-muted-foreground">{r?.message ?? 'This code could not be verified. It may be expired or tampered with.'}</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
