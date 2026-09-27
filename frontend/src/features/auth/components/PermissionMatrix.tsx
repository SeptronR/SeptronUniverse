import { useMemo, useState } from 'react';
import { getApiError } from '@/api/axios';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Checkbox } from '@/components/ui/Switch';
import { TableSkeleton } from '@/components/ui/Skeleton';
import { toast } from '@/components/ui/Toaster';
import { useReadOnly } from '@/features/platform/hooks';
import { titleCase } from '@/utils/formatters';
import { useRoleMatrix, useSetRoleMatrix } from '../hooks';
import type { Role } from '../types';

/**
 * Permission matrix: rows = modules, columns = the module's actions. Only the changed cells are sent (the API
 * applies a partial update and audits the diff); the diff preview lists them before saving.
 */
export function PermissionMatrix({ role, onSaved }: { role: Role; onSaved?: () => void }) {
  const matrix = useRoleMatrix(role.id);
  const save = useSetRoleMatrix();
  const readOnly = useReadOnly();
  const [changes, setChanges] = useState<Record<string, boolean>>({});
  const [filter, setFilter] = useState('');

  const modules = useMemo(() => {
    const rows = matrix.data?.data.modules ?? [];
    const needle = filter.trim().toLowerCase();
    return needle ? rows.filter((m) => m.module.includes(needle)) : rows;
  }, [matrix.data, filter]);

  const granted = (module: string, action: string, current: boolean) => changes[`${module}:${action}`] ?? current;

  const toggle = (module: string, action: string, current: boolean) => {
    const key = `${module}:${action}`;
    const next = !granted(module, action, current);
    setChanges((prev) => {
      const copy = { ...prev };
      if (next === current) delete copy[key];
      else copy[key] = next;
      return copy;
    });
  };

  const toggleModule = (module: string, actions: { action: string; granted: boolean }[], value: boolean) => {
    setChanges((prev) => {
      const copy = { ...prev };
      for (const a of actions) {
        const key = `${module}:${a.action}`;
        if (value === a.granted) delete copy[key];
        else copy[key] = value;
      }
      return copy;
    });
  };

  const diff = Object.entries(changes);
  const onSave = () => {
    const byModule = new Map<string, { action: string; granted: boolean }[]>();
    for (const [key, value] of diff) {
      const [module, action] = key.split(':');
      byModule.set(module, [...(byModule.get(module) ?? []), { action, granted: value }]);
    }
    save.mutate(
      { id: role.id, modules: [...byModule.entries()].map(([module, actions]) => ({ module, actions })) },
      {
        onSuccess: () => {
          setChanges({});
          toast.success(`${diff.length} permission change(s) saved`);
          onSaved?.();
        },
        onError: (e) => toast.error(getApiError(e, 'Could not save the matrix')),
      },
    );
  };

  if (matrix.isLoading) return <TableSkeleton />;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Input className="w-56" placeholder="Filter modules…" value={filter} onChange={(e) => setFilter(e.target.value)} />
        <span className="text-xs text-muted-foreground">
          {diff.length > 0 ? `${diff.length} pending change(s)` : 'No changes'}
        </span>
        <div className="ml-auto flex gap-2">
          <Button variant="ghost" size="sm" disabled={diff.length === 0} onClick={() => setChanges({})}>
            Reset
          </Button>
          <Button size="sm" data-write disabled={readOnly || diff.length === 0} loading={save.isPending} onClick={onSave}>
            Save changes
          </Button>
        </div>
      </div>

      {diff.length > 0 && (
        <ul className="max-h-24 overflow-y-auto rounded-md border bg-muted/40 p-2 text-xs">
          {diff.map(([key, value]) => (
            <li key={key}>
              <span className={value ? 'text-status-approved' : 'text-destructive'}>{value ? '+ ' : '− '}</span>
              {key}
            </li>
          ))}
        </ul>
      )}

      <div className="max-h-[50vh] overflow-auto rounded-md border">
        <table className="w-full text-sm">
          <tbody>
            {modules.map((m) => (
              <tr key={m.module} className="border-b last:border-0">
                <th scope="row" className="sticky left-0 w-48 bg-card px-3 py-2 text-left align-top font-medium">
                  {titleCase(m.module)}
                  <div className="mt-1 flex gap-1 text-[11px] font-normal">
                    <button type="button" className="text-primary hover:underline" onClick={() => toggleModule(m.module, m.actions, true)}>
                      all
                    </button>
                    <button type="button" className="text-muted-foreground hover:underline" onClick={() => toggleModule(m.module, m.actions, false)}>
                      none
                    </button>
                  </div>
                </th>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap gap-x-4 gap-y-1">
                    {m.actions.map((a) => (
                      <label key={a.action} className="flex items-center gap-1.5 text-xs">
                        <Checkbox
                          checked={granted(m.module, a.action, a.granted)}
                          onCheckedChange={() => toggle(m.module, a.action, a.granted)}
                          disabled={readOnly}
                          aria-label={`${m.module}:${a.action}`}
                        />
                        {a.action}
                      </label>
                    ))}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
