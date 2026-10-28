import { useEffect, useState } from 'react';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Switch } from '@/components/ui/Switch';
import { toast } from '@/components/ui/Toaster';
import { Bars, d, dt, Err, rows, Section, sel, Stat, useQ, useRun, useTitle, type Any } from '@/features/saas/components/kit';
import { websiteApi } from '../api';

const input = 'h-9 w-full rounded-md border bg-background px-2 text-sm';
const SECTION_TYPES = ['hero', 'about', 'leadership', 'programmes', 'admissions_cta', 'notices', 'events', 'gallery', 'stats', 'accreditation', 'placements', 'research', 'departments', 'colleges', 'faculty_directory', 'disclosures', 'policies', 'committees', 'contact', 'footer', 'custom_html'];

/** /admin/website — site builder: ordered sections with visibility, hero / SEO / contact, draft → preview → publish,
 * versions and rollback, live preview iframe (Prompts/40 §40.9). */
export function WebsiteBuilderPage() {
  useTitle('Website builder');
  const cfg = useQ(['web-config'], () => websiteApi.config());
  const versions = useQ(['web-versions'], () => websiteApi.versions());
  const run = useRun('Saved');
  const [draft, setDraft] = useState<Any>(null);
  const [preview, setPreview] = useState<string | null>(null);
  useEffect(() => {
    if (cfg.data?.data) setDraft(cfg.data.data);
  }, [cfg.data]);
  if (!draft) return <Err q={cfg} />;
  const sections: Any[] = [...(draft.sections ?? [])].sort((a, b) => a.sequence - b.sequence);
  const move = (i: number, by: number) => {
    const next = [...sections];
    const [s] = next.splice(i, 1);
    next.splice(Math.max(0, Math.min(next.length, i + by)), 0, s);
    setDraft({ ...draft, sections: next.map((x, n) => ({ ...x, sequence: n + 1 })) });
  };
  const set = (path: string, key: string, v: unknown) => setDraft({ ...draft, [path]: { ...(draft[path] ?? {}), [key]: v } });
  const save = () => run.mutate(() => websiteApi.saveConfig({ ...draft, sections }));
  return (
    <div className="space-y-4">
      <PageHeader
        title="Website builder"
        description={draft.has_unpublished_changes ? 'Draft has unpublished changes' : `Published · version ${draft.version}`}
        actions={
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={save}>Save draft</Button>
            <Button size="sm" variant="outline" onClick={() => run.mutate(async () => { const r: Any = await websiteApi.previewToken(); setPreview(r.data.url); })}>Preview</Button>
            <Button size="sm" onClick={() => run.mutate(async () => { await websiteApi.saveConfig({ ...draft, sections }); await websiteApi.publish(window.prompt('Publish notes') ?? undefined); })}>Publish</Button>
          </div>
        }
      />
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-4">
          <Section title="Sections">
            <ul className="divide-y text-sm">
              {sections.map((s, i) => (
                <li key={`${s.key}${i}`} className="flex items-center gap-2 py-1.5">
                  <Switch checked={s.is_visible} onCheckedChange={(v) => setDraft({ ...draft, sections: sections.map((x, n) => (n === i ? { ...x, is_visible: v } : x)) })} aria-label={`Show ${s.type}`} />
                  <span className="flex-1">{s.title || s.type.replace('_', ' ')}</span>
                  <Button size="sm" variant="ghost" aria-label="Move up" onClick={() => move(i, -1)}>↑</Button>
                  <Button size="sm" variant="ghost" aria-label="Move down" onClick={() => move(i, 1)}>↓</Button>
                  <Button size="sm" variant="ghost" aria-label="Remove" onClick={() => setDraft({ ...draft, sections: sections.filter((_, n) => n !== i) })}>✕</Button>
                </li>
              ))}
            </ul>
            <select className={sel} aria-label="Add section" value="" onChange={(e) => e.target.value && setDraft({ ...draft, sections: [...sections, { type: e.target.value, key: e.target.value, config: {}, is_visible: true, sequence: sections.length + 1 }] })}>
              <option value="">+ Add section…</option>
              {SECTION_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </Section>
          <Section title="Hero & SEO">
            <label className="block text-xs">Hero title<input className={input} value={draft.hero?.title ?? ''} onChange={(e) => set('hero', 'title', e.target.value)} /></label>
            <label className="block text-xs">Hero subtitle<input className={input} value={draft.hero?.subtitle ?? ''} onChange={(e) => set('hero', 'subtitle', e.target.value)} /></label>
            <label className="block text-xs">SEO title<input className={input} value={draft.seo?.title ?? ''} onChange={(e) => set('seo', 'title', e.target.value)} /></label>
            <label className="block text-xs">SEO description<input className={input} value={draft.seo?.description ?? ''} onChange={(e) => set('seo', 'description', e.target.value)} /></label>
            <label className="block text-xs">Theme
              <select className={sel} value={draft.theme?.name ?? 'indigo'} onChange={(e) => set('theme', 'name', e.target.value)}>
                {['indigo', 'ocean', 'grove', 'sunset', 'plum'].map((t) => <option key={t}>{t}</option>)}
              </select>
            </label>
          </Section>
          <Section title="Contact">
            {['address', 'phone', 'email'].map((k) => (
              <label key={k} className="block text-xs capitalize">{k}<input className={input} value={draft.contact?.[k] ?? ''} onChange={(e) => set('contact', k, e.target.value)} /></label>
            ))}
            <label className="flex items-center gap-2 text-xs"><Switch checked={draft.show_catalog} onCheckedChange={(v) => setDraft({ ...draft, show_catalog: v })} /> Show catalogue</label>
            <label className="flex items-center gap-2 text-xs"><Switch checked={draft.show_apply} onCheckedChange={(v) => setDraft({ ...draft, show_apply: v })} /> Show apply CTA</label>
          </Section>
          <Section title="Versions">
            <ul className="divide-y text-sm">
              {rows(versions.data).map((v) => (
                <li key={v.version} className="flex items-center justify-between py-1.5">
                  <span>v{v.version} · {dt(v.published_at)} {v.notes ? `· ${v.notes}` : ''}</span>
                  <Button size="sm" variant="outline" onClick={() => run.mutate(() => websiteApi.rollback(v.version))}>Roll back</Button>
                </li>
              ))}
            </ul>
          </Section>
        </div>
        <Section title="Live preview">
          {preview ? <iframe title="Site preview" src={preview} className="h-[70vh] w-full rounded border" /> : <p className="text-sm text-muted-foreground">Save and press Preview to see the draft.</p>}
        </Section>
      </div>
    </div>
  );
}

export function WebsiteContentPage() {
  useTitle('Website content');
  const [section, setSection] = useState('');
  const list = useQ(['web-content', section], () => websiteApi.content(section || undefined));
  const run = useRun('Saved');
  const [form, setForm] = useState<Any>({ section: 'about', slug: '', title: '', body: '', is_published: false });
  return (
    <div className="space-y-4">
      <PageHeader title="Content" description="Pages by section; college / department sub-sites use college:CODE / department:CODE." />
      <Section title="New page">
        <div className="grid gap-2 sm:grid-cols-3">
          <input className={input} placeholder="section (about, department:CSE…)" value={form.section} onChange={(e) => setForm({ ...form, section: e.target.value })} />
          <input className={input} placeholder="slug" value={form.slug} onChange={(e) => setForm({ ...form, slug: e.target.value })} />
          <input className={input} placeholder="title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
        </div>
        <textarea className="h-32 w-full rounded-md border bg-background p-2 text-sm" placeholder="HTML (sanitised on save)" value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} />
        <Button size="sm" onClick={() => run.mutate(() => websiteApi.createContent(form))}>Create</Button>
      </Section>
      <Section title="Pages" action={<input className={`${input} w-56`} placeholder="filter section" value={section} onChange={(e) => setSection(e.target.value)} />}>
        <Err q={list} />
        <table className="w-full text-sm"><tbody className="divide-y">
          {rows(list.data).map((c) => (
            <tr key={c.id}><td className="py-1.5">{c.section}</td><td>{c.slug}</td><td>{c.title}</td>
              <td className="text-right"><Switch checked={c.is_published} onCheckedChange={(v) => run.mutate(() => websiteApi.publishContent(c.id, v))} aria-label="Published" /></td>
              <td className="text-right"><Button size="sm" variant="ghost" onClick={() => run.mutate(() => websiteApi.deleteContent(c.id))}>Delete</Button></td></tr>
          ))}
        </tbody></table>
      </Section>
    </div>
  );
}

export function WebsiteNoticesPage() {
  useTitle('Website notices');
  const list = useQ(['web-notices'], () => websiteApi.notices());
  const run = useRun('Saved');
  const [picked, setPicked] = useState<string[]>([]);
  const [form, setForm] = useState<Any>({ title: '', category: 'general', body: '', is_published: true, also_announce: false });
  return (
    <div className="space-y-4">
      <PageHeader title="Notices" actions={<div className="flex gap-2">{['publish', 'unpublish', 'expire'].map((a) => <Button key={a} size="sm" variant="outline" disabled={!picked.length} onClick={() => run.mutate(async () => { const r: Any = await websiteApi.bulkNotices(picked, a); toast.success(`${r.data.succeeded} done, ${r.data.failed} failed`); setPicked([]); })}>{a}</Button>)}</div>} />
      <Section title="New notice">
        <div className="grid gap-2 sm:grid-cols-3">
          <input className={input} placeholder="Title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          <select className={sel} value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>{['general', 'admissions', 'examinations', 'tenders', 'recruitment', 'events', 'scholarships', 'results'].map((c) => <option key={c}>{c}</option>)}</select>
          <input className={input} type="datetime-local" aria-label="Publish at" onChange={(e) => setForm({ ...form, publish_at: e.target.value ? new Date(e.target.value).toISOString() : null })} />
        </div>
        <textarea className="h-24 w-full rounded-md border bg-background p-2 text-sm" value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} />
        <label className="flex items-center gap-2 text-xs"><Switch checked={form.also_announce} onCheckedChange={(v) => setForm({ ...form, also_announce: v })} /> Also announce to students & staff</label>
        <Button size="sm" disabled={!form.title} onClick={() => run.mutate(() => websiteApi.createNotice(form))}>Create</Button>
      </Section>
      <Section title="All notices">
        <Err q={list} />
        <table className="w-full text-sm"><tbody className="divide-y">
          {rows(list.data).map((n) => (
            <tr key={n.id}>
              <td><input type="checkbox" aria-label={`Select ${n.title}`} checked={picked.includes(n.id)} onChange={(e) => setPicked(e.target.checked ? [...picked, n.id] : picked.filter((x) => x !== n.id))} /></td>
              <td className="py-1.5">{n.title}{n.pinned ? ' 📌' : ''}</td><td>{n.category}</td><td>{d(n.publish_at)}</td><td><StatusBadge status={n.state} /></td>
              <td className="text-right"><Button size="sm" variant="ghost" onClick={() => run.mutate(() => websiteApi.announce(n.id))}>Announce</Button></td>
            </tr>
          ))}
        </tbody></table>
      </Section>
    </div>
  );
}

export function WebsiteEventsPage() {
  useTitle('Website events');
  const list = useQ(['web-events'], () => websiteApi.events());
  const source = useQ(['web-src-events'], () => import('@/api/axios').then(({ api }) => api.get('/events', { params: { page_size: 50 } }) as Promise<Any>));
  const run = useRun('Saved');
  const mirrored = new Set(rows(list.data).map((e) => e.event_id));
  return (
    <div className="space-y-4">
      <PageHeader title="Events" description="Mirror Phase 25 events or publish manual ones." />
      <Section title="Mirror from campus events">
        <ul className="divide-y text-sm">
          {rows(source.data?.data ? source.data : source.data).slice(0, 30).map((e) => (
            <li key={e.id} className="flex items-center justify-between py-1.5"><span>{e.title} · {d(e.from_on)} · {e.status}</span>
              <Button size="sm" variant="outline" disabled={mirrored.has(e.id)} onClick={() => run.mutate(() => websiteApi.mirror([e.id]))}>{mirrored.has(e.id) ? 'Mirrored' : 'Mirror'}</Button></li>
          ))}
        </ul>
      </Section>
      <Section title="On the website">
        <ul className="divide-y text-sm">
          {rows(list.data).map((e) => <li key={e.id} className="flex justify-between py-1.5"><span>{e.title} · {d(e.starts_at)}</span><Button size="sm" variant="ghost" onClick={() => run.mutate(() => websiteApi.deleteEvent(e.id))}>Remove</Button></li>)}
        </ul>
      </Section>
    </div>
  );
}

export function WebsiteGalleryPage() {
  useTitle('Gallery');
  const list = useQ(['web-albums'], () => websiteApi.albums());
  const run = useRun('Saved');
  const [title, setTitle] = useState('');
  return (
    <div className="space-y-4">
      <PageHeader title="Gallery" actions={<div className="flex gap-2"><input className={input} placeholder="Album title" value={title} onChange={(e) => setTitle(e.target.value)} /><Button size="sm" disabled={!title} onClick={() => run.mutate(() => websiteApi.createAlbum({ title, is_published: true }))}>Add album</Button></div>} />
      <Err q={list} />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {rows(list.data).map((a) => (
          <Section key={a.id} title={`${a.title} (${a.image_count})`} action={<Button size="sm" variant="ghost" onClick={() => run.mutate(() => websiteApi.deleteAlbum(a.id))}>Delete</Button>}>
            <div className="grid grid-cols-4 gap-1">{(a.images ?? []).slice(0, 8).map((i: Any) => <img key={i.id} src={i.image_url} alt={i.caption ?? ''} className="aspect-square w-full rounded object-cover" loading="lazy" />)}</div>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={() => { const u = window.prompt('Image URL'); if (u) run.mutate(() => websiteApi.addImage(a.id, { image_url: u })); }}>Add image</Button>
              <Button size="sm" variant="outline" onClick={() => { const u = window.prompt('Uploaded zip URL'); if (u) run.mutate(() => websiteApi.bulkUpload(a.id, u)); }}>Bulk upload (zip)</Button>
            </div>
          </Section>
        ))}
      </div>
    </div>
  );
}

export function WebsiteEnquiriesPage() {
  useTitle('Website enquiries');
  const [status, setStatus] = useState('');
  const list = useQ(['web-enq', status], () => websiteApi.enquiries({ status: status || undefined }));
  const run = useRun('Saved');
  return (
    <div className="space-y-4">
      <PageHeader title="Enquiries" actions={<div className="flex gap-2"><select className={sel} value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status"><option value="">All</option>{['new', 'contacted', 'converted', 'spam', 'closed'].map((s) => <option key={s}>{s}</option>)}</select><Button size="sm" variant="outline" onClick={() => run.mutate(() => websiteApi.exportEnquiries())}>Export</Button></div>} />
      <Err q={list} />
      <table className="w-full text-sm"><tbody className="divide-y">
        {rows(list.data).map((e) => (
          <tr key={e.id}><td className="py-1.5">{e.name}<br /><small className="text-muted-foreground">{e.phone} {e.email}</small></td><td>{e.subject}</td><td>{d(e.created_at)}</td>
            <td><select className={sel} value={e.status} aria-label="Status" onChange={(ev) => run.mutate(() => websiteApi.enquiryStatus(e.id, ev.target.value))}>{['new', 'contacted', 'converted', 'spam', 'closed'].map((s) => <option key={s}>{s}</option>)}</select></td>
            <td className="text-right">{e.enquiry_id ? <span className="text-xs">In CRM</span> : <Button size="sm" variant="outline" onClick={() => run.mutate(() => websiteApi.linkCrm(e.id))}>Link CRM</Button>}</td></tr>
        ))}
      </tbody></table>
    </div>
  );
}

export function WebsiteCataloguePage() {
  useTitle('Catalogue');
  const cfg = useQ(['web-cat'], () => websiteApi.catalogue());
  const preview = useQ(['web-cat-prev'], () => websiteApi.cataloguePreview());
  const run = useRun('Saved');
  const c: Any = cfg.data?.data;
  const progs: Any[] = c?.programmes ?? [];
  const upd = (pid: string, k: string, v: boolean) => {
    const exists = progs.some((p) => p.program_id === pid);
    const next = exists ? progs.map((p) => (p.program_id === pid ? { ...p, [k]: v } : p)) : [...progs, { program_id: pid, visible: true, show_fees: false, highlight: false, [k]: v }];
    run.mutate(() => websiteApi.saveCatalogue({ ...c, programmes: next }));
  };
  return (
    <div className="space-y-4">
      <PageHeader title="Catalogue visibility" />
      <Err q={cfg} />
      <Section title="Programmes (as the public sees them)">
        <ul className="divide-y text-sm">{rows(preview.data).map((p) => <li key={p.code} className="py-1.5">{p.code} — {p.name} · intake {p.intake ?? '—'} {p.apply_url ? '· applications open' : ''}</li>)}</ul>
      </Section>
      <Section title="Settings">
        {progs.map((p) => (
          <div key={p.program_id} className="flex flex-wrap items-center gap-4 text-sm"><code className="text-xs">{p.program_id.slice(0, 8)}</code>
            {(['visible', 'show_fees', 'highlight'] as const).map((k) => <label key={k} className="flex items-center gap-1">{k}<Switch checked={Boolean(p[k])} onCheckedChange={(v) => upd(p.program_id, k, v)} /></label>)}
          </div>
        ))}
        <label className="block text-xs">Hidden course codes (comma separated)
          <input className={input} defaultValue={(c?.courses_hidden ?? []).join(', ')} onBlur={(e) => run.mutate(() => websiteApi.saveCatalogue({ ...c, courses_hidden: e.target.value.split(',').map((x) => x.trim()).filter(Boolean) }))} />
        </label>
      </Section>
    </div>
  );
}

export function WebsiteDisclosuresPage() {
  useTitle('Disclosures');
  const cfg = useQ(['web-disc'], () => websiteApi.disclosures());
  const dir = useQ(['web-dir'], () => websiteApi.directory());
  const run = useRun('Saved');
  const items: Any[] = cfg.data?.data?.items ?? [];
  const save = (next: Any[]) => run.mutate(() => websiteApi.saveDisclosures({ items: next }));
  return (
    <div className="space-y-4">
      <PageHeader title="Disclosures & faculty directory" actions={<Button size="sm" variant="outline" onClick={() => { const key = window.prompt('Metric key or item key'); if (key) save([...items, { key, title: key, source: 'metric', ref: key, is_published: false }]); }}>Add item</Button>} />
      <Err q={cfg} />
      <Section title="Mandatory disclosures">
        <ul className="divide-y text-sm">{items.map((i, n) => (
          <li key={i.key} className="flex items-center gap-2 py-1.5"><span className="rounded bg-muted px-1.5 text-[10px] uppercase">{i.source}</span><span className="flex-1">{i.title}</span>
            <Switch checked={i.is_published} aria-label="Published" onCheckedChange={(v) => save(items.map((x, m) => (m === n ? { ...x, is_published: v } : x)))} /></li>
        ))}</ul>
      </Section>
      <Section title="Faculty directory fields">
        <p className="text-sm">{(dir.data?.data?.fields ?? []).join(', ') || '—'}</p>
      </Section>
    </div>
  );
}

export function WebsiteDomainsPage() {
  useTitle('Domains');
  const list = useQ(['web-domains'], () => websiteApi.domains());
  const run = useRun();
  const [host, setHost] = useState('');
  const steps = ['pending', 'provisioning', 'active'];
  return (
    <div className="space-y-4">
      <PageHeader title="Custom domains" actions={<div className="flex gap-2"><input className={input} placeholder="www.example.edu.in" value={host} onChange={(e) => setHost(e.target.value.toLowerCase())} /><Button size="sm" disabled={!host} onClick={() => run.mutate(() => websiteApi.addDomain(host, false))}>Add</Button></div>} />
      <Err q={list} />
      {rows(list.data).map((dm) => (
        <Section key={dm.id} title={`${dm.hostname}${dm.is_primary ? ' (primary)' : ''}`} action={<div className="flex gap-2"><Button size="sm" variant="outline" onClick={() => run.mutate(async () => { const r: Any = await websiteApi.verifyDomain(dm.id); toast[r.data.ok ? 'success' : 'error'](r.data.message); })}>Verify</Button><Button size="sm" variant="outline" disabled={!dm.verified_at || dm.is_primary} onClick={() => run.mutate(() => websiteApi.primaryDomain(dm.id))}>Make primary</Button><Button size="sm" variant="ghost" onClick={() => run.mutate(() => websiteApi.deleteDomain(dm.id))}>Remove</Button></div>}>
          <ol className="flex gap-2 text-xs" aria-label="SSL status">{steps.map((s) => <li key={s} className={`rounded-full border px-2 py-0.5 ${steps.indexOf(dm.ssl_status) >= steps.indexOf(s) ? 'bg-primary text-primary-foreground' : ''}`}>{s}</li>)}{dm.ssl_status === 'failed' && <li className="text-destructive">failed</li>}</ol>
          <div className="space-y-1 rounded bg-muted p-2 font-mono text-xs">
            <div>TXT {dm.dns_instructions?.txt_name} = {dm.dns_instructions?.txt_value}</div>
            <div>CNAME {dm.hostname} → {dm.dns_instructions?.cname_target}</div>
          </div>
          <p className="text-xs text-muted-foreground">DNS changes can take up to an hour; we re-check every 15 minutes for 72 hours.</p>
        </Section>
      ))}
    </div>
  );
}

export function WebsiteAnalyticsPage() {
  useTitle('Website analytics');
  const a = useQ(['web-an'], () => websiteApi.analytics());
  const data: Any = a.data?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="Website analytics" description="Privacy-friendly counters (no cookies, no raw IPs)." />
      <Err q={a} />
      {data && (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <Stat label="Page views (30 d)" value={Object.values(data.pageviews_by_day as Record<string, number>).reduce((x, y) => x + y, 0)} />
            <Stat label="Visitors (30 d, daily unique)" value={Object.values(data.visitors_by_day as Record<string, number>).reduce((x, y) => x + y, 0)} />
            <Stat label="Enquiries converted" value={data.enquiry_conversions?.converted ?? 0} />
          </div>
          <Section title="Top pages"><Bars points={(data.top_pages as Any[]).map((p) => ({ label: p.path, value: p.views }))} /></Section>
        </>
      )}
    </div>
  );
}

/** /super-admin/marketing — marketing site editor (hero, features, FAQ, legal links) with publish; pricing from plans. */
export function MarketingSitePage() {
  useTitle('Marketing site');
  const q = useQ(['mkt'], () => websiteApi.marketing());
  const run = useRun('Saved');
  const [text, setText] = useState('');
  useEffect(() => {
    if (q.data?.data) {
      const { pricing: _p, published_at: _a, has_unpublished_changes: _h, ...body } = q.data.data as Any;
      setText(JSON.stringify(body, null, 2));
    }
  }, [q.data]);
  const m: Any = q.data?.data;
  return (
    <div className="space-y-4">
      <PageHeader title="Marketing site" description={m ? `Published ${dt(m.published_at)}${m.has_unpublished_changes ? ' · draft pending' : ''}` : ''} actions={<div className="flex gap-2"><Button size="sm" variant="outline" onClick={() => run.mutate(() => websiteApi.saveMarketing(JSON.parse(text)))}>Save draft</Button><Button size="sm" onClick={() => run.mutate(() => websiteApi.publishMarketing())}>Publish</Button></div>} />
      <Err q={q} />
      <textarea aria-label="Marketing content (JSON)" className="h-[50vh] w-full rounded-md border bg-background p-2 font-mono text-xs" value={text} onChange={(e) => setText(e.target.value)} />
      <Section title="Pricing (from plans)"><ul className="text-sm">{(m?.pricing ?? []).map((p: Any) => <li key={p.code}>{p.name} — ₹ {(Number(p.price_paise_monthly ?? 0) / 100).toLocaleString('en-IN')} / month</li>)}</ul></Section>
    </div>
  );
}
