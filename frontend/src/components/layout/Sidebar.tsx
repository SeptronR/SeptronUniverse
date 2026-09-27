import { NavLink } from 'react-router-dom';
import { GraduationCap } from 'lucide-react';
import { NAV_GROUPS } from '@/nav';
import { useInbox } from '@/features/workflow/hooks';
import { useFeatures } from '@/hooks/useFeature';
import { usePermission } from '@/hooks/usePermission';
import { useSessionStore } from '@/store/sessionStore';
import { cn } from '@/utils/cn';

interface SidebarProps {
  collapsed: boolean;
  onNavigate?: () => void;
}

/** Data-driven sidebar: items filtered by `can(module, action) || canAny(altActions)` and `useFeature(feature)`. */
export function Sidebar({ collapsed, onNavigate }: SidebarProps) {
  const { can, canAny } = usePermission();
  const features = useFeatures();
  const institutionName = useSessionStore((s) => s.institutionName);
  const inbox = useInbox();
  const badges: Record<string, number> = { approvals: inbox.data?.data.length ?? 0 };

  const groups = NAV_GROUPS.map((g) => ({
    ...g,
    items: g.items.filter((it) => {
      const permitted = can(it.module, it.action ?? 'view') || (it.altActions ? canAny(it.altActions.map((a) => [it.module, a])) : false);
      const featured = !it.feature || it.feature.startsWith('core.') || features.includes(it.feature);
      return permitted && featured;
    }),
  })).filter((g) => g.items.length > 0);

  return (
    <aside
      className={cn(
        'flex h-full flex-col border-r bg-sidebar-bg text-sidebar-text transition-[width] duration-200',
        collapsed ? 'w-16' : 'w-60',
      )}
      aria-label="Primary"
    >
      <div className="flex h-14 items-center gap-2 border-b px-4">
        <GraduationCap className="h-6 w-6 shrink-0 text-primary" />
        {!collapsed && (
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-foreground">SeptronUniverse</p>
            {institutionName && <p className="truncate text-xs text-muted-foreground">{institutionName}</p>}
          </div>
        )}
      </div>
      <nav className="flex-1 overflow-y-auto px-2 py-3">
        {groups.map((g) => (
          <div key={g.title} className="mb-4">
            {!collapsed && <p className="px-2 pb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{g.title}</p>}
            <ul className="space-y-0.5">
              {g.items.map((it) => (
                <li key={it.to}>
                  <NavLink
                    to={it.to}
                    onClick={onNavigate}
                    title={collapsed ? it.label : undefined}
                    className={({ isActive }) =>
                      cn(
                        'flex items-center gap-3 rounded-md px-2 py-2 text-sm font-medium hover:bg-sidebar-hover',
                        isActive && 'bg-sidebar-active text-sidebar-text-active',
                        collapsed && 'justify-center',
                      )
                    }
                  >
                    <it.icon className="h-4 w-4 shrink-0" />
                    {!collapsed && <span className="truncate">{it.label}</span>}
                    {it.badge && badges[it.badge] > 0 && (
                      <span className="ml-auto rounded-full bg-primary px-1.5 text-[10px] font-semibold text-primary-foreground">
                        {badges[it.badge]}
                      </span>
                    )}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>
    </aside>
  );
}
