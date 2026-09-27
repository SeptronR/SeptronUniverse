import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { authApi } from '@/features/auth/api';
import { Input } from '@/components/ui/Input';

/** Staff user search for HOD / dean assignment (``/users?user_type=staff``; staff records arrive in Phase 06). */
export function StaffPicker({ onPick }: { onPick: (id: string, name: string) => void }) {
  const [q, setQ] = useState('');
  const users = useQuery({
    queryKey: ['users', { q, user_type: 'staff', picker: true }],
    queryFn: () => authApi.listUsers({ q, user_type: 'staff', page_size: 10 }),
    enabled: q.length >= 2,
  });
  return (
    <div className="space-y-2">
      <Input placeholder="Search staff (min 2 letters)…" value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
      <ul className="max-h-60 divide-y overflow-y-auto rounded-md border">
        {(users.data?.data ?? []).map((u) => (
          <li key={u.id}>
            <button
              type="button"
              className="w-full px-3 py-2 text-left text-sm hover:bg-accent"
              onClick={() => onPick(u.id, u.display_name ?? u.username)}
            >
              {u.display_name ?? u.username} <span className="text-xs text-muted-foreground">({u.username})</span>
            </button>
          </li>
        ))}
        {q.length >= 2 && users.data?.data.length === 0 && <li className="px-3 py-2 text-sm text-muted-foreground">No staff found</li>}
      </ul>
    </div>
  );
}
