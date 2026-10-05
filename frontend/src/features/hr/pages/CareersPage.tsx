import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getApiError } from '@/api/axios';
import { FormField } from '@/components/shared/FormField';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Select } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { hrApi } from '../api';
import { label, type PublicPosting } from '../types';

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/** Public /careers?institution=<slug> — open postings and the application form (no sign-in). */
export default function CareersPage() {
  const [params] = useSearchParams();
  const institution = params.get('institution') ?? import.meta.env.VITE_DEFAULT_INSTITUTION ?? 'demo-uni';
  const list = useQuery({ queryKey: ['careers', institution], queryFn: () => hrApi.publicPostings(institution), retry: false });
  const [applyTo, setApplyTo] = useState<PublicPosting | null>(null);
  const [form, setForm] = useState({ name: '', email: '', phone: '', highest_qualification: '', experience_months: '0', category: 'GEN' });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    document.title = 'Careers';
  }, []);
  const submit = async () => {
    const e: Record<string, string> = {};
    if (form.name.trim().length < 2) e.name = 'Enter your full name';
    if (!EMAIL.test(form.email)) e.email = 'Enter a valid e-mail';
    if (!/^\+?[0-9 -]{8,20}$/.test(form.phone)) e.phone = 'Enter a valid phone number';
    setErrors(e);
    if (Object.keys(e).length || !applyTo) return;
    setBusy(true);
    try {
      const r = await hrApi.publicApply(applyTo.id, {
        applicant: { name: form.name, email: form.email, phone: form.phone, highest_qualification: form.highest_qualification || undefined, experience_months: Number(form.experience_months) || 0 },
        category: form.category,
      });
      toast.success(`Application received — reference ${r.data.reference}`);
      setApplyTo(null);
    } catch (err) {
      toast.error(getApiError(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <main className="mx-auto max-w-4xl space-y-4 p-6">
      <h1 className="text-2xl font-semibold">Careers</h1>
      {list.isError && <p className="text-sm text-muted-foreground">{getApiError(list.error)}</p>}
      {list.data?.data.length === 0 && <p className="text-sm text-muted-foreground">There are no open positions right now.</p>}
      {(list.data?.data ?? []).map((p) => (
        <Card key={p.id}>
          <CardHeader>
            <CardTitle className="flex items-center justify-between text-lg">{p.title} <Badge variant="outline">{p.vacancies} post(s)</Badge></CardTitle>
            <p className="text-sm text-muted-foreground">{p.department ?? ''} · {label(p.cadre)} {p.closes_at ? `· apply by ${new Date(p.closes_at).toLocaleDateString()}` : ''}</p>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {p.description && <p>{p.description}</p>}
            {p.reservation?.vacancies && <p className="text-xs text-muted-foreground">Reservation: {Object.entries(p.reservation.vacancies).map(([k, v]) => `${k} ${v}`).join(', ')}</p>}
            <Button onClick={() => setApplyTo(p)}>Apply</Button>
          </CardContent>
        </Card>
      ))}
      <Modal open={applyTo !== null} onOpenChange={(o) => !o && setApplyTo(null)} title={`Apply · ${applyTo?.title ?? ''}`} footer={<Button loading={busy} onClick={submit}>Submit application</Button>}>
        <div className="grid gap-3 sm:grid-cols-2">
          <FormField label="Full name" required value={form.name} error={errors.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="sm:col-span-2" />
          <FormField label="E-mail" required type="email" value={form.email} error={errors.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <FormField label="Phone" required value={form.phone} error={errors.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
          <FormField label="Highest qualification" value={form.highest_qualification} onChange={(e) => setForm({ ...form, highest_qualification: e.target.value })} />
          <FormField label="Experience (months)" type="number" value={form.experience_months} onChange={(e) => setForm({ ...form, experience_months: e.target.value })} />
          <label className="space-y-1.5 text-sm font-medium">
            Category
            <Select options={['GEN', 'EWS', 'OBC-NCL', 'SC', 'ST'].map((c) => ({ value: c, label: c }))} value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} />
          </label>
        </div>
      </Modal>
    </main>
  );
}
