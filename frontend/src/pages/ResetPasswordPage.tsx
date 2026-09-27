import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { KeyRound } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { getApiError } from '@/api/axios';
import { Button } from '@/components/ui/Button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/Card';
import { FormField } from '@/components/shared/FormField';
import { toast } from '@/components/ui/Toaster';
import { passwordPolicy } from '@/utils/validators';
import { useResetPassword } from '@/features/auth/hooks';

const schema = z
  .object({ password: passwordPolicy, confirm: z.string() })
  .refine((v) => v.password === v.confirm, { path: ['confirm'], message: 'Passwords do not match' });
type Form = z.infer<typeof schema>;

/** /reset-password?token=… — single-use token from the reset email (1 h; policy enforced server-side too). */
export default function ResetPasswordPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const token = params.get('token') ?? '';
  const reset = useResetPassword();
  const form = useForm<Form>({ resolver: zodResolver(schema), defaultValues: { password: '', confirm: '' } });

  const onSubmit = async (values: Form) => {
    try {
      await reset.mutateAsync({ token, password: values.password });
      toast.success('Password updated — sign in with the new password');
      navigate('/login', { replace: true });
    } catch (e) {
      toast.error(getApiError(e, 'The reset link is invalid or has expired'));
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="items-center text-center">
          <KeyRound className="h-9 w-9 text-primary" />
          <CardTitle className="text-lg">{t('auth.resetTitle')}</CardTitle>
          <CardDescription>{t('auth.passwordPolicy')}</CardDescription>
        </CardHeader>
        <CardContent>
          {!token ? (
            <p className="text-center text-sm text-muted-foreground">
              {t('auth.resetNoToken')}{' '}
              <Link to="/forgot-password" className="text-primary hover:underline">
                {t('auth.forgot')}
              </Link>
            </p>
          ) : (
            <form className="space-y-4" onSubmit={form.handleSubmit(onSubmit)} noValidate>
              <FormField
                label={t('auth.newPassword')}
                type="password"
                autoComplete="new-password"
                error={form.formState.errors.password}
                {...form.register('password')}
              />
              <FormField
                label={t('auth.confirmPassword')}
                type="password"
                autoComplete="new-password"
                error={form.formState.errors.confirm}
                {...form.register('confirm')}
              />
              <Button type="submit" className="w-full" loading={reset.isPending}>
                {t('auth.setPassword')}
              </Button>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
