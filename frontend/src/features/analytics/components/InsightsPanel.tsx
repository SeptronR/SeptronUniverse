import { useState } from 'react';
import { BarChart3 } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { useFeature } from '@/hooks/useFeature';
import { InsightsTab } from './InsightsTab';

/** "Insights" toggle for list pages (Prompts/35 §35.9): charts of the module under the page's current filters. */
export function InsightsPanel({ module, filters = {} }: { module: string; filters?: Record<string, unknown> }) {
  const on = useFeature('analytics.core');
  const [open, setOpen] = useState(false);
  if (!on) return null;
  return (
    <div className="space-y-3">
      <Button variant={open ? 'default' : 'outline'} size="sm" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <BarChart3 className="h-4 w-4" /> Insights
      </Button>
      {open && <InsightsTab module={module} filters={filters} />}
    </div>
  );
}
