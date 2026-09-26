import { useEffect, useState } from 'react'
import {
  connectGoogleCalendar,
  disconnectGoogleCalendar,
  getGoogleCalendarIntegration,
} from '../api/googleIntegrations'
import type { GoogleCalendarIntegration } from '../types/googleIntegration'
import { Icon } from './Icon'

type IntegrationState =
  | { kind: 'loading' }
  | { kind: 'error' }
  | { kind: 'ready'; integration: GoogleCalendarIntegration }

export function GoogleCalendarIntegrationCard() {
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState<IntegrationState>({ kind: 'loading' })
  const [confirmingDisconnect, setConfirmingDisconnect] = useState(false)
  const [disconnecting, setDisconnecting] = useState(false)
  const [disconnectError, setDisconnectError] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    setState({ kind: 'loading' })

    getGoogleCalendarIntegration(controller.signal)
      .then(integration => {
        if (!controller.signal.aborted) {
          setState({ kind: 'ready', integration })
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setState({ kind: 'error' })
      })

    return () => controller.abort()
  }, [attempt])

  async function handleDisconnect() {
    setDisconnecting(true)
    setDisconnectError(false)

    try {
      await disconnectGoogleCalendar()
      setState({
        kind: 'ready',
        integration: {
          connected: false,
          calendar_id: null,
          connected_at: null,
        },
      })
      setConfirmingDisconnect(false)
    } catch {
      setDisconnectError(true)
    } finally {
      setDisconnecting(false)
    }
  }

  const connected = state.kind === 'ready' && state.integration.connected

  return (
    <section className="integrations-section" aria-labelledby="integrations-title">
      <div className="section-heading">
        <div className="eyebrow"><span /> CONECTA TUS HERRAMIENTAS</div>
        <h2 id="integrations-title">Integraciones</h2>
        <p>Automatiza tareas para dedicar más tiempo a tus clientes.</p>
      </div>

      <article className="integration-card">
        <div className="integration-card-icon"><Icon name="calendar" size={24} /></div>
        <div className="integration-card-content">
          <h3>Google Calendar</h3>

          {state.kind === 'loading' && (
            <div className="integration-loading" role="status" aria-busy="true">
              <span className="sr-only">Consultando Google Calendar</span>
              <span /><span />
            </div>
          )}

          {state.kind === 'error' && (
            <div className="integration-error" role="alert">
              <p>No pudimos consultar el estado de Google Calendar.</p>
              <button className="text-button" onClick={() => setAttempt(value => value + 1)}>
                Reintentar
              </button>
            </div>
          )}

          {state.kind === 'ready' && !state.integration.connected && (
            <>
              <p>Conecta tu calendario para agregar automáticamente las nuevas citas que recibas por WhatsApp.</p>
              <span className="connection-status disconnected"><span /> No conectado</span>
              <button className="integration-primary-action" onClick={() => connectGoogleCalendar()}>
                Conectar Google Calendar
              </button>
            </>
          )}

          {connected && state.kind === 'ready' && (
            <>
              <span className="connection-status connected"><span /> Conectado</span>
              {state.integration.calendar_id && (
                <p className="calendar-name">
                  {state.integration.calendar_id === 'primary' ? 'Calendario principal' : 'Calendario conectado'}
                </p>
              )}
              <p>Las nuevas reservas se agregarán automáticamente a tu calendario.</p>
              {disconnectError && (
                <p className="disconnect-error" role="alert">
                  No pudimos desconectar Google Calendar. La integración sigue activa.
                </p>
              )}
              <button className="integration-secondary-action" onClick={() => {
                setDisconnectError(false)
                setConfirmingDisconnect(true)
              }}>
                Desconectar
              </button>
            </>
          )}
        </div>
      </article>

      {confirmingDisconnect && connected && (
        <div className="dialog-backdrop">
          <div className="confirmation-dialog" role="dialog" aria-modal="true" aria-labelledby="disconnect-title" aria-describedby="disconnect-description">
            <div className="confirmation-icon"><Icon name="alert" size={24} /></div>
            <h3 id="disconnect-title">¿Desconectar Google Calendar?</h3>
            <p id="disconnect-description">
              Las citas que ya existen en Google Calendar no se eliminarán. Las nuevas reservas dejarán de agregarse automáticamente.
            </p>
            {disconnectError && <p className="disconnect-error" role="alert">No pudimos desconectar Google Calendar. Intenta de nuevo.</p>}
            <div className="confirmation-actions">
              <button className="dialog-cancel" disabled={disconnecting} onClick={() => setConfirmingDisconnect(false)}>Cancelar</button>
              <button className="dialog-confirm" disabled={disconnecting} onClick={handleDisconnect}>
                {disconnecting ? 'Desconectando…' : 'Desconectar'}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
