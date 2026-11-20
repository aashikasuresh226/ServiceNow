/**
 * The one link to share: asks who you are and sends you to the right place.
 *   Homeowner   -> the homeowner app (sign in / create account)
 *   Shop owner  -> create a shop account (or sign in) here
 *   Technician  -> no sign-up: their shop invites them by email
 */
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { Icon } from '../components/Icon';
import { useOptions } from '../lib/hooks';

export function StartPage() {
  const options = useOptions();
  const [techOpen, setTechOpen] = useState(false);
  const appUrl = options?.features.app_url;
  const techSignIn = options?.features.technician_sign_in_url;

  return (
    <div className="auth-page">
      <main className="start-card">
        <div className="start-head">
          <h1 style={{ fontSize: 26, margin: 0 }}>Welcome to HVAC Connect</h1>
          <p className="muted" style={{ margin: 0 }}>Who are you?</p>
        </div>

        <a className="role-option" href={appUrl ? `${appUrl}/welcome` : undefined}
          aria-disabled={!appUrl}>
          <span className="role-icon"><Icon name="home" size={22} /></span>
          <span className="role-text">
            <strong>Homeowner</strong>
            <span className="small muted">Book a repair, track your technician, message them</span>
          </span>
          <Icon name="arrow" size={18} />
        </a>

        <Link className="role-option" to="/login?mode=signup">
          <span className="role-icon"><Icon name="building" size={22} /></span>
          <span className="role-text">
            <strong>Shop owner</strong>
            <span className="small muted">Create your shop's account, or sign in</span>
          </span>
          <Icon name="arrow" size={18} />
        </Link>

        <button type="button" className="role-option" aria-expanded={techOpen} aria-controls="tech-help"
          onClick={() => setTechOpen(!techOpen)}>
          <span className="role-icon"><Icon name="wrench" size={22} /></span>
          <span className="role-text">
            <strong>Technician</strong>
            <span className="small muted">Your shop invites you</span>
          </span>
          <Icon name="arrow" size={18} />
        </button>
        {techOpen ? (
          <div className="role-help" id="tech-help">
            <strong>Technicians join by invite</strong>
            <ol className="small">
              <li>Ask your shop owner or office to invite you from their HVAC Connect portal (Technicians → Invite to app).</li>
              <li>
                The invite arrives by email from HVAC Connect. If it isn't in your inbox, check your <b>Spam</b> or{' '}
                <b>Junk</b> folder (and Promotions in Gmail).
              </li>
              <li>Open the link on your phone to set up your account. The invite works for 7 days.</li>
            </ol>
            {techSignIn ? (
              <p className="small" style={{ margin: 0 }}>
                Already set up? <a href={techSignIn}>Technician sign-in</a>
              </p>
            ) : null}
          </div>
        ) : null}
      </main>
    </div>
  );
}
