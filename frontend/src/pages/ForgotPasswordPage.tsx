import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { MailCheck } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router-dom';
import { getApiError } from '@/api/axios';
import { Button } from '@/components/ui/Button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/Card';
import { FormField } from '@/components/shared/FormField';
import { toast } from '@/components/ui/Toaster';
import { useForgotPassword } from '@/features/auth/hooks';

const schema = z.object({ identifier: z.string().min(1, 'Required') });
type Form = z.infer<typeof schema>;

/** /forgot-password — the API always answers 200 so the page never reveals whether an account exists. */
export default function ForgotPasswordPage() {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const [sent, setSent] = useState(false);
  const forgot = useForgotPassword();
  const form = useForm<Form>({ resolver: zodResolver(schema), defaultValues: { identifier: '' } });

  const onSubmit = async (values: Form) => {
    try {
      await forgot.mutateAsync({ ...values, institution_slug: params.get('institution') ?? undefined });
      setSent(true);
    } catch (e) {
      toast.error(getApiError(e, 'Could not send the reset link'));
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="items-center text-center">
          <MailCheck className="h-9 w-9 text-primary" />
          <CardTitle className="text-lg">{t('auth.forgot')}</CardTitle>
          <CardDescription>{t('auth.forgotHint')}</CardDescription>
        </CardHeader>
        <CardContent>
          {sent ? (
            <div className="space-y-4 text-center">
              <p className="text-sm text-muted-foreground">{t('auth.resetSent')}</p>
              <Link to="/login" className="text-sm text-primary hover:underline">
                {t('common.back')}
              </Link>
            </div>
          ) : (
            <form className="space-y-4" onSubmit={form.handleSubmit(onSubmit)} noValidate>
              <FormField
                label={t('auth.identifier')}
                autoComplete="username"
                error={form.formState.errors.identifier}
                {...form.register('identifier')}
              />
              <Button type="submit" className="w-full" loading={forgot.isPending}>
                {t('auth.sendResetLink')}
              </Button>
              <Link to="/login" className="block text-center text-xs text-muted-foreground hover:text-foreground">
                {t('common.back')}
              </Link>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
