import type { ButtonHTMLAttributes, ReactNode } from 'react';

import { Icon } from './Icon';

export function Button({ variant = 'default', size, busy, icon, children, ...props }:
  ButtonHTMLAttributes<HTMLButtonElement> & {
    variant?: 'default' | 'primary' | 'danger';
    size?: 'small';
    busy?: boolean;
    icon?: string;
  }) {
  const cls = ['btn', variant !== 'default' ? variant : '', size ?? ''].filter(Boolean).join(' ');
  return (
    <button type="button" {...props} className={cls} disabled={props.disabled || busy}
      aria-busy={busy || undefined}>
      {icon ? <Icon name={icon} size={16} /> : null}
      {busy ? 'Working…' : children}
    </button>
  );
}

export function ErrorAlert({ message }: { message: string | null | undefined }) {
  if (!message) return null;
  return (
    <div className="alert" role="alert">
      <Icon name="alert" size={18} />
      <span>{message}</span>
    </div>
  );
}

export function Switch({ checked, onChange, label, disabled }: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label} className="switch"
      disabled={disabled} onClick={() => onChange(!checked)} />
  );
}

export function ChipGroup({ options, value, onChange, tone, label }: {
  options: { value: string; label: string }[];
  value: string[];
  onChange: (value: string[]) => void;
  tone?: 'blue';
  label: string;
}) {
  return (
    <div className="row" role="group" aria-label={label} style={{ gap: 6 }}>
      {options.map((o) => {
        const on = value.includes(o.value);
        return (
          <button key={o.value} type="button" className={`chip ${tone ?? ''}`} aria-pressed={on}
            onClick={() => onChange(on ? value.filter((v) => v !== o.value) : [...value, o.value])}>
            {on ? <Icon name="check" size={13} /> : null}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export function Stat({ icon, value, label, tone }: {
  icon: string;
  value: ReactNode;
  label: string;
  tone: 'primary' | 'amber' | 'neutral';
}) {
  const colors = {
    primary: ['var(--primary-soft)', 'var(--primary)'],
    amber: ['var(--amber-soft)', 'var(--amber-ink)'],
    neutral: ['#eef0f3', 'var(--ink)'],
  }[tone];
  return (
    <div className="card stat">
      <span className="stat-icon" style={{ background: colors[0], color: colors[1] }}>
        <Icon name={icon} size={20} />
      </span>
      <div>
        <div className="stat-value">{value}</div>
        <div className="muted small">{label}</div>
      </div>
    </div>
  );
}

export function Empty({ icon, children }: { icon: string; children: ReactNode }) {
  return (
    <div className="empty">
      <Icon name={icon} size={28} color="var(--faint)" />
      <div>{children}</div>
    </div>
  );
}
