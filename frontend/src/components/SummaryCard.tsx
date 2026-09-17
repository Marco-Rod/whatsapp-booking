import { Icon } from './Icon'

export function SummaryCard({ label, count, kind }: { label: string; count: number; kind: 'total' | 'confirmed' | 'cancelled' }) {
  return <div className={`summary-card ${kind}`}>
    <div className="summary-label">{label}<span className="summary-icon"><Icon name={kind === 'confirmed' ? 'check' : kind === 'total' ? 'calendar' : 'clock'}/></span></div>
    <strong>{count}</strong><span className="summary-caption">{kind === 'total' ? 'en tu agenda' : kind === 'confirmed' ? 'listas para recibir' : 'para tener en cuenta'}</span>
  </div>
}
