import { cn } from '@/utils/cn';

/** Credit load of a term against its min / normal / max band (the bar spans 0 … max + 25 %). */
export function CreditMeter({ load, min, normal, max }: { load: number; min: number; normal: number; max: number }) {
  const span = Math.max(max * 1.25, load, 1);
  const pct = (v: number) => `${Math.min(100, (v / span) * 100)}%`;
  const tone = load > max ? 'bg-status-rejected' : load < min ? 'bg-status-pending' : 'bg-status-approved';
  return (
    <div className="space-y-1" aria-label={`${load} credits (min ${min}, normal ${normal}, max ${max})`}>
      <div className="relative h-2 rounded-full bg-muted">
        <div className={cn('absolute inset-y-0 left-0 rounded-full', tone)} style={{ width: pct(load) }} />
        <div className="absolute inset-y-[-3px] w-px bg-foreground/60" style={{ left: pct(min) }} title={`min ${min}`} />
        <div className="absolute inset-y-[-3px] w-px bg-foreground" style={{ left: pct(normal) }} title={`normal ${normal}`} />
        <div className="absolute inset-y-[-3px] w-px bg-foreground/60" style={{ left: pct(max) }} title={`max ${max}`} />
      </div>
      <p className="text-xs text-muted-foreground">
        <span className="font-medium text-foreground">{load}</span> credits · {min}–{max} (normal {normal})
      </p>
    </div>
  );
}
