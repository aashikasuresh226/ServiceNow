/** The shop's customers (imported from Housecall Pro, or joined through the shop's link)
 * and inviting them to the homeowner app from the shop's own phone or email. */
import QRCode from 'qrcode';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { Icon } from '../components/Icon';
import { Button, Empty, ErrorAlert } from '../components/ui';
import { api } from '../lib/api';
import { useAction, useLiveData, usePortal } from '../lib/hooks';
import type { Customer } from '../lib/types';

const FILTERS: [string, string][] = [
  ['', 'All'],
  ['not_invited', 'Not invited'],
  ['invited', 'Invited'],
  ['joined', 'Using the app'],
];

/** +14045550199 -> (404) 555-0199 */
function prettyPhone(e164: string): string {
  const d = e164.replace(/\D/g, '');
  return d.length === 11 && d.startsWith('1') ? `(${d.slice(1, 4)}) ${d.slice(4, 7)}-${d.slice(7)}` : e164;
}

/** Opens the Messages app (phone, Mac, or Phone Link on Windows) with the text filled in. */
function smsHref(phone: string, body: string): string {
  const sep = /iPhone|iPad|Macintosh/.test(navigator.userAgent) ? '&' : '?';
  return `sms:${phone}${sep}body=${encodeURIComponent(body)}`;
}

function mailHref(email: string, shop: string, body: string): string {
  return `mailto:${email}?subject=${encodeURIComponent(`Book your next visit with ${shop}`)}&body=${encodeURIComponent(body)}`;
}

async function copy(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function StatusBadge({ c }: { c: Customer }) {
  if (c.status === 'joined') return <span className="badge success">Using the app</span>;
  if (c.status === 'invited') {
    return <span className="badge" title={c.invited_at ? new Date(c.invited_at).toLocaleString() : undefined}>Invited</span>;
  }
  return <span className="muted small">Not invited</span>;
}

function InviteActions({ c, shopName, onSent }: { c: Customer; shopName: string; onSent: () => void }) {
  const [copied, setCopied] = useState(false);
  const mark = () => { void api.markInvited(c.id).then(onSent).catch(() => undefined); };
  if (c.status === 'joined') return <span className="muted small">—</span>;
  return (
    <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
      {c.phone ? (
        <a className="btn small" href={smsHref(c.phone, c.invite_message)} onClick={mark}
          aria-label={`Text an invite to ${c.name ?? 'this customer'}`}>
          <Icon name="chat" size={14} /> Text
        </a>
      ) : null}
      {c.email ? (
        <a className="btn small" href={mailHref(c.email, shopName, c.invite_message)} onClick={mark}
          aria-label={`Email an invite to ${c.name ?? 'this customer'}`}>
          <Icon name="mail" size={14} /> Email
        </a>
      ) : null}
      <button type="button" className="btn small" onClick={async () => {
        if (await copy(c.invite_message)) { setCopied(true); mark(); setTimeout(() => setCopied(false), 2000); }
      }}>
        {copied ? 'Copied' : 'Copy message'}
      </button>
    </div>
  );
}

export function CustomersPage() {
  const { me } = usePortal();
  const shop = me.shop;
  const connected = shop.scheduling_provider === 'housecall_pro';
  const [q, setQ] = useState('');
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('');
  const list = useLiveData(() => api.customers(query || undefined, status || undefined), 15000);
  const [qr, setQr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const importNow = useAction(async () => {
    await api.importCustomers();
    await list.reload();
  });

  useEffect(() => {
    const t = setTimeout(() => setQuery(q.trim()), 300);
    return () => clearTimeout(t);
  }, [q]);
  const shopUrl = list.data?.shop_invite_url;
  useEffect(() => {
    if (!shopUrl) return;
    QRCode.toDataURL(shopUrl, { margin: 1, width: 360 }).then(setQr).catch(() => setQr(null));
  }, [shopUrl]);

  const data = list.data;
  return (
    <>
      <div className="row between">
        <h1>Customers</h1>
        {connected ? (
          <Button icon="refresh" busy={importNow.busy} onClick={() => importNow.run()}>Import from Housecall Pro</Button>
        ) : null}
      </div>
      <p className="muted">
        Invite the customers you already have to book and track visits in the app. Invites go from your own
        phone or email, so customers see they come from you. When they sign up with the number or email you
        have on file, they're linked to you automatically and their requests come to you first.
      </p>
      <ErrorAlert message={list.error ?? importNow.error} />

      {data ? (
        <div className="grid-stats">
          <div className="card" style={{ gap: 4 }}><span className="muted small">Customers</span><span className="stat-value">{data.total}</span></div>
          <div className="card" style={{ gap: 4 }}><span className="muted small">Invited</span><span className="stat-value">{data.invited}</span></div>
          <div className="card" style={{ gap: 4 }}><span className="muted small">Using the app</span><span className="stat-value">{data.joined}</span></div>
        </div>
      ) : null}

      {data ? (
        <div className="card row" style={{ alignItems: 'flex-start', gap: 20, flexWrap: 'wrap' }}>
          {qr ? <img src={qr} alt="QR code for your invite link" width={140} height={140} style={{ borderRadius: 8 }} /> : null}
          <div className="stack spacer" style={{ gap: 8, minWidth: 260 }}>
            <strong>Your invite link for everyone</strong>
            <span className="muted small">
              Put it on invoices and your website, in Housecall Pro's email or postcard campaigns, or print the QR code
              for technicians to show at the door. Anyone who signs up from it becomes your customer.
            </span>
            <code style={{ wordBreak: 'break-all' }}>{data.shop_invite_url}</code>
            <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
              <Button size="small" onClick={async () => {
                if (await copy(data.shop_invite_message)) { setCopied(true); setTimeout(() => setCopied(false), 2000); }
              }}>{copied ? 'Copied' : 'Copy invite message'}</Button>
              {qr ? <a className="btn small" href={qr} download={`${shop.name} invite QR.png`}>Download QR code</a> : null}
            </div>
          </div>
        </div>
      ) : null}

      <div className="row" style={{ gap: 12, flexWrap: 'wrap' }}>
        <input className="input" style={{ maxWidth: 320 }} placeholder="Search name, phone or email"
          aria-label="Search customers" value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="tabs" role="tablist" aria-label="Filter customers">
          {FILTERS.map(([value, text]) => (
            <button key={value} type="button" role="tab" className="tab" aria-selected={status === value}
              onClick={() => setStatus(value)}>{text}</button>
          ))}
        </div>
      </div>

      {data?.customers.length ? (
        <div className="card table-wrap">
          <table className="table">
            <thead><tr><th>Customer</th><th>Contact</th><th>Last job</th><th>Status</th><th>Invite</th></tr></thead>
            <tbody>
              {data.customers.map((c) => (
                <tr key={c.id}>
                  <td>
                    <strong>{c.name ?? 'Customer'}</strong>
                    {c.address ? <span className="muted small" style={{ display: 'block' }}>{c.address}</span> : null}
                  </td>
                  <td className="small">
                    {c.phone ? <span style={{ display: 'block' }}>{prettyPhone(c.phone)}</span> : null}
                    {c.email ? <span className="muted">{c.email}</span> : null}
                    {!c.phone && !c.email ? <span className="muted">No contact on file</span> : null}
                  </td>
                  <td className="small">{c.last_job_at ? new Date(c.last_job_at).toLocaleDateString() : '—'}</td>
                  <td><StatusBadge c={c} /></td>
                  <td><InviteActions c={c} shopName={shop.name} onSent={() => void list.reload()} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : data ? (
        <div className="card">
          <Empty icon="users">
            {query || status ? 'No customers match.' : connected
              ? 'No customers yet. Import them from Housecall Pro, or share your invite link.'
              : <>Connect Housecall Pro in <Link to="/integrations">How you take jobs</Link> to import your customers, or share your invite link above.</>}
          </Empty>
        </div>
      ) : null}
      {data && data.total > data.customers.length && !query && !status ? (
        <p className="muted small">Showing the first {data.customers.length}. Search to find others.</p>
      ) : null}
    </>
  );
}
