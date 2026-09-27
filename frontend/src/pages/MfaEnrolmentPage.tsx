import { useEffect, useState } from 'react';
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { ShieldCheck } from 'lucide-react';
import { api, getApiError } from '@/api/axios';
import { Button } from '@/components/ui/Button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/Card';
import { FormField } from '@/components/shared/FormField';
import { toast } from '@/components/ui/Toaster';
import type { Envelope } from '@/utils/types';
import { homeFor, refreshPrincipal } from '@/features/auth/hooks';
import { useAuthStore } from '@/store/authStore';
import type { MfaConfirmResponse, MfaSetup } from '@/features/auth/types';

/**
 * /mfa-setup?token=… — enrolment for a role that **requires** MFA before it may hold a session: the login answered
 * `403 MFA_REQUIRED` with a 10-minute `mfa_setup` token, which is the only credential this page has. Confirming
 * returns the recovery codes **and** opens the session (Prompts/02 §02.6 rule 6), so the user lands on their home.
 */
export default function MfaEnrolmentPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get('token') ?? '';
  const [setup, setSetup] = useState<MfaSetup | null>(null);
  const [code, setCode] = useState('');
  const [codes, setCodes] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    void (async () => {
      try {
        const res = (await api.post('/auth/mfa/setup', undefined, {
          idempotent: false,
          headers: { Authorization: `Bearer ${token}` },
        })) as unknown as Envelope<MfaSetup>;
        if (!cancelled) setSetup(res.data);
      } catch (e) {
        toast.error(getApiError(e, 'This enrolment link has expired — sign in again'));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (!token) return <Navigate to="/login" replace />;

  const confirm = async () => {
    setBusy(true);
    try {
      const res = (await api.post(
        '/auth/mfa/confirm',
        { code },
        { idempotent: false, headers: { Authorization: `Bearer ${token}` } },
      )) as unknown as Envelope<MfaConfirmResponse>;
      setCodes(res.data.recovery_codes);
      if (res.data.access_token) {
        useAuthStore.getState().setAccessToken(res.data.access_token);
        await refreshPrincipal();
      }
      toast.success('Multi-factor authentication enabled');
    } catch (e) {
      toast.error(getApiError(e, 'Invalid code'));
    } finally {
      setBusy(false);
    }
  };

  const user = useAuthStore.getState().currentUser;

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="items-center text-center">
          <ShieldCheck className="h-9 w-9 text-primary" />
          <CardTitle className="text-lg">Set up multi-factor authentication</CardTitle>
          <CardDescription>Your role requires a second factor. Scan the code with an authenticator app.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {codes ? (
            <>
              <p className="text-sm">Store these recovery codes safely — each one works once.</p>
              <ul className="grid grid-cols-2 gap-2 font-mono text-sm">
                {codes.map((c) => (
                  <li key={c} className="rounded bg-muted px-2 py-1">
                    {c}
                  </li>
                ))}
              </ul>
              <Button
                className="w-full"
                onClick={() =>
                  navigate(user ? homeFor(user.role_slugs, user.is_super_admin) : '/login', { replace: true })
                }
              >
                Continue
              </Button>
            </>
          ) : (
            <>
              {setup && (
                <div className="space-y-2 text-center">
                  <img
                    src={`data:image/png;base64,${setup.qr_png_base64}`}
                    alt="Scan this QR code with your authenticator app"
                    className="mx-auto h-44 w-44 rounded border bg-white p-2"
                  />
                  <p className="text-xs text-muted-foreground">
                    Or enter the secret manually: <code className="rounded bg-muted px-1">{setup.secret}</code>
                  </p>
                </div>
              )}
              <FormField
                label="Code from the app"
                inputMode="numeric"
                maxLength={6}
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
              <Button className="w-full" loading={busy} disabled={!setup} onClick={confirm}>
                Confirm and sign in
              </Button>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
