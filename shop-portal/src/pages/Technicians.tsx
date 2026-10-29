import { useState } from 'react';

import { Avatar } from '../components/Icon';
import { Button, ChipGroup, Empty, ErrorAlert, Switch } from '../components/ui';
import { api } from '../lib/api';
import { label, useAction, useLiveData, usePortal } from '../lib/hooks';
import type { Technician, WorkingHours } from '../lib/types';

const DAYS = [['mon', 'Mon'], ['tue', 'Tue'], ['wed', 'Wed'], ['thu', 'Thu'], ['fri', 'Fri'], ['sat', 'Sat'], ['sun', 'Sun']] as const;
const DEFAULT_HOURS: WorkingHours = Object.fromEntries(
  DAYS.slice(0, 5).map(([d]) => [d, [['08:00', '17:00']]]),
);

type Draft = Pick<Technician, 'name' | 'phone' | 'equipment_types' | 'certifications' | 'soft_skills' |
  'service_radius_km' | 'working_hours' | 'is_active'>;

const emptyDraft = (): Draft => ({
  name: '', phone: '', equipment_types: [], certifications: [], soft_skills: [],
  service_radius_km: 25, working_hours: DEFAULT_HOURS, is_active: true,
});

export function TechniciansPage() {
  const { options, me } = usePortal();
  const techs = useLiveData(() => api.technicians());
  const [editing, setEditing] = useState<Technician | 'new' | null>(null);
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
      <ErrorAlert message={techs.error ?? importNow.error ?? toggle.error} />
      {editing ? (
        <TechnicianForm tech={editing === 'new' ? null : editing}
          onDone={() => { setEditing(null); void techs.reload(); }} />
      ) : null}
      <div className="card table-wrap">
        {techs.data?.length ? (
          <table className="table">
            <thead><tr><th>Name</th><th>Qualified for</th><th>Certifications</th><th>Soft skills</th><th>Active</th><th /></tr></thead>
            <tbody>
              {techs.data.map((t) => (
                <tr key={t.id}>
                  <td><span className="row" style={{ flexWrap: 'nowrap' }}><Avatar name={t.name} size={30} /><span style={{ whiteSpace: 'nowrap' }}><strong>{t.name}</strong>
                    {t.rating ? <span className="small muted"> · ★ {t.rating.toFixed(1)}</span> : null}</span></span></td>
                  <td className="small">{t.equipment_types.map((e) => label(options, 'equipment_types', e)).join(', ') || '—'}</td>
                  <td className="small">{t.certifications.map((c) => label(options, 'certifications', c)).join(', ') || '—'}</td>
                  <td className="small">{t.soft_skills.map((s) => label(options, 'soft_skills', s)).join(', ') || '—'}</td>
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
  const { options } = usePortal();
  const [draft, setDraft] = useState<Draft>(() => (tech ? { ...tech, phone: tech.phone ?? '' } : emptyDraft()));
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft((d) => ({ ...d, [key]: value }));
  const save = useAction(async () => {
    if (tech) await api.updateTechnician(tech.id, draft);
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
          <input id="tech-phone" className="input" value={draft.phone ?? ''} onChange={(e) => set('phone', e.target.value)} />
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
      <div className="field">
        <span className="label">Soft skills</span>
        <ChipGroup label="Soft skills" tone="blue" options={options?.soft_skills ?? []}
          value={draft.soft_skills} onChange={(v) => set('soft_skills', v)} />
        <span className="small muted">Homeowner reviews confirm these over time.</span>
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
      <ErrorAlert message={save.error} />
      <div className="row" style={{ justifyContent: 'flex-end' }}>
        <Button onClick={onDone}>Cancel</Button>
        <Button type="submit" variant="primary" busy={save.busy}>Save technician</Button>
      </div>
    </form>
  );
}
