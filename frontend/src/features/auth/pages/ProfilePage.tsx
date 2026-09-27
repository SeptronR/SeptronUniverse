import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useSearchParams } from 'react-router-dom';
import { Laptop, LogOut, ShieldCheck, ShieldOff } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { FormField } from '@/components/shared/FormField';
import { Button } from '@/components/ui/Button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/Card';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Switch } from '@/components/ui/Switch';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { useAuthStore } from '@/store/authStore';
import { useFeature } from '@/hooks/useFeature';
import { formatDateTime, formatRelative, titleCase } from '@/utils/formatters';
import { passwordPolicy } from '@/utils/validators';
import {
  useChangePassword,
  useLoginHistory,
  useMfaConfirm,
  useMfaDisable,
  useMfaSetup,
  useMyConsents,
  useRecordConsent,
  useRecoveryCodes,
  useRevokeOtherSessions,
  useRevokeSession,
  useSessions,
} from '../hooks';

const CONSENT_PURPOSES = ['communication', 'marketing', 'photo', 'third_party'] as const;

const passwordSchema = z
  .object({ current_password: z.string().min(1, 'Required'), new_password: passwordPolicy, confirm: z.string() })
  .refine((v) => v.new_password === v.confirm, { path: ['confirm'], message: 'Passwords do not match' });
type PasswordForm = z.infer<typeof passwordSchema>;

/**
 * /profile — details, change password (forced when `?change=1`), MFA enrolment with QR, active sessions,
 * login history and DPDP consents (Prompts/02 §02.9).
 */
export default function ProfilePage() {
  const [params] = useSearchParams();
  const user = useAuthStore((s) => s.currentUser);
  const sessionsEnabled = useFeature('security.session_management');
  const mfaEnabled = useFeature('security.mfa');
  const consentEnabled = useFeature('privacy.dpdp_consent');
  const mustChange = !!user?.must_change_password || params.get('change') === '1';

  const changePassword = useChangePassword();
  const mfaSetup = useMfaSetup();
  const mfaConfirm = useMfaConfirm();
  const mfaDisable = useMfaDisable();
  const recoveryCodes = useRecoveryCodes();
  const sessions = useSessions();
  const revokeSession = useRevokeSession();
  const revokeOthers = useRevokeOtherSessions();
  const history = useLoginHistory();
  const consents = useMyConsents();
  const recordConsent = useRecordConsent();

  const [enrolment, setEnrolment] = useState<{ secret: string; qr: string } | null>(null);
  const [code, setCode] = useState('');
  const [codes, setCodes] = useState<string[] | null>(null);
  const [disableOpen, setDisableOpen] = useState(false);
  const [disableForm, setDisableForm] = useState({ password: '', code: '' });

  const form = useForm<PasswordForm>({
    resolver: zodResolver(passwordSchema),
    defaultValues: { current_password: '', new_password: '', confirm: '' },
  });

  const onChangePassword = async (values: PasswordForm) => {
    try {
      await changePassword.mutateAsync({ current_password: values.current_password, new_password: values.new_password });
      form.reset();
      toast.success('Password changed');
    } catch (e) {
      toast.error(getApiError(e, 'Could not change the password'));
    }
  };

  const startEnrolment = async () => {
    try {
      const res = await mfaSetup.mutateAsync();
      setEnrolment({ secret: res.data.secret, qr: res.data.qr_png_base64 });
    } catch (e) {
      toast.error(getApiError(e, 'Could not start MFA enrolment'));
    }
  };

  const confirmEnrolment = async () => {
    try {
      const res = await mfaConfirm.mutateAsync(code);
      setCodes(res.data.recovery_codes);
      setEnrolment(null);
      setCode('');
      toast.success('Multi-factor authentication enabled');
    } catch (e) {
      toast.error(getApiError(e, 'Invalid code'));
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="My profile"
        description={user?.display_name ?? user?.username}
        actions={
          <div className="flex items-center gap-2">
            {user?.role_slugs.map((r) => (
              <Badge key={r} variant="secondary">
                {titleCase(r)}
              </Badge>
            ))}
          </div>
        }
      />

      {mustChange && (
        <div role="alert" className="rounded-md border border-warning bg-warning/10 p-3 text-sm">
          Your password must be changed before you can use the rest of the workspace.
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Change password</CardTitle>
            <CardDescription>At least 10 characters with 3 of 4 character classes; the last 5 cannot be reused.</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={form.handleSubmit(onChangePassword)} noValidate>
              <FormField
                label="Current password"
                type="password"
                autoComplete="current-password"
                error={form.formState.errors.current_password}
                {...form.register('current_password')}
              />
              <FormField
                label="New password"
                type="password"
                autoComplete="new-password"
                error={form.formState.errors.new_password}
                {...form.register('new_password')}
              />
              <FormField
                label="Confirm new password"
                type="password"
                autoComplete="new-password"
                error={form.formState.errors.confirm}
                {...form.register('confirm')}
              />
              <Button type="submit" loading={changePassword.isPending}>
                Change password
              </Button>
            </form>
          </CardContent>
        </Card>

        {mfaEnabled && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <ShieldCheck className="h-4 w-4" /> Multi-factor authentication
              </CardTitle>
              <CardDescription>
                {user?.username} · {useAuthStore.getState().currentUser ? '' : ''}
                Required for privileged roles (exam control, registrar, platform).
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {enrolment ? (
                <div className="space-y-3">
                  <img
                    src={`data:image/png;base64,${enrolment.qr}`}
                    alt="Scan this QR code with your authenticator app"
                    className="h-40 w-40 rounded border bg-white p-2"
                  />
                  <p className="text-xs text-muted-foreground">
                    Or enter the secret manually: <code className="rounded bg-muted px-1">{enrolment.secret}</code>
                  </p>
                  <div className="flex items-end gap-2">
                    <FormField
                      label="Code from the app"
                      inputMode="numeric"
                      maxLength={6}
                      value={code}
                      onChange={(e) => setCode(e.target.value)}
                    />
                    <Button onClick={confirmEnrolment} loading={mfaConfirm.isPending}>
                      Confirm
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="flex flex-wrap items-center gap-2">
                  <Button variant="outline" onClick={startEnrolment} loading={mfaSetup.isPending}>
                    <ShieldCheck className="h-4 w-4" /> Set up authenticator
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={async () => {
                      try {
                        const res = await recoveryCodes.mutateAsync();
                        setCodes(res.data.recovery_codes);
                      } catch (e) {
                        toast.error(getApiError(e, 'MFA is not enabled'));
                      }
                    }}
                    loading={recoveryCodes.isPending}
                  >
                    New recovery codes
                  </Button>
                  <Button variant="ghost" className="text-destructive" onClick={() => setDisableOpen(true)}>
                    <ShieldOff className="h-4 w-4" /> Disable
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        )}
      </div>

      {sessionsEnabled && (
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2 text-base">
                <Laptop className="h-4 w-4" /> Active sessions
              </CardTitle>
              <CardDescription>Signing out of a device revokes its refresh token immediately.</CardDescription>
            </div>
            <Button
              variant="outline"
              size="sm"
              loading={revokeOthers.isPending}
              onClick={() =>
                revokeOthers.mutate(undefined, {
                  onSuccess: () => toast.success('Other sessions revoked'),
                  onError: (e) => toast.error(getApiError(e)),
                })
              }
            >
              <LogOut className="h-4 w-4" /> Revoke others
            </Button>
          </CardHeader>
          <CardContent className="space-y-2">
            {(sessions.data?.data ?? []).map((s) => (
              <div key={s.id} className="flex items-center justify-between rounded-md border p-2 text-sm">
                <div>
                  <p className="font-medium">
                    {s.device_label ?? 'Unknown device'} {s.current && <Badge variant="info">This device</Badge>}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {s.platform ?? '—'} · {s.ip_masked ?? '—'} · last seen {formatRelative(s.last_seen_at)}
                  </p>
                </div>
                {!s.current && (
                  <Button
                    variant="ghost"
                    size="sm"
                    loading={revokeSession.isPending && revokeSession.variables === s.id}
                    onClick={() =>
                      revokeSession.mutate(s.id, {
                        onSuccess: () => toast.success('Session revoked'),
                        onError: (e) => toast.error(getApiError(e)),
                      })
                    }
                  >
                    Revoke
                  </Button>
                )}
              </div>
            ))}
            {sessions.data?.data.length === 0 && <p className="text-sm text-muted-foreground">No active sessions.</p>}
          </CardContent>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Recent sign-in attempts</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            {(history.data?.data ?? []).slice(0, 10).map((h) => (
              <div key={h.id} className="flex items-center justify-between text-sm">
                <StatusBadge status={h.outcome === 'success' ? 'approved' : h.outcome} />
                <span className="text-xs text-muted-foreground">{formatDateTime(h.occurred_at)}</span>
              </div>
            ))}
            {history.data?.data.length === 0 && <p className="text-sm text-muted-foreground">Nothing yet.</p>}
          </CardContent>
        </Card>

        {consentEnabled && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Consents (DPDP)</CardTitle>
              <CardDescription>You can withdraw a consent at any time; every change is recorded.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {CONSENT_PURPOSES.map((purpose) => {
                const current = consents.data?.data.find((c) => c.purpose === purpose);
                return (
                  <div key={purpose} className="flex items-center justify-between">
                    <span className="text-sm">{titleCase(purpose)}</span>
                    <Switch
                      checked={!!current?.granted}
                      onCheckedChange={(granted) =>
                        recordConsent.mutate(
                          { purpose, granted },
                          {
                            onSuccess: () => toast.success(granted ? 'Consent recorded' : 'Consent withdrawn'),
                            onError: (e) => toast.error(getApiError(e)),
                          },
                        )
                      }
                      aria-label={`Consent for ${purpose}`}
                    />
                  </div>
                );
              })}
            </CardContent>
          </Card>
        )}
      </div>

      <Modal
        open={!!codes}
        onOpenChange={() => setCodes(null)}
        title="Recovery codes"
        description="Store these somewhere safe — each code works once if you lose your authenticator."
        footer={<Button onClick={() => setCodes(null)}>Done</Button>}
      >
        <ul className="grid grid-cols-2 gap-2 font-mono text-sm">
          {(codes ?? []).map((c) => (
            <li key={c} className="rounded bg-muted px-2 py-1">
              {c}
            </li>
          ))}
        </ul>
      </Modal>

      <Modal
        open={disableOpen}
        onOpenChange={setDisableOpen}
        title="Disable multi-factor authentication"
        description="Confirm with your password and a current code."
        footer={
          <>
            <Button variant="ghost" onClick={() => setDisableOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              loading={mfaDisable.isPending}
              onClick={() =>
                mfaDisable.mutate(disableForm, {
                  onSuccess: () => {
                    setDisableOpen(false);
                    setDisableForm({ password: '', code: '' });
                    toast.success('Multi-factor authentication disabled');
                  },
                  onError: (e) => toast.error(getApiError(e)),
                })
              }
            >
              Disable
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <FormField
            label="Password"
            type="password"
            value={disableForm.password}
            onChange={(e) => setDisableForm((f) => ({ ...f, password: e.target.value }))}
          />
          <FormField
            label="Code"
            inputMode="numeric"
            value={disableForm.code}
            onChange={(e) => setDisableForm((f) => ({ ...f, code: e.target.value }))}
          />
        </div>
      </Modal>
    </div>
  );
}
