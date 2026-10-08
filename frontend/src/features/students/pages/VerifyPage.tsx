import { useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { BadgeCheck, ShieldX } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/Card';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { formatDate } from '@/utils/formatters';
import { studentsApi } from '../api';
import { label } from '../types';

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
          {r && valid ? (
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
