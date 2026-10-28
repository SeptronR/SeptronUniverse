/* eslint-disable react-refresh/only-export-components */
import { useEffect, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { getApiError } from '@/api/axios';
import { Card, CardContent } from '@/components/ui/Card';
import { toast } from '@/components/ui/Toaster';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Any = any;
export const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
export const fail = (e: unknown) => toast.error(getApiError(e));
export const useQ = <T,>(key: unknown[], fn: () => Promise<T>, enabled = true, refetchInterval: number | false = false) =>
  useQuery({ queryKey: ['saas', ...key], queryFn: fn, retry: false, enabled, refetchInterval });
export function useRun(success?: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (fn: () => Promise<unknown>) => fn(),
    onSuccess: () => {
      if (success) toast.success(success);
      qc.invalidateQueries({ queryKey: ['saas'] });
    },
    onError: fail,
  });
}
export const rows = (r: Any): Any[] => (Array.isArray(r?.data) ? r.data : Array.isArray(r?.data?.items) ? r.data.items : []);
export const sel = 'h-9 rounded-md border bg-background px-2 text-sm';
export const dt = (v: unknown) => (v ? new Date(String(v)).toLocaleString() : '—');
export const d = (v: unknown) => (v ? new Date(String(v)).toLocaleDateString() : '—');
export const inr = (paise: unknown) => `₹ ${(Number(paise ?? 0) / 100).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
export const show = (v: unknown) => (v === null || v === undefined ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v));

export function Section({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">{title}</h2>
          {action}
        </div>
        {children}
      </CardContent>
    </Card>
  );
}
export function Err({ q }: { q: Any }) {
  return q.isError ? <p className="text-sm text-destructive">{getApiError(q.error)}</p> : null;
}
export function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: 'warn' | 'bad' }) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className={`text-xl font-semibold ${tone === 'bad' ? 'text-destructive' : tone === 'warn' ? 'text-warning' : ''}`}>{value}</p>
      </CardContent>
    </Card>
  );
}
/** Minimal horizontal bar list for chart series ({label, value}) — the platform dashboard's charts. */
export function Bars({ points }: { points: { label: string; value: number }[] }) {
  const max = Math.max(1, ...points.map((p) => p.value));
  return (
    <div className="space-y-1">
      {points.map((p) => (
        <div key={p.label} className="flex items-center gap-2 text-xs">
          <span className="w-24 truncate">{p.label}</span>
          <div className="h-2 flex-1 rounded bg-muted">
            <div className="h-2 rounded bg-primary" style={{ width: `${(p.value * 100) / max}%` }} />
          </div>
          <span className="w-20 text-right tabular-nums">{p.value.toLocaleString('en-IN')}</span>
        </div>
      ))}
    </div>
  );
}
