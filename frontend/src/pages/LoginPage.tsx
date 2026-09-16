import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { GraduationCap } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Navigate } from 'react-router-dom';
import { api, getApiError } from '@/api/axios';
import { Button } from '@/components/ui/Button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/Card';
import { FormField } from '@/components/shared/FormField';
import { toast } from '@/components/ui/Toaster';
import { useAuthStore } from '@/store/authStore';

const schema = z.object({
  identifier: z.string().min(1, 'Required'),
  password: z.string().min(1, 'Required'),
});
type LoginForm = z.infer<typeof schema>;

/**
 * Login placeholder (Phase 02 completes OTP/SSO/MFA and /auth/me bootstrap). Until then POST /auth/login answers
 * 401 UNAUTHENTICATED, which surfaces as a toast — this proves the axios interceptor + envelope handling end to end.
 */
export default function LoginPage() {
  const { t } = useTranslation();
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const form = useForm<LoginForm>({ resolver: zodResolver(schema), defaultValues: { identifier: '', password: '' } });

  if (isAuthenticated) return <Navigate to="/dashboard" replace />;

  const onSubmit = async (values: LoginForm) => {
    try {
      await api.post('/auth/login', values, { idempotent: false });
      toast.success('Signed in');
    } catch (e) {
      toast.error(getApiError(e, 'Sign-in failed'));
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="items-center text-center">
          <GraduationCap className="h-10 w-10 text-primary" />
          <CardTitle className="text-xl">{t('app.name')}</CardTitle>
          <CardDescription>{t('auth.login')}</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={form.handleSubmit(onSubmit)} noValidate>
            <FormField
              label={t('auth.identifier')}
              autoComplete="username"
              error={form.formState.errors.identifier}
              {...form.register('identifier')}
            />
            <FormField
              label={t('auth.password')}
              type="password"
              autoComplete="current-password"
              error={form.formState.errors.password}
              {...form.register('password')}
            />
            <Button type="submit" className="w-full" loading={form.formState.isSubmitting}>
              {t('auth.login')}
            </Button>
            <p className="text-center text-xs text-muted-foreground">Authentication arrives in Phase 02.</p>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
