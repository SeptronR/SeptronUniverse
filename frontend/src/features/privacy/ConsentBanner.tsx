import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Switch } from '@/components/ui/Switch';
import { toast } from '@/components/ui/Toaster';
import { useQ, type Any } from '@/features/saas/components/kit';
import { privacyApi } from './api';

/** DPDP consent banner (Prompts/43 §43.9): shown on first sign-in and whenever the notice / purpose versions change.
 * Mandatory purposes are informational; optional ones are toggles. Minors see the optional purposes read-only (their
 * guardian records them). Rendered by the admin and portal layouts. */
export function ConsentBanner() {
  const q = useQ(['consent-banner'], () => privacyApi.banner());
  const data: Any = q.data?.data;
  const [grants, setGrants] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (data) setGrants(Object.fromEntries(data.purposes.map((p: Any) => [p.key, p.mandatory || Boolean(data.current?.[p.key])])));
  }, [data]);
  if (!data?.requires_update) return null;
  const save = async () => {
    setBusy(true);
    try {
      const body = data.is_minor ? Object.fromEntries(data.purposes.filter((p: Any) => p.mandatory).map((p: Any) => [p.key, true])) : grants;
      await privacyApi.bulk(body, data.notice_version);
      toast.success('Privacy preferences saved');
      q.refetch();
    } catch {
      toast.error('Could not save your choices');
    } finally {
      setBusy(false);
    }
  };
  return (
    <div role="dialog" aria-modal="true" aria-labelledby="consent-title" className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-4 sm:items-center">
      <div className="max-h-[90vh] w-full max-w-lg overflow-auto rounded-lg bg-background p-5 shadow-xl">
        <h2 id="consent-title" className="text-lg font-semibold">Your privacy choices</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          We process personal data under the Digital Personal Data Protection Act, 2023 (notice v{data.notice_version}). Choose what you allow; you can
          change this any time under Profile › Privacy.
        </p>
        {data.is_minor && <p className="mt-2 rounded bg-muted p-2 text-sm">You are under 18 — your parent or guardian records the optional choices.</p>}
        <ul className="mt-4 space-y-3">
          {data.purposes.map((p: Any) => (
            <li key={p.key} className="flex items-start gap-3">
              <Switch
                checked={grants[p.key] ?? false}
                disabled={p.mandatory || data.is_minor}
                onCheckedChange={(v) => setGrants({ ...grants, [p.key]: v })}
                aria-label={p.key.replaceAll('_', ' ')}
              />
              <div className="text-sm">
                <div className="font-medium">{p.key.replaceAll('_', ' ')}{p.mandatory && <span className="ml-2 text-xs text-muted-foreground">required</span>}</div>
                <div className="text-muted-foreground">{p.texts?.en}</div>
              </div>
            </li>
          ))}
        </ul>
        <div className="mt-5 flex justify-end gap-2">
          <Button onClick={save} disabled={busy}>Save choices</Button>
        </div>
      </div>
    </div>
  );
}
