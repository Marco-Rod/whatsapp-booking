import { useEffect, useState } from 'react'
import { getDashboard } from '../api/dashboard'
import { AppointmentCard } from '../components/AppointmentCard'
import { GoogleCalendarIntegrationCard } from '../components/GoogleCalendarIntegrationCard'
import { Icon } from '../components/Icon'
import { SummaryCard } from '../components/SummaryCard'
import type { DashboardResponse } from '../types/dashboard'

const businessId = Number(import.meta.env.VITE_BUSINESS_ID || 1)
const businessName = import.meta.env.VITE_BUSINESS_NAME || 'Bella Studio'
const initialTimezone = import.meta.env.VITE_BUSINESS_TIMEZONE || 'America/Mexico_City'
const todayIn = (timezone: string) => new Intl.DateTimeFormat('en-CA', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
const readableDate = (date: string) => new Intl.DateTimeFormat('es-MX', { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'UTC' }).format(new Date(`${date}T12:00:00Z`))
const shiftDay = (date: string, days: number) => { const value = new Date(`${date}T12:00:00Z`); value.setUTCDate(value.getUTCDate() + days); return value.toISOString().slice(0, 10) }
type State = { kind: 'loading' } | { kind: 'error'; message: string } | { kind: 'success'; data: DashboardResponse }
type GoogleCalendarNotice = 'connected' | 'error' | null

function consumeGoogleCalendarNotice(): GoogleCalendarNotice {
  const url = new URL(window.location.href)
  const result = url.searchParams.get('google_calendar')

  if (result !== 'connected' && result !== 'error') return null

  url.searchParams.delete('google_calendar')
  window.history.replaceState(window.history.state, '', url)
  return result
}

export function DashboardPage() {
  const [date, setDate] = useState(() => todayIn(initialTimezone))
  const [timezone, setTimezone] = useState(initialTimezone)
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [googleCalendarNotice, setGoogleCalendarNotice] = useState<GoogleCalendarNotice>(consumeGoogleCalendarNotice)
  useEffect(() => {
    const controller = new AbortController()
    setState({ kind: 'loading' })
    getDashboard(businessId, date, controller.signal).then(data => {
      if (!controller.signal.aborted) { setTimezone(data.timezone); setState({ kind: 'success', data }) }
    }).catch(error => {
      if (!controller.signal.aborted) setState({ kind: 'error', message: error instanceof TypeError ? 'No pudimos conectar con tu agenda. Revisa tu conexión e intenta de nuevo.' : error.message })
    })
    return () => controller.abort()
  }, [date, attempt])

  return <>
    <header className="topbar"><div className="topbar-inner"><a className="brand" href="/" aria-label="WhatsApp Booking, inicio"><span className="brand-mark">w<span>·</span></span><span>WhatsApp <b>Booking</b></span></a><div className="business"><span className="business-avatar">BS</span><span>{businessName}<small>Agenda del negocio</small></span></div></div></header>
    <main>
      <section className="page-heading"><div><div className="eyebrow"><span/> TU NEGOCIO, AL DÍA</div><h1>Citas del día<span>.</span></h1><p>Una mirada a tu agenda. Todo en su lugar.</p></div><div className="date-control"><div className="date-nav"><button onClick={() => setDate(shiftDay(date, -1))} aria-label="Día anterior"><Icon name="arrow-left"/></button><label className="date-field"><Icon name="calendar"/><input aria-label="Fecha de la agenda" type="date" value={date} min="1900-01-01" max="9998-12-31" onChange={event => { if (event.target.validity.valid && event.target.value) setDate(event.target.value) }}/></label><button onClick={() => setDate(shiftDay(date, 1))} aria-label="Día siguiente"><Icon name="arrow-right"/></button></div><span className="date-caption">{readableDate(date)}</span></div></section>

      {googleCalendarNotice && <div className={`oauth-notice ${googleCalendarNotice}`} role={googleCalendarNotice === 'error' ? 'alert' : 'status'}><Icon name={googleCalendarNotice === 'connected' ? 'check' : 'alert'} size={20}/><span>{googleCalendarNotice === 'connected' ? 'Google Calendar se conectó correctamente.' : 'No pudimos conectar Google Calendar. Inténtalo nuevamente.'}</span><button aria-label="Cerrar mensaje" onClick={() => setGoogleCalendarNotice(null)}>×</button></div>}

      {state.kind === 'loading' && <section aria-label="Cargando agenda" aria-busy="true" role="status"><span className="sr-only">Cargando agenda</span><div className="summary-grid">{[1, 2, 3].map(i => <div className="summary-card skeleton" key={i}><div/><div/><div/></div>)}</div><div className="agenda-panel skeleton-agenda">{[1, 2, 3].map(i => <div className="skeleton-line" key={i}/>)}</div></section>}
      {state.kind === 'error' && <section className="state-panel error-panel" role="alert"><span className="state-icon"><Icon name="alert" size={28}/></span><h2>No pudimos cargar tu agenda</h2><p>{state.message}</p><button className="retry" onClick={() => setAttempt(value => value + 1)}>Reintentar</button></section>}
      {state.kind === 'success' && <>
        <section className="summary-grid" aria-label="Resumen de citas"><SummaryCard label="Total de citas" count={state.data.summary.total} kind="total"/><SummaryCard label="Confirmadas" count={state.data.summary.confirmed} kind="confirmed"/><SummaryCard label="Canceladas" count={state.data.summary.cancelled} kind="cancelled"/></section>
        <section className="agenda-panel" aria-labelledby="agenda-title"><div className="agenda-heading"><div><h2 id="agenda-title">Tu agenda <span>{state.data.summary.total}</span></h2><p>{date === todayIn(timezone) ? 'Así se ve tu día de hoy.' : readableDate(date)}</p></div><span className="read-only"><Icon name="calendar" size={15}/> Vista del día</span></div>
          {state.data.appointments.length === 0 ? <div className="state-panel empty-panel"><span className="state-icon"><Icon name="calendar" size={30}/></span><h3>No tienes citas para este día</h3><p>Cuando haya una reserva, la verás aquí.<br/>También puedes consultar otra fecha.</p></div> : <><div className="agenda-columns" aria-hidden="true"><span>HORARIO</span><span>SERVICIO</span><span>CLIENTE</span><span>ESTADO</span></div><ul className="appointment-list">{state.data.appointments.map(a => <AppointmentCard key={a.id} appointment={a} timezone={state.data.timezone}/>)}</ul></>}
        </section>
      </>}
      <GoogleCalendarIntegrationCard businessId={businessId}/>
      <footer className="page-footer"><span><Icon name="clock" size={14}/> Hora local del negocio · {timezone.replaceAll('_', ' ')}</span><span>Menos pendientes. Más tiempo para tus clientes.</span></footer>
    </main><div className="bottom-brand">Hecho para el ritmo de tu negocio <span>✧</span></div>
  </>
}
