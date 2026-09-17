export function Icon({ name, size = 18 }: { name: 'calendar' | 'check' | 'clock' | 'arrow-left' | 'arrow-right' | 'alert'; size?: number }) {
  const paths = {
    calendar: <><rect x="4" y="5" width="16" height="16" rx="3"/><path d="M8 3v4m8-4v4M4 11h16m-11 4h2m2 0h2"/></>,
    check: <path d="m5 12 4 4 10-10"/>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
    'arrow-left': <path d="m14 6-6 6 6 6"/>,
    'arrow-right': <path d="m10 6 6 6-6 6"/>,
    alert: <><circle cx="12" cy="12" r="9"/><path d="M12 7v6m0 3v1"/></>,
  }
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>
}
