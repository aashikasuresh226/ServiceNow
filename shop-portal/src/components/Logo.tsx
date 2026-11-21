/** The brand mark: an airflow that forms a "C" (white outer stream, teal inner stream). */
export function Logo({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true" style={{ flex: 'none' }}>
      <rect width="64" height="64" rx="16" fill="var(--primary)" />
      <g transform="translate(-1.5 2)" fill="none" strokeWidth="5.5" strokeLinecap="round">
        <path stroke="#fff" d="M44 16.5a3.5 3.5 0 1 1 3.5 3.5A17 17 0 1 0 47.5 44h5" />
        <path stroke="var(--logo-air)" d="M39 27.5a7.5 7.5 0 1 0 0 9" />
      </g>
    </svg>
  );
}
