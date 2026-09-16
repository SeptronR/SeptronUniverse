import { useEffect, useMemo, useState } from 'react';
import { Command } from 'cmdk';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, Loader2, Search } from 'lucide-react';
import { NAV_GROUPS } from '@/nav';
import { useFeatures } from '@/hooks/useFeature';
import { usePermission } from '@/hooks/usePermission';
import { useSearch } from '@/features/platform/hooks';
import { titleCase } from '@/utils/formatters';

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return v;
}

/**
 * Ctrl+K command palette: navigation entries (permission + feature filtered) plus the top hits of `GET /search`
 * once two characters are typed (Prompts/01 §01.9); Enter on "See all results" opens /search.
 */
export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const navigate = useNavigate();
  const { can, canAny } = usePermission();
  const features = useFeatures();
  const debounced = useDebounced(q, 250);
  const searchEnabled = features.includes('search.global') && can('dashboard', 'view');
  const search = useSearch(searchEnabled && open ? debounced : '');

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

  useEffect(() => {
    if (!open) setQ('');
  }, [open]);

  const items = useMemo(
    () =>
      NAV_GROUPS.flatMap((g) =>
        g.items
          .filter(
            (it) =>
              can(it.module, it.action ?? 'view') ||
              (it.altActions ? canAny(it.altActions.map((a) => [it.module, a])) : false),
          )
          .filter((it) => !it.feature || it.feature.startsWith('core.') || features.includes(it.feature))
          .map((it) => ({ ...it, group: g.title })),
      ),
    [can, canAny, features],
  );

  const go = (to: string) => {
    setOpen(false);
    navigate(to);
  };
  const results = search.data?.data.results ?? [];
  const searching = searchEnabled && debounced.trim().length >= 2;

  return (
    <Command.Dialog open={open} onOpenChange={setOpen} label="Command palette" className="fixed inset-0 z-50">
      <div className="fixed inset-0 bg-black/40" onClick={() => setOpen(false)} aria-hidden />
      <div className="fixed left-1/2 top-24 w-[min(40rem,calc(100%-2rem))] -translate-x-1/2 overflow-hidden rounded-lg border bg-popover shadow-lg">
        <div className="flex items-center gap-2 border-b px-3">
          <Search className="h-4 w-4 text-muted-foreground" />
          <Command.Input
            value={q}
            onValueChange={setQ}
            placeholder={searchEnabled ? 'Search pages, students, staff, courses…' : 'Search pages…'}
            className="h-11 w-full bg-transparent text-sm outline-none"
          />
          {search.isFetching && (
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-label="Searching" />
          )}
        </div>
        <Command.List className="max-h-80 overflow-y-auto p-2">
          <Command.Empty className="p-4 text-center text-sm text-muted-foreground">
            {searching && !search.isFetching ? `No results for “${debounced}”.` : 'No results.'}
          </Command.Empty>
          {searching && results.length > 0 && (
            <Command.Group
              heading="Records"
              className="text-xs text-muted-foreground [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1"
            >
              {results.map((r) => (
                <Command.Item
                  key={`${r.entity_type}-${r.entity_id}`}
                  // cmdk filters on `value`: prefix the query so server hits always survive the client-side match
                  value={`${debounced} ${r.entity_type} ${r.title} ${r.entity_id}`}
                  onSelect={() => go(r.route)}
                  className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm text-foreground data-[selected=true]:bg-accent"
                >
                  <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                    {titleCase(r.entity_type)}
                  </span>
                  <span className="truncate">{r.title}</span>
                  {r.subtitle && <span className="truncate text-xs text-muted-foreground">{r.subtitle}</span>}
                </Command.Item>
              ))}
            </Command.Group>
          )}
          {searching && (
            <Command.Item
              value={`see all results ${debounced}`}
              onSelect={() => go(`/search?q=${encodeURIComponent(debounced.trim())}`)}
              className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm data-[selected=true]:bg-accent"
            >
              <ArrowRight className="h-4 w-4 text-muted-foreground" />
              See all results for “{debounced.trim()}”
            </Command.Item>
          )}
          {items.map((it) => (
            <Command.Item
              key={it.to}
              value={`${it.group} ${it.label}`}
              onSelect={() => go(it.to)}
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
