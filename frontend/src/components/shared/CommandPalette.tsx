import { useEffect, useMemo, useState } from 'react';
import { Command } from 'cmdk';
import { useNavigate } from 'react-router-dom';
import { Search } from 'lucide-react';
import { NAV_GROUPS } from '@/nav';
import { useFeatures } from '@/hooks/useFeature';
import { usePermission } from '@/hooks/usePermission';

/**
 * Ctrl+K command palette: navigation entries (permission + feature filtered) now; Phase 01 adds `/search` results.
 */
export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const { can, canAny } = usePermission();
  const features = useFeatures();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const items = useMemo(
    () =>
      NAV_GROUPS.flatMap((g) =>
        g.items
          .filter((it) => can(it.module, it.action ?? 'view') || (it.altActions ? canAny(it.altActions.map((a) => [it.module, a])) : false))
          .filter((it) => !it.feature || it.feature.startsWith('core.') || features.includes(it.feature))
          .map((it) => ({ ...it, group: g.title })),
      ),
    [can, canAny, features],
  );

  return (
    <Command.Dialog open={open} onOpenChange={setOpen} label="Command palette" className="fixed inset-0 z-50">
      <div className="fixed inset-0 bg-black/40" onClick={() => setOpen(false)} aria-hidden />
      <div className="fixed left-1/2 top-24 w-[min(40rem,calc(100%-2rem))] -translate-x-1/2 overflow-hidden rounded-lg border bg-popover shadow-lg">
        <div className="flex items-center gap-2 border-b px-3">
          <Search className="h-4 w-4 text-muted-foreground" />
          <Command.Input placeholder="Search pages…" className="h-11 w-full bg-transparent text-sm outline-none" />
        </div>
        <Command.List className="max-h-80 overflow-y-auto p-2">
          <Command.Empty className="p-4 text-center text-sm text-muted-foreground">No results.</Command.Empty>
          {items.map((it) => (
            <Command.Item
              key={it.to}
              value={`${it.group} ${it.label}`}
              onSelect={() => {
                setOpen(false);
                navigate(it.to);
              }}
              className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm data-[selected=true]:bg-accent"
            >
              <it.icon className="h-4 w-4 text-muted-foreground" />
              <span>{it.label}</span>
              <span className="ml-auto text-xs text-muted-foreground">{it.group}</span>
            </Command.Item>
          ))}
        </Command.List>
      </div>
    </Command.Dialog>
  );
}
