import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

/** react-i18next scaffold with `en` only; all UI strings go through t() so locale packs can be added (feature i18n.web). */
export const resources = {
  en: {
    translation: {
      app: { name: 'SeptronUniverse' },
      nav: {
        main: 'Main',
        academics: 'Academics',
        examinations: 'Examinations',
        admissions: 'Admissions',
        students: 'Students',
        people: 'People',
        campus: 'Campus',
        finance: 'Finance',
        engagement: 'Engagement',
        quality: 'Quality & Governance',
        communication: 'Communication',
        admin: 'Admin',
        dashboard: 'Dashboard',
      },
      common: {
        loading: 'Loading…',
        save: 'Save',
        cancel: 'Cancel',
        delete: 'Delete',
        edit: 'Edit',
        create: 'Create',
        search: 'Search',
        export: 'Export',
        filters: 'Filters',
        noResults: 'No results',
        retry: 'Retry',
        back: 'Back',
        logout: 'Sign out',
        readOnly: 'The platform is in read-only mode. Changes are temporarily disabled.',
        impersonating: 'You are impersonating {{name}}. Every action is audited.',
      },
      scope: { self: 'Mine', own: 'Mine', department: 'Department', faculty: 'Faculty', college: 'College', all: 'All' },
      errors: {
        accessDenied: 'You do not have permission to view this page.',
        featureDisabled: 'This feature is not enabled for your institution.',
        notFound: 'The page you are looking for does not exist.',
        generic: 'Something went wrong',
      },
      auth: { login: 'Sign in', identifier: 'Username, email or phone', password: 'Password', forgot: 'Forgot password?' },
    },
  },
} as const;

void i18n.use(initReactI18next).init({
  resources,
  lng: 'en',
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
});

export default i18n;
