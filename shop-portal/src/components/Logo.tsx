/** The brand mark: airflow lines in sand on a deep petrol square. */
export function Logo({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true" style={{ flex: 'none' }}>
      <rect width="64" height="64" rx="16" fill="var(--primary-dark)" />
      <g transform="translate(0 2.5)" fill="none" stroke="var(--sand)" strokeWidth="5" strokeLinecap="round">
        <path d="M14 25h22a6.5 6.5 0 1 0-6.5-6.5" />
        <path d="M14 34h30a6.5 6.5 0 1 1-6.5 6.5" />
        <path d="M14 43h12" />
      </g>
    </svg>
  );
}
