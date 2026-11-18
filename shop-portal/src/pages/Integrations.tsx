/**
 * ServiceTitan / Housecall Pro: optional, and not connectable yet (waiting on API
 * access from both vendors). Shops run fully on technicians' working hours plus the
 * jobs booked here, which go on each tech's calendar automatically.
 */
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { Icon } from '../components/Icon';
import { Button } from '../components/ui';

const PROVIDERS = [
  {
    key: 'servicetitan',
    name: 'ServiceTitan',
    blurb: 'Sync technicians, shifts, booked jobs and time off from ServiceTitan Dispatch.',
  },
  {
    key: 'housecall_pro',
    name: 'Housecall Pro',
    blurb: 'Sync employees and scheduled jobs from Housecall Pro (MAX plan API).',
  },
] as const;

export function IntegrationsPage() {
  const [clicked, setClicked] = useState<string | null>(null);
  return (
    <>
      <div className="row">
        <h1>Scheduling software</h1>
        <span className="badge neutral">Optional</span>
      </div>
      <section className="card soft">
        <h2>You don't need to connect anything to receive jobs</h2>
        <p>
          We decide who's free from each technician's <Link to="/technicians">working hours</Link>,
          the jobs booked in this app, and anything you mark on
          the <Link to="/availability">Availability</Link> board. Every booked job is added to the
          technician's calendar automatically, and each tech can subscribe to their calendar from
          Google Calendar, Apple Calendar or Outlook.
        </p>
      </section>
      <div className="grid-2">
        {PROVIDERS.map((p) => (
          <section key={p.key} className="card">
            <div className="row between">
              <h2>{p.name}</h2>
              <span className="badge amber">Coming soon</span>
            </div>
            <p className="small muted">{p.blurb}</p>
            <div>
              <Button onClick={() => setClicked(p.key)} aria-describedby={`${p.key}-note`}>
                <Icon name="plug" size={16} /> Connect {p.name} (optional)
              </Button>
            </div>
            {clicked === p.key ? (
              <p id={`${p.key}-note`} className="notice small" role="status">
                {p.name} connections aren't available yet: we're waiting on API access. Nothing was
                connected or shared. Your working hours keep everything running in the meantime.
              </p>
            ) : null}
          </section>
        ))}
      </div>
    </>
  );
}
