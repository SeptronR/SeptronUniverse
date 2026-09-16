import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Search as SearchIcon } from 'lucide-react';
import { PageHeader } from '@/components/shared/PageHeader';
import { EmptyState } from '@/components/shared/EmptyState';
import { Badge } from '@/components/ui/Badge';
import { Input } from '@/components/ui/Input';
import { Skeleton } from '@/components/ui/Skeleton';
import { titleCase } from '@/utils/formatters';
import { useSearch } from '../hooks';

/** /search?q= — full-page results of the global search (the Ctrl+K palette shows the same top hits inline). */
export default function SearchPage() {
  const [params, setParams] = useSearchParams();
  const q = params.get('q') ?? '';
  const [draft, setDraft] = useState(q);
  const query = useSearch(q);
  const results = query.data?.data.results ?? [];

  return (
    <div className="space-y-4">
      <PageHeader title="Search" description="Students, staff, courses and applicants you are allowed to see." />
      <form
        className="relative max-w-xl"
        onSubmit={(e) => {
          e.preventDefault();
          setParams(draft.trim() ? { q: draft.trim() } : {}, { replace: true });
        }}
      >
        <SearchIcon className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input
          aria-label="Search"
          autoFocus
          placeholder="Name, number or code… (min. 2 characters)"
          className="pl-8"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
      </form>
      {q.trim().length < 2 ? (
        <p className="text-sm text-muted-foreground">Type at least two characters and press Enter.</p>
      ) : query.isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-12" />
          ))}
        </div>
      ) : results.length === 0 ? (
        <EmptyState
          title="No results"
          description={`Nothing matched “${q}”. Records appear here once the modules that own them are live.`}
          icon={<SearchIcon className="h-6 w-6" />}
        />
      ) : (
        <ul className="divide-y rounded-lg border bg-card">
          {results.map((r) => (
            <li key={`${r.entity_type}-${r.entity_id}`}>
              <Link to={r.route} className="flex items-center justify-between gap-3 px-4 py-3 hover:bg-accent/40">
                <span>
                  <span className="font-medium">{r.title}</span>
                  {r.subtitle && <span className="ml-2 text-sm text-muted-foreground">{r.subtitle}</span>}
                </span>
                <Badge variant="secondary">{titleCase(r.entity_type)}</Badge>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
