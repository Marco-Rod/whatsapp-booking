import type { DashboardAppointment } from '../types/dashboard'
import { Icon } from './Icon'

export function AppointmentCard({ appointment: a, timezone }: { appointment: DashboardAppointment; timezone: string }) {
  const format = (value: string) => new Intl.DateTimeFormat('es-MX', { timeZone: timezone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(value))
  const cancelled = a.status === 'CANCELLED'
  return <li className={`appointment ${cancelled ? 'is-cancelled' : ''}`} data-testid="appointment">
    <div className="appointment-time"><strong><time dateTime={a.starts_at}>{format(a.starts_at)}</time></strong><span>— {format(a.ends_at)}</span></div>
    <div className="appointment-service"><span className="mobile-label">Servicio</span><strong>{a.service.name}</strong><span className="appointment-id">Cita #{a.id}</span></div>
    <div className="appointment-customer"><span className="avatar" aria-hidden="true">{(a.customer?.name || 'Cliente').slice(0, 1).toUpperCase()}</span><span>{a.customer?.name || 'Sin nombre'}</span></div>
    <div className="appointment-status"><span className={`badge ${cancelled ? 'cancelled' : 'confirmed'}`}><span className="status-dot"/>{cancelled ? 'Cancelada' : 'Confirmada'}</span></div>
    <div className="appointment-integrations">
      <span className={a.calendar_synced ? 'integration active' : 'integration'} title="Indica si la cita tiene un evento asociado; no verifica si sigue activo en Calendar."><Icon name="calendar" size={15}/>{a.calendar_synced ? 'Calendar vinculado' : 'Sin vincular a Calendar'}</span>
      <span className={a.reminder_sent ? 'integration reminder-sent' : 'integration reminder-pending'}><Icon name={a.reminder_sent ? 'check' : 'clock'} size={15}/>{a.reminder_sent ? 'Recordatorio enviado' : 'Recordatorio pendiente'}</span>
    </div>
  </li>
}
