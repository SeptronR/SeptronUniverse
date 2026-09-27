import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { GraduationCap, KeyRound, ShieldCheck } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { getApiError, getApiErrorCode, getApiErrorDetails } from '@/api/axios';
import { Button } from '@/components/ui/Button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/Card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs';
import { FormField } from '@/components/shared/FormField';
import { toast } from '@/components/ui/Toaster';
import { useAuthStore } from '@/store/authStore';
import { usePublicConfig } from '@/features/platform/hooks';
import { homeFor, useLogin, useSendOtp, useSsoStart, useVerifyOtp } from '@/features/auth/hooks';

const passwordSchema = z.object({
  identifier: z.string().min(1, 'Required'),
  password: z.string().min(1, 'Required'),
  mfa_code: z.string().optional(),
});
type PasswordForm = z.infer<typeof passwordSchema>;

const otpSchema = z.object({
  phone: z.string().min(8, 'Enter the registered phone number'),
  code: z.string().optional(),
});
type OtpForm = z.infer<typeof otpSchema>;

/**
 * /login — password (with the MFA step), OTP tab and SSO buttons (Prompts/02 §02.9).
 * The refresh token is set as an httpOnly cookie by the API; only the 15-minute access token reaches the store.
 * A forced password change redirects to /profile?change=1 (every other route answers 403 until it is done).
 */
export default function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const slug = params.get('institution') ?? undefined;
  const config = usePublicConfig(slug);
  const login = useLogin();
  const sendOtp = useSendOtp();
  const verifyOtp = useVerifyOtp();
  const ssoStart = useSsoStart();
  const [mfaRequired, setMfaRequired] = useState(false);
  const [mfaSetupUrl, setMfaSetupUrl] = useState<string | null>(null);
  const [otpSent, setOtpSent] = useState(false);
  const [resendIn, setResendIn] = useState(0);

  const passwordForm = useForm<PasswordForm>({
    resolver: zodResolver(passwordSchema),
    defaultValues: { identifier: '', password: '', mfa_code: '' },
  });
  const otpForm = useForm<OtpForm>({ resolver: zodResolver(otpSchema), defaultValues: { phone: '', code: '' } });

  useEffect(() => {
    if (resendIn <= 0) return;
    const id = window.setInterval(() => setResendIn((s) => Math.max(0, s - 1)), 1000);
    return () => window.clearInterval(id);
  }, [resendIn]);

  if (isAuthenticated) {
    const from = (location.state as { from?: Location } | null)?.from?.pathname;
    return <Navigate to={from ?? '/dashboard'} replace />;
  }

  const afterLogin = (data: { user: { role_slugs: string[]; is_super_admin: boolean; must_change_password: boolean } }) => {
    toast.success('Signed in');
    navigate(data.user.must_change_password ? '/profile?change=1' : homeFor(data.user.role_slugs, data.user.is_super_admin), {
      replace: true,
    });
  };

  const onPassword = async (values: PasswordForm) => {
    try {
      const res = await login.mutateAsync({ ...values, mfa_code: values.mfa_code || undefined, institution_slug: slug });
      afterLogin(res.data);
    } catch (e) {
      if (getApiErrorCode(e) === 'MFA_REQUIRED') {
        const details = getApiErrorDetails(e) as { mfa_setup_required?: boolean; mfa_setup_token?: string };
        setMfaRequired(true);
        setMfaSetupUrl(details.mfa_setup_token ? `/mfa-setup?token=${details.mfa_setup_token}` : null);
        toast.info(
          details.mfa_setup_required
            ? 'Your role requires multi-factor authentication — set it up to continue'
            : 'Enter the code from your authenticator app',
        );
        return;
      }
      toast.error(getApiError(e, 'Sign-in failed'));
    }
  };

  const onSendOtp = async () => {
    const phone = otpForm.getValues('phone');
    if (!phone) {
      otpForm.setError('phone', { message: 'Enter the registered phone number' });
      return;
    }
    try {
      const res = await sendOtp.mutateAsync({ phone, institution_slug: slug });
      setOtpSent(true);
      setResendIn(res.data.resend_after);
      toast.success('Code sent');
    } catch (e) {
      toast.error(getApiError(e, 'Could not send the code'));
    }
  };

  const onVerifyOtp = async (values: OtpForm) => {
    if (!values.code) {
      otpForm.setError('code', { message: 'Enter the 6-digit code' });
      return;
    }
    try {
      const res = await verifyOtp.mutateAsync({ phone: values.phone, code: values.code, institution_slug: slug });
      afterLogin(res.data);
    } catch (e) {
      toast.error(getApiError(e, 'Invalid or expired code'));
    }
  };

  const onSso = async (provider: string) => {
    try {
      const res = await ssoStart.mutateAsync({ provider, slug });
      window.location.href = res.data.authorize_url;
    } catch (e) {
      toast.error(getApiError(e, 'Single sign-on is not available'));
    }
  };

  const institution = config.data?.data.institution;
  const ssoEnabled = config.data?.data.features_public?.includes('security.sso');

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="items-center text-center">
          {institution?.logo_url ? (
            <img src={institution.logo_url} alt="" className="h-10 w-10 rounded" />
          ) : (
            <GraduationCap className="h-10 w-10 text-primary" />
          )}
          <CardTitle className="text-xl">{institution?.name ?? t('app.name')}</CardTitle>
          <CardDescription>{t('auth.login')}</CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="password">
            <TabsList className="mb-4 grid w-full grid-cols-2">
              <TabsTrigger value="password">{t('auth.password')}</TabsTrigger>
              <TabsTrigger value="otp">{t('auth.otp')}</TabsTrigger>
            </TabsList>

            <TabsContent value="password">
              <form className="space-y-4" onSubmit={passwordForm.handleSubmit(onPassword)} noValidate>
                <FormField
                  label={t('auth.identifier')}
                  autoComplete="username"
                  error={passwordForm.formState.errors.identifier}
                  {...passwordForm.register('identifier')}
                />
                <FormField
                  label={t('auth.password')}
                  type="password"
                  autoComplete="current-password"
                  error={passwordForm.formState.errors.password}
                  {...passwordForm.register('password')}
                />
                {mfaRequired && (
                  <FormField
                    label={t('auth.mfaCode')}
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    hint={t('auth.mfaHint')}
                    error={passwordForm.formState.errors.mfa_code}
                    {...passwordForm.register('mfa_code')}
                  />
                )}
                <Button type="submit" className="w-full" loading={login.isPending}>
                  <KeyRound className="h-4 w-4" /> {t('auth.login')}
                </Button>
                {mfaSetupUrl && (
                  <Link to={mfaSetupUrl} className="block text-center text-xs text-primary hover:underline">
                    <ShieldCheck className="mr-1 inline h-3.5 w-3.5" />
                    {t('auth.mfaSetup')}
                  </Link>
                )}
                <Link to="/forgot-password" className="block text-center text-xs text-muted-foreground hover:text-foreground">
                  {t('auth.forgot')}
                </Link>
              </form>
            </TabsContent>

            <TabsContent value="otp">
              <form className="space-y-4" onSubmit={otpForm.handleSubmit(onVerifyOtp)} noValidate>
                <FormField
                  label={t('auth.phone')}
                  autoComplete="tel"
                  inputMode="tel"
                  error={otpForm.formState.errors.phone}
                  {...otpForm.register('phone')}
                />
                {otpSent && (
                  <FormField
                    label={t('auth.otpCode')}
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    maxLength={6}
                    error={otpForm.formState.errors.code}
                    {...otpForm.register('code')}
                  />
                )}
                {otpSent ? (
                  <div className="space-y-2">
                    <Button type="submit" className="w-full" loading={verifyOtp.isPending}>
                      {t('auth.login')}
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      className="w-full"
                      disabled={resendIn > 0 || sendOtp.isPending}
                      onClick={onSendOtp}
                    >
                      {resendIn > 0 ? t('auth.resendIn', { seconds: resendIn }) : t('auth.resend')}
                    </Button>
                  </div>
                ) : (
                  <Button type="button" className="w-full" loading={sendOtp.isPending} onClick={onSendOtp}>
                    {t('auth.sendOtp')}
                  </Button>
                )}
              </form>
            </TabsContent>
          </Tabs>

          {ssoEnabled && (
            <div className="mt-5 border-t pt-4">
              <Button variant="outline" className="w-full" loading={ssoStart.isPending} onClick={() => onSso('oidc')}>
                {t('auth.sso')}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
