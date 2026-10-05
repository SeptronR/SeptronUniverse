import { useTranslation } from 'react-i18next';
import { cn } from '@/utils/cn';
import type { ScopeName, VisibilityMeta } from '@/utils/types';

interface ScopeTabsProps {
  visibility: VisibilityMeta | undefined;
  value: string | undefined;
  onChange: (scope: ScopeName) => void;
  className?: string;
  /** per-scope label overrides — Phase 06 HR lists show `department` as "Team" (HOD / dean) */
  labels?: Partial<Record<ScopeName, string>>;
}

const ORDER: ScopeName[] = ['self', 'own', 'department', 'faculty', 'college', 'all'];

/**
 * Segmented **Mine | Department | College | All** driven by `meta.visibility` (docs/Authorization_and_Visibility.md §4).
 * Hidden when the caller only sees one scope; the chosen scope is written to `?scope=` by the caller (query key).
 */
export function ScopeTabs({ visibility, value, onChange, className, labels }: ScopeTabsProps) {
  const { t } = useTranslation();
  if (!visibility) return null;
  const tabs: ScopeName[] = [];
  if (visibility.self) tabs.push('self');
  for (const s of ORDER) if (visibility.scopes.includes(s) && !tabs.includes(s)) tabs.push(s);
  if (tabs.length <= 1) return null;
  const active = (value as ScopeName | undefined) ?? visibility.default ?? tabs[0];
  return (
    <div role="tablist" aria-label="Scope" className={cn('inline-flex rounded-md border bg-muted p-1', className)}>
      {tabs.map((s) => (
        <button
          key={s}
          role="tab"
          type="button"
          aria-selected={active === s}
          onClick={() => onChange(s)}
          className={cn(
            'rounded-sm px-3 py-1 text-sm font-medium transition-colors',
            active === s ? 'bg-card text-foreground shadow-xs' : 'text-muted-foreground hover:text-foreground',
          )}
        >
          {labels?.[s] ?? t(`scope.${s}`)}
        </button>
      ))}
    </div>
  );
}
