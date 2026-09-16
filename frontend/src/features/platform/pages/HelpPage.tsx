import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { BookOpen, ChevronLeft, Search } from 'lucide-react';
import { PageHeader } from '@/components/shared/PageHeader';
import { EmptyState } from '@/components/shared/EmptyState';
import { Card, CardContent } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Input } from '@/components/ui/Input';
import { Skeleton } from '@/components/ui/Skeleton';
import { buttonVariants } from '@/components/ui/Button';
import { formatDate, titleCase } from '@/utils/formatters';
import { cn } from '@/utils/cn';
import { FeedbackDialog } from '../components/FeedbackDialog';
import { useHelpArticle, useHelpArticles } from '../hooks';

/** Minimal Markdown → blocks (headings, bullets, paragraphs, `code`, **bold**) — articles are trusted platform/tenant content. */
function renderBody(body: string) {
  const inline = (text: string) =>
    text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g).map((part, i) => {
      if (part.startsWith('`'))
        return (
          <code key={i} className="rounded bg-muted px-1 py-0.5 text-[0.85em]">
            {part.slice(1, -1)}
          </code>
        );
      if (part.startsWith('**')) return <strong key={i}>{part.slice(2, -2)}</strong>;
      return <span key={i}>{part}</span>;
    });
  const blocks: React.ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length) {
      blocks.push(
        <ul key={`ul-${blocks.length}`} className="list-disc space-y-1 pl-5">
          {list.map((l, i) => (
            <li key={i}>{inline(l)}</li>
          ))}
        </ul>,
      );
      list = [];
    }
  };
  body.split(/\r?\n/).forEach((line, i) => {
    const t = line.trim();
    if (!t) return flush();
    if (t.startsWith('- ')) return list.push(t.slice(2));
    flush();
    if (t.startsWith('## '))
      blocks.push(
        <h2 key={i} className="text-lg font-semibold">
          {t.slice(3)}
        </h2>,
      );
    else if (t.startsWith('# '))
      blocks.push(
        <h1 key={i} className="text-xl font-semibold">
          {t.slice(2)}
        </h1>,
      );
    else blocks.push(<p key={i}>{inline(t)}</p>);
  });
  flush();
  return blocks;
}

/** /help (article list with module filter + search) and /help/:slug (article detail) — Prompts/01 §01.9. */
export default function HelpPage() {
  const { slug } = useParams<{ slug?: string }>();
  const [q, setQ] = useState('');
  const [module, setModule] = useState<string | null>(null);
  const list = useHelpArticles({ q: q.trim() || undefined, module: module ?? undefined });
  const article = useHelpArticle(slug);
  const modules = useMemo(
    () => Array.from(new Set((list.data?.data ?? []).map((a) => a.module).filter(Boolean))) as string[],
    [list.data],
  );

  if (slug) {
    return (
      <div className="mx-auto max-w-3xl space-y-4">
        <Link to="/help" className={cn(buttonVariants({ variant: 'ghost', size: 'sm' }), '-ml-2')}>
          <ChevronLeft className="h-4 w-4" /> All articles
        </Link>
        {article.isLoading ? (
          <div className="space-y-3">
            <Skeleton className="h-7 w-2/3" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
          </div>
        ) : article.isError || !article.data ? (
          <EmptyState
            title="Article not found"
            description="It may have been unpublished."
            icon={<BookOpen className="h-6 w-6" />}
          />
        ) : (
          <article className="space-y-4">
            <PageHeader
              title={article.data.data.title}
              description={
                <span className="flex items-center gap-2">
                  {article.data.data.module && <Badge variant="secondary">{titleCase(article.data.data.module)}</Badge>}
                  {article.data.data.is_platform && <Badge variant="outline">Platform</Badge>}
                  <span>Updated {formatDate(article.data.data.updated_at)}</span>
                </span>
              }
            />
            <Card>
              <CardContent className="space-y-3 p-5 text-sm leading-6">
                {renderBody(article.data.data.body)}
              </CardContent>
            </Card>
            <div className="flex justify-end">
              <FeedbackDialog />
            </div>
          </article>
        )}
      </div>
    );
  }

  const articles = list.data?.data ?? [];
  return (
    <div className="space-y-4">
      <PageHeader
        title="Help centre"
        description="Guides for every module, plus your institution's own articles."
        actions={<FeedbackDialog />}
      />
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-72">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            aria-label="Search help"
            placeholder="Search articles…"
            className="pl-8"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <div className="flex flex-wrap gap-1">
          <button
            type="button"
            onClick={() => setModule(null)}
            className={cn('rounded-full border px-3 py-1 text-xs', !module && 'bg-primary text-primary-foreground')}
          >
            All
          </button>
          {modules.map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setModule(m)}
              className={cn(
                'rounded-full border px-3 py-1 text-xs',
                module === m && 'bg-primary text-primary-foreground',
              )}
            >
              {titleCase(m)}
            </button>
          ))}
        </div>
      </div>
      {list.isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
      ) : articles.length === 0 ? (
        <EmptyState
          title="No articles"
          description="Nothing matches your search."
          icon={<BookOpen className="h-6 w-6" />}
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {articles.map((a) => (
            <Link
              key={a.id}
              to={`/help/${a.slug}`}
              className="rounded-lg border bg-card p-4 transition-colors hover:border-primary hover:bg-accent/30"
            >
              <p className="font-medium">{a.title}</p>
              <p className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                {a.module && <Badge variant="secondary">{titleCase(a.module)}</Badge>}
                {a.is_platform ? 'Platform guide' : 'Institution article'}
              </p>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
