import { LayoutDashboard, type LucideIcon } from 'lucide-react';

/**
 * Sidebar navigation (Prompts/00 §4.5). Items are gated by `can(module, action ?? 'view') || canAny(altActions)`
 * and `useFeature(feature)`. Phases append `{ label, to, icon, module, action?, feature? }` under their group.
 */
export type NavItem = {
  label: string;
  to: string;
  icon: LucideIcon;
  module: string;
  action?: string;
  altActions?: string[];
  feature?: string;
  roles?: string[];
};

export type NavGroup = { title: string; items: NavItem[] };

export const NAV_GROUPS: NavGroup[] = [
  { title: 'MAIN', items: [{ label: 'Dashboard', to: '/dashboard', icon: LayoutDashboard, module: 'dashboard' }] },
  { title: 'ACADEMICS', items: [] },
  { title: 'EXAMINATIONS', items: [] },
  { title: 'ADMISSIONS', items: [] },
  { title: 'STUDENTS', items: [] },
  { title: 'PEOPLE', items: [] },
  { title: 'CAMPUS', items: [] },
  { title: 'FINANCE', items: [] },
  { title: 'ENGAGEMENT', items: [] },
  { title: 'QUALITY & GOVERNANCE', items: [] },
  { title: 'COMMUNICATION', items: [] },
  { title: 'ADMIN', items: [] },
];
