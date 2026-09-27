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
        stopImpersonating: 'Stop impersonating',
        profile: 'My profile',
      },
      scope: { self: 'Mine', own: 'Mine', department: 'Department', faculty: 'Faculty', college: 'College', all: 'All' },
      errors: {
        accessDenied: 'You do not have permission to view this page.',
        featureDisabled: 'This feature is not enabled for your institution.',
        notFound: 'The page you are looking for does not exist.',
        generic: 'Something went wrong',
      },
      auth: {
        login: 'Sign in',
        identifier: 'Username, email or phone',
        password: 'Password',
        forgot: 'Forgot password?',
        forgotHint: 'We will email a single-use reset link if the account exists.',
        sendResetLink: 'Send reset link',
        resetSent: 'If the account exists, a reset link is on its way. The link expires in one hour.',
        resetTitle: 'Choose a new password',
        resetNoToken: 'This link is missing its token.',
        passwordPolicy: 'At least 10 characters with 3 of 4 character classes.',
        newPassword: 'New password',
        confirmPassword: 'Confirm password',
        setPassword: 'Set password',
        otp: 'One-time code',
        otpCode: '6-digit code',
        sendOtp: 'Send code',
        resend: 'Send a new code',
        resendIn: 'Send a new code in {{seconds}}s',
        phone: 'Registered phone number',
        mfaCode: 'Authenticator code',
        mfaHint: 'Six digits from your authenticator app, or a recovery code.',
        mfaSetup: 'Set up multi-factor authentication',
        sso: 'Continue with single sign-on',
      },
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
