import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { Ban, ShieldAlert } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { formatDate } from '@/utils/formatters';
import { STANDING_VARIANT, label, type Hold } from '../types';

/** Academic standing chip (good / warning / probation / dismissal). */
export function StandingChip({ standing }: { standing: string | null | undefined }) {
  if (!standing) return <span className="text-muted-foreground">—</span>;
  return <Badge variant={STANDING_VARIANT[standing] ?? 'outline'}>{label(standing)}</Badge>;
}

/** Open-holds counter shown in lists / headers. */
export function HoldsBadge({ count }: { count: number }) {
  if (!count) return null;
  return (
    <Badge variant="destructive" className="gap-1">
      <Ban className="h-3 w-3" /> {count} hold{count > 1 ? 's' : ''}
    </Badge>
  );
}

/** Banner listing open holds with reason and who placed them — the student / parent portals and the 360° header. */
export function HoldBanner({ holds, contact }: { holds: Hold[]; contact?: ReactNode }) {
  const open = holds.filter((h) => h.is_open);
  if (!open.length) return null;
  return (
    <div role="alert" className="rounded-md border border-status-rejected/40 bg-status-rejected/10 p-3 text-sm">
      <p className="flex items-center gap-2 font-semibold text-status-rejected">
        <ShieldAlert className="h-4 w-4" /> {open.length} active hold{open.length > 1 ? 's' : ''}
      </p>
      <ul className="mt-1 space-y-0.5">
        {open.map((h) => (
          <li key={h.id}>
            <span className="font-medium">{label(h.hold_type)}</span> — {h.reason}
            <span className="text-muted-foreground"> · placed {formatDate(h.placed_at)}{h.placed_by_name ? ` by ${h.placed_by_name}` : ''}</span>
          </li>
        ))}
      </ul>
      {contact && <p className="mt-1 text-muted-foreground">{contact}</p>}
    </div>
  );
}

export function Field({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{k}</dt>
      <dd className="break-words text-sm">{v === '' || v === null || v === undefined ? '—' : v}</dd>
    </div>
  );
}

export function StudentLink({ id, children }: { id: string | null; children: ReactNode }) {
  if (!id) return <>{children}</>;
  return (
    <Link className="text-primary hover:underline" to={`/admin/students/${id}`}>
      {children}
    </Link>
  );
}
