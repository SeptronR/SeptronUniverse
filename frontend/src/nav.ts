import {
  Activity,
  Building,
  Building2,
  CalendarDays,
  CalendarRange,
  Hash,
  Landmark,
  Settings,
  CreditCard,
  LayoutDashboard,
  LifeBuoy,
  ShieldCheck,
  ToggleLeft,
  Users,
  type LucideIcon,
} from 'lucide-react';

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
  {
    title: 'MAIN',
    items: [
      { label: 'Dashboard', to: '/dashboard', icon: LayoutDashboard, module: 'dashboard' },
      // Phase 01 — platform services
      { label: 'Background jobs', to: '/jobs', icon: Activity, module: 'jobs', feature: 'core.background_jobs' },
      { label: 'Help centre', to: '/help', icon: LifeBuoy, module: 'dashboard', feature: 'platform.help_center' },
    ],
  },
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
  {
    title: 'ADMIN',
    items: [
      // Phase 03 — institution structure, academic sessions, settings
      { label: 'Institution', to: '/admin/institution', icon: Landmark, module: 'institutions', feature: 'core.institution' },
      { label: 'Colleges', to: '/admin/colleges', icon: Building2, module: 'institutions', feature: 'core.institution' },
      { label: 'Departments', to: '/admin/departments', icon: Building, module: 'institutions', feature: 'core.institution' },
      {
        label: 'Academic Years',
        to: '/admin/academic-years',
        icon: CalendarRange,
        module: 'sessions',
        altActions: ['manage'],
        feature: 'core.institution',
      },
      { label: 'Holidays', to: '/admin/holidays', icon: CalendarDays, module: 'institutions', feature: 'institution.holidays' },
      { label: 'Settings', to: '/admin/settings', icon: Settings, module: 'settings', feature: 'core.settings' },
      {
        label: 'Number Sequences',
        to: '/admin/number-sequences',
        icon: Hash,
        module: 'settings',
        action: 'manage',
        feature: 'institution.number_sequences_custom',
      },
      // super admin only (features:manage is platform-only): tenants + onboarding wizard
      {
        label: 'Tenants',
        to: '/super-admin/institutions',
        icon: Landmark,
        module: 'features',
        action: 'manage',
        feature: 'core.institution',
      },
      // Phase 02 — auth, RBAC, features, entitlements
      { label: 'Users', to: '/admin/users', icon: Users, module: 'users', action: 'view_all', feature: 'core.rbac' },
      { label: 'Roles', to: '/admin/roles', icon: ShieldCheck, module: 'roles', feature: 'core.rbac' },
      {
        label: 'Features',
        to: '/admin/settings/features',
        icon: ToggleLeft,
        module: 'features',
        action: 'institution_toggle',
        feature: 'core.settings',
      },
      {
        label: 'Entitlements',
        to: '/admin/settings/entitlements',
        icon: CreditCard,
        module: 'settings',
        feature: 'core.settings',
      },
    ],
  },
];
