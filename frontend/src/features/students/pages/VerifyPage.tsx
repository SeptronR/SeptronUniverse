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
          <h1 className="text-lg font-semibold">{valid ? `Valid ${label(r?.document_type ?? (r as Any)?.entity_type)}` : 'Not valid'}</h1>
          {r && ['degree', 'provisional_certificate'].includes((r as Any).entity_type) ? (
            // Phase 18 — degree / provisional certificate tokens (masked holder; revoked / superseded states)
            <dl className="grid grid-cols-2 gap-2 text-left text-sm">
              <dt className="text-muted-foreground">Holder</dt><dd>{(r as Any).holder_masked ?? '—'}</dd>
              {Object.entries((r as Any).award ?? {}).filter(([, v]) => v !== null && v !== undefined).map(([k, v]) => (
                <div key={k} className="contents"><dt className="text-muted-foreground">{label(k)}</dt><dd>{String(v)}</dd></div>
              ))}
              <dt className="text-muted-foreground">Institution</dt><dd>{(r as Any).institution ?? '—'}</dd>
              <dt className="text-muted-foreground">Hash</dt><dd className="break-all font-mono text-xs">{(r as Any).hash}</dd>
              {(r as Any).revoked && <dd className="col-span-2 text-status-rejected">Revoked {(r as Any).message ?? ''}</dd>}
              {(r as Any).superseded && <dd className="col-span-2 text-status-pending">{(r as Any).version_note ?? 'Superseded by a newer version'}</dd>}
            </dl>
          ) : r && valid && r.document_type === 'grade_card' ? (
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
