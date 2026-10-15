import { useColleges, useDepartments } from '@/features/institution/hooks';
import { Input } from '@/components/ui/Input';
import type { AudienceRules } from '../types';

const ROLE_HINT = 'student, parent, faculty, hod, …';

/** Audience rules: roles, colleges, departments (programme / batch rules arrive with Phases 05/07). */
export function AudienceBuilder({ value, onChange }: { value: AudienceRules; onChange: (v: AudienceRules) => void }) {
  const colleges = useColleges({ scope: 'all', page_size: 200 });
  const depts = useDepartments({ page_size: 200 });
  const toggle = (key: 'college_ids' | 'department_ids', id: string) => {
    const set = new Set(value[key]);
    if (set.has(id)) set.delete(id);
    else set.add(id);
    onChange({ ...value, [key]: [...set] });
  };
  return (
    <div className="space-y-3 text-sm">
      <label className="block space-y-1">
        <span className="font-medium">Roles</span>
        <Input
          aria-label="Roles"
          placeholder={ROLE_HINT}
          value={value.roles.join(', ')}
          onChange={(e) => onChange({ ...value, roles: e.target.value.split(',').map((s) => s.trim()).filter(Boolean) })}
        />
      </label>
      <div>
        <p className="font-medium">Colleges</p>
        <div className="mt-1 flex flex-wrap gap-2">
          {(colleges.data?.data ?? []).map((c) => (
            <label key={c.id} className="flex items-center gap-1 rounded border px-2 py-1">
              <input type="checkbox" checked={value.college_ids.includes(c.id)} onChange={() => toggle('college_ids', c.id)} />
              {c.code}
            </label>
          ))}
        </div>
      </div>
      <div>
        <p className="font-medium">Departments</p>
        <div className="mt-1 flex flex-wrap gap-2">
          {(depts.data?.data ?? []).map((d) => (
            <label key={d.id} className="flex items-center gap-1 rounded border px-2 py-1">
              <input type="checkbox" checked={value.department_ids.includes(d.id)} onChange={() => toggle('department_ids', d.id)} />
              {d.college_code}/{d.code}
            </label>
          ))}
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        Selections add up: anyone matching <b>any</b> selected role, college or department receives it (e.g. role
        &ldquo;student&rdquo; + department A/CSE = every student and everyone in A/CSE). No selection = the whole institution.
      </p>
    </div>
  );
}
