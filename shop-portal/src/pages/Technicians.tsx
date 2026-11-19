import { useState } from 'react';

import { Avatar } from '../components/Icon';
import { Button, ChipGroup, Empty, ErrorAlert, Switch } from '../components/ui';
import { api } from '../lib/api';
import { label, useAction, useLiveData, usePortal } from '../lib/hooks';
import type { EmailLink, TechPermissions, Technician, WorkingHours } from '../lib/types';

const DAYS = [['mon', 'Mon'], ['tue', 'Tue'], ['wed', 'Wed'], ['thu', 'Thu'], ['fri', 'Fri'], ['sat', 'Sat'], ['sun', 'Sun']] as const;
const DEFAULT_HOURS: WorkingHours = Object.fromEntries(
  DAYS.slice(0, 5).map(([d]) => [d, [['08:00', '17:00']]]),
);

type Draft = Pick<Technician, 'name' | 'phone' | 'equipment_types' | 'certifications' |
  'service_radius_km' | 'working_hours' | 'is_active'> & TechPermissions & { external_id?: string | null };

const DEFAULT_PERMISSIONS: TechPermissions = {
  can_respond_offers: true, can_contact_customers: true, schedule_view: 'full',
};

const emptyDraft = (): Draft => ({
  name: '', phone: '', equipment_types: [], certifications: [],
  service_radius_km: 25, working_hours: DEFAULT_HOURS, is_active: true, ...DEFAULT_PERMISSIONS,
});

const APP_STATUS: Record<Technician['app_status'], [string, string]> = {
  none: ['Not invited', 'neutral'],
  invited: ['Invite sent', 'amber'],
  active: ['Using the app', 'success'],
  disabled: ['Access removed', 'danger'],
};

export function TechniciansPage() {
  const { options, me } = usePortal();
  const techs = useLiveData(() => api.technicians());
  const [editing, setEditing] = useState<Technician | 'new' | null>(null);
  const [inviting, setInviting] = useState<Technician | null>(null);
  const removeAccess = useAction(async (t: Technician) => {
    await api.removeAppAccess(t.id);
    await techs.reload();
  });
  const importNow = useAction(async () => { await api.importTechnicians(); await techs.reload(); });
  const toggle = useAction(async (t: Technician) => {
    await api.updateTechnician(t.id, { is_active: !t.is_active });
    await techs.reload();
  });

  return (
    <>
      <div className="row between">
        <h1>Technicians</h1>
        <div className="row">
          {me.shop.scheduling_provider !== 'none' ? (
            <Button icon="refresh" busy={importNow.busy} onClick={() => importNow.run()}>Import from scheduling software</Button>
          ) : null}
          <Button variant="primary" icon="plus" onClick={() => setEditing('new')}>Add technician</Button>
        </div>
      </div>
      <p className="muted">
        Technicians can't sign up on their own: add them, then send an email invite from their row. Once they've joined,
        they sign in at{' '}
        {options ? <a href={options.features.technician_sign_in_url} target="_blank" rel="noreferrer">{options.features.technician_sign_in_url}</a> : 'the technician app'}.
      </p>
      <ErrorAlert message={techs.error ?? importNow.error ?? toggle.error ?? removeAccess.error} />
      {inviting ? (
        <InviteDialog tech={inviting} onClose={() => { setInviting(null); void techs.reload(); }} />
      ) : null}
      {editing ? (
        <TechnicianForm tech={editing === 'new' ? null : editing}
          onDone={() => { setEditing(null); void techs.reload(); }} />
      ) : null}
      <div className="card table-wrap">
        {techs.data?.length ? (
          <table className="table">
            <thead><tr><th>Name</th><th>Qualified for</th><th>Certifications</th><th>Hours</th><th>Technician app</th><th>Active</th><th /></tr></thead>
            <tbody>
              {techs.data.map((t) => (
                <tr key={t.id}>
                  <td><span className="row" style={{ flexWrap: 'nowrap' }}><Avatar name={t.name} size={30} /><span style={{ whiteSpace: 'nowrap' }}><strong>{t.name}</strong>
                    {t.rating ? <span className="small muted"> · ★ {t.rating.toFixed(1)}</span> : null}</span></span></td>
                  <td className="small">{t.equipment_types.map((e) => label(options, 'equipment_types', e)).join(', ') || '—'}</td>
                  <td className="small">{t.certifications.map((c) => label(options, 'certifications', c)).join(', ') || '—'}</td>
                  <td className="small">{hoursSummary(t.working_hours)}</td>
                  <td className="small">
                    <div className="stack" style={{ gap: 4, alignItems: 'flex-start' }}>
                      <span className={`badge ${APP_STATUS[t.app_status][1]}`}>{APP_STATUS[t.app_status][0]}</span>
                      {t.app_status === 'active' ? (
                        <>
                          <span className="muted">{permissionSummary(t)}</span>
                          <Button size="small" variant="danger" busy={removeAccess.busy}
                            onClick={() => { if (window.confirm(`Remove ${t.name}'s app access? They're signed out right away.`)) void removeAccess.run(t); }}>
                            Remove access
                          </Button>
                        </>
                      ) : (
                        <Button size="small" icon="mail" onClick={() => setInviting(t)}>
                          {t.app_status === 'invited' ? 'Resend invite' : 'Invite to app'}
                        </Button>
                      )}
                    </div>
                  </td>
                  <td><Switch checked={t.is_active} label={`${t.name} active`} onChange={() => toggle.run(t)} /></td>
                  <td><Button size="small" onClick={() => setEditing(t)}>Edit</Button></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : techs.data ? <Empty icon="users">No technicians yet. Add your first one to start receiving jobs.</Empty> : 'Loading…'}
      </div>
    </>
  );
}

function TechnicianForm({ tech, onDone }: { tech: Technician | null; onDone: () => void }) {
  const { options, me } = usePortal();
  const hcp = me?.shop.scheduling_provider === 'housecall_pro';
  const [draft, setDraft] = useState<Draft>(() => (tech ? { ...tech, phone: tech.phone ?? '' } : emptyDraft()));
  const phoneLocked = tech?.app_status === 'active';
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft((d) => ({ ...d, [key]: value }));
  const save = useAction(async () => {
    if (tech) {
      const { phone, ...rest } = draft;
      await api.updateTechnician(tech.id, phoneLocked ? rest : { ...rest, phone });
    }
    else await api.createTechnician(draft);
    onDone();
  });

  const setDay = (day: string, on: boolean, start = '08:00', end = '17:00') => {
    const hours = { ...draft.working_hours };
    if (on) hours[day] = [[start, end]];
    else delete hours[day];
    set('working_hours', hours);
  };

  return (
    <form className="card" onSubmit={(e) => { e.preventDefault(); void save.run(); }} aria-label="Technician details">
      <h2>{tech ? `Edit ${tech.name}` : 'Add technician'}</h2>
      <div className="grid-2">
        <div className="field">
          <label htmlFor="tech-name">Full name</label>
          <input id="tech-name" className="input" required value={draft.name} onChange={(e) => set('name', e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="tech-phone">Mobile number</label>
          <input id="tech-phone" className="input" type="tel" value={draft.phone ?? ''} disabled={phoneLocked}
            onChange={(e) => set('phone', e.target.value)} />
          {phoneLocked ? <span className="small muted">They sign in with this number, so only they can change it.</span> : null}
        </div>
      </div>
      <div className="field">
        <span className="label">Qualified for</span>
        <ChipGroup label="Qualified for" options={(options?.equipment_types ?? []).filter((o) => o.value !== 'unknown')}
          value={draft.equipment_types} onChange={(v) => set('equipment_types', v)} />
      </div>
      <div className="field">
        <span className="label">Certifications</span>
        <ChipGroup label="Certifications" options={options?.certifications ?? []}
          value={draft.certifications} onChange={(v) => set('certifications', v)} />
        <span className="small muted">EPA 608 is required for jobs likely to involve refrigerant.</span>
      </div>
      <div className="field" style={{ maxWidth: 260 }}>
        <label htmlFor="tech-radius">Service radius (km)</label>
        <input id="tech-radius" className="input" type="number" min={1} max={100} value={draft.service_radius_km}
          onChange={(e) => set('service_radius_km', Number(e.target.value))} />
      </div>
      <fieldset className="field" style={{ border: 0, padding: 0, margin: 0 }}>
        <legend className="label" style={{ marginBottom: 6 }}>Working hours</legend>
        <span className="small muted">Used when your scheduling software doesn't provide shifts.</span>
        <div className="stack" style={{ gap: 6 }}>
          {DAYS.map(([day, name]) => {
            const range = draft.working_hours[day]?.[0];
            return (
              <div key={day} className="row" style={{ gap: 8 }}>
                <label className="row" style={{ width: 80, gap: 6 }}>
                  <input type="checkbox" checked={!!range} onChange={(e) => setDay(day, e.target.checked)} /> {name}
                </label>
                {range ? (
                  <>
                    <input aria-label={`${name} start`} className="input" type="time" style={{ width: 130 }} value={range[0]}
                      onChange={(e) => setDay(day, true, e.target.value, range[1])} />
                    <span className="muted">to</span>
                    <input aria-label={`${name} end`} className="input" type="time" style={{ width: 130 }}
                      value={range[1] === '24:00' ? '23:59' : range[1]}
                      onChange={(e) => setDay(day, true, range[0], e.target.value === '23:59' ? '24:00' : e.target.value)} />
                  </>
                ) : <span className="small muted">Off</span>}
              </div>
            );
          })}
        </div>
      </fieldset>
      <PermissionFields value={draft} onChange={(p) => setDraft((d) => ({ ...d, ...p }))} />
      {hcp ? (
        <div className="field">
          <label htmlFor="tech-hcp">Housecall Pro employee ID</label>
          <input id="tech-hcp" className="input" value={draft.external_id ?? ''} placeholder="Filled in automatically when names match"
            onChange={(e) => set('external_id', e.target.value)} />
          <span className="small muted">Links this technician to the same person in Housecall Pro, so jobs assigned there show up here.</span>
        </div>
      ) : null}
      {tech ? <TimeOffFields tech={tech} /> : null}
      <ErrorAlert message={save.error} />
      <div className="row" style={{ justifyContent: 'flex-end' }}>
        <Button onClick={onDone}>Cancel</Button>
        <Button type="submit" variant="primary" busy={save.busy}>Save technician</Button>
      </div>
    </form>
  );
}

/** Vacation, days off, appointments: no jobs are planned for them in this time. */
function TimeOffFields({ tech }: { tech: Technician }) {
  const list = useLiveData(() => api.timeOff(tech.id));
  const today = new Date().toISOString().slice(0, 10);
  const [from, setFrom] = useState(today);
  const [to, setTo] = useState(today);
  const [label, setLabel] = useState('');
  const add = useAction(async () => {
    // Whole days in your local time: from the start of the first day to the end of the last.
    const start = new Date(`${from}T00:00`);
    const end = new Date(`${to}T23:59`);
    await api.addTimeOff(tech.id, start.toISOString(), end.toISOString(), label || 'Time off');
    setLabel('');
    await list.reload();
  });
  const remove = useAction(async (blockId: string) => {
    await api.removeTimeOff(tech.id, blockId);
    await list.reload();
  });
  const fmt = (iso: string) => new Date(iso).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });
  return (
    <fieldset className="field" style={{ border: 0, padding: 0, margin: 0 }}>
      <legend className="label">Time off</legend>
      {list.data?.length ? (
        <ul className="stack" style={{ listStyle: 'none', padding: 0, margin: '0 0 8px', gap: 6 }}>
          {list.data.map((b) => (
            <li key={b.id} className="row between small" style={{ border: '1px solid var(--line)', borderRadius: 8, padding: '6px 10px' }}>
              <span><strong>{b.label ?? 'Time off'}</strong> · {fmt(b.starts_at)}{fmt(b.starts_at) !== fmt(b.ends_at) ? ` – ${fmt(b.ends_at)}` : ''}</span>
              <Button size="small" busy={remove.busy} onClick={() => void remove.run(b.id)}>Remove</Button>
            </li>
          ))}
        </ul>
      ) : <p className="small muted" style={{ margin: '0 0 8px' }}>None planned.</p>}
      <div className="row" style={{ alignItems: 'flex-end' }}>
        <div className="field"><label htmlFor="off-from">From</label>
          <input id="off-from" className="input" type="date" value={from} min={today} onChange={(e) => { setFrom(e.target.value); if (e.target.value > to) setTo(e.target.value); }} /></div>
        <div className="field"><label htmlFor="off-to">To</label>
          <input id="off-to" className="input" type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} /></div>
        <div className="field spacer"><label htmlFor="off-label">Reason (optional)</label>
          <input id="off-label" className="input" value={label} maxLength={60} placeholder="Vacation" onChange={(e) => setLabel(e.target.value)} /></div>
        <Button busy={add.busy} onClick={() => void add.run()}>Add time off</Button>
      </div>
      <ErrorAlert message={add.error ?? remove.error} />
    </fieldset>
  );
}

/** What the technician may do in the app. Enforced by the server, not just hidden. */
function PermissionFields({ value, onChange }: { value: TechPermissions; onChange: (p: Partial<TechPermissions>) => void }) {
  return (
    <fieldset className="field" style={{ border: 0, padding: 0, margin: 0 }}>
      <legend className="label" style={{ marginBottom: 2 }}>What can this technician do in the app?</legend>
      <label className="perm">
        <input type="checkbox" checked={value.can_respond_offers}
          onChange={(e) => onChange({ can_respond_offers: e.target.checked })} />
        <span><strong>Accept or decline job offers</strong><br />
          <span className="small muted">Off: your office accepts jobs and they appear on the technician's schedule.</span></span>
      </label>
      <label className="perm">
        <input type="checkbox" checked={value.can_contact_customers}
          onChange={(e) => onChange({ can_contact_customers: e.target.checked })} />
        <span><strong>Message and call customers</strong><br />
          <span className="small muted">Customers and the technician see each other's phone number. Off: your office talks to the customer.</span></span>
      </label>
      <div className="perm" role="radiogroup" aria-label="Schedule they can see">
        <span style={{ width: 13 }} />
        <span className="stack" style={{ gap: 4 }}>
          <strong>Schedule they can see</strong>
          <label className="row" style={{ gap: 6 }}>
            <input type="radio" name="schedule_view" checked={value.schedule_view === 'full'}
              onChange={() => onChange({ schedule_view: 'full' })} /> Their full day
          </label>
          <label className="row" style={{ gap: 6 }}>
            <input type="radio" name="schedule_view" checked={value.schedule_view === 'next'}
              onChange={() => onChange({ schedule_view: 'next' })} /> Only their next job
          </label>
        </span>
      </div>
    </fieldset>
  );
}

function permissionSummary(t: Technician): string {
  return [
    t.can_respond_offers ? 'Accepts jobs' : 'Office accepts jobs',
    t.can_contact_customers ? 'contacts customers' : 'no customer contact',
    t.schedule_view === 'full' ? 'full day' : 'next job only',
  ].join(' · ');
}

/** Invite by email: Firebase sends the link (or, in development, it's shown here). */
function InviteDialog({ tech, onClose }: { tech: Technician; onClose: () => void }) {
  const [email, setEmail] = useState(tech.email ?? '');
  const [perms, setPerms] = useState<TechPermissions>({
    can_respond_offers: tech.can_respond_offers,
    can_contact_customers: tech.can_contact_customers,
    schedule_view: tech.schedule_view,
  });
  const [sent, setSent] = useState<EmailLink | null>(null);
  const invite = useAction(async () => {
    const { email_link } = await api.inviteTechnician(tech.id, email, perms);
    setSent(email_link);
  });

  return (
    <div className="dialog-backdrop" role="presentation" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <form className="card dialog stack" role="dialog" aria-modal="true" aria-labelledby="invite-title"
        onSubmit={(e) => { e.preventDefault(); void invite.run(); }}>
        <h2 id="invite-title">Invite {tech.name} to the technician app</h2>
        {sent ? (
          <>
            {sent.delivery === 'development' ? (
              <>
                <p className="row small"><span className="badge amber">TEST MODE</span>
                  Email sending isn't set up (Firebase). Send {tech.name} this link, or open it to test:</p>
                <input className="input" readOnly value={sent.dev_link ?? ''} aria-label="Invite link"
                  onFocus={(e) => e.currentTarget.select()} />
                <a className="btn" href={sent.dev_link ?? '#'} target="_blank" rel="noreferrer">Open invite link</a>
              </>
            ) : (
              <p>We emailed an invite to <strong>{sent.email}</strong>. The link works once and expires in 7 days.</p>
            )}
            <div className="row" style={{ justifyContent: 'flex-end' }}>
              <Button variant="primary" onClick={onClose}>Done</Button>
            </div>
          </>
        ) : (
          <>
            <p className="small muted">They'll open the link on their phone, confirm the email is theirs, and sign in with
              their phone number or Google. You can change these permissions any time.</p>
            <div className="field">
              <label htmlFor="invite-email">Technician's email</label>
              <input id="invite-email" className="input" type="email" required autoFocus value={email}
                onChange={(e) => setEmail(e.target.value)} placeholder="name@example.com" />
            </div>
            <PermissionFields value={perms} onChange={(p) => setPerms((d) => ({ ...d, ...p }))} />
            <ErrorAlert message={invite.error} />
            <div className="row" style={{ justifyContent: 'flex-end' }}>
              <Button onClick={onClose}>Cancel</Button>
              <Button type="submit" variant="primary" icon="mail" busy={invite.busy}>Send invite</Button>
            </div>
          </>
        )}
      </form>
    </div>
  );
}

const DAY_ORDER = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];

/** "Mon–Fri 8:00–17:00", or "No hours" when nothing is set (the tech can't be matched). */
function hoursSummary(hours: WorkingHours | null | undefined): string {
  const days = DAY_ORDER.filter((d) => hours?.[d]?.length);
  const first = days.length ? hours?.[days[0]!]?.[0] : undefined;
  if (!first) return 'No hours set';
  const same = days.every((d) => hours?.[d]?.[0]?.[0] === first[0] && hours?.[d]?.[0]?.[1] === first[1]);
  const span = days.length === 7 ? 'Every day' : `${cap(days[0]!)}–${cap(days[days.length - 1]!)}`;
  return same ? `${span} ${first[0]}–${first[1]}` : `${days.length} days a week`;
}

const cap = (d: string) => d.charAt(0).toUpperCase() + d.slice(1);
