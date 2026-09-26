import { useEffect, useState } from 'react'
import {
  connectGoogleCalendar,
  disconnectGoogleCalendar,
  getGoogleCalendarIntegration,
} from '../../api/googleIntegrations'
import { AdminAuthError } from '../../api/adminAuth'
import type { GoogleCalendarIntegration } from '../../types/googleIntegration'

type CalendarState =
  | { kind: 'loading' }
  | { kind: 'error' }
  | { kind: 'ready'; integration: GoogleCalendarIntegration }

interface CalendarStepProps {
  onContinue: () => void
  onUnauthorized: () => void
}

export function CalendarStep({
  onContinue,
  onUnauthorized,
}: CalendarStepProps) {
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState<CalendarState>({ kind: 'loading' })
  const [disconnecting, setDisconnecting] = useState(false)
  const [disconnectError, setDisconnectError] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    setState({ kind: 'loading' })

    getGoogleCalendarIntegration(controller.signal)
      .then((integration) => {
        if (!controller.signal.aborted) {
          setState({ kind: 'ready', integration })
        }
      })
      .catch((error: unknown) => {
        if (error instanceof AdminAuthError && error.status === 401) {
          onUnauthorized()
          return
        }
        if (!controller.signal.aborted) setState({ kind: 'error' })
      })

    return () => controller.abort()
  }, [attempt])

  async function handleDisconnect() {
    setDisconnecting(true)
    setDisconnectError(false)

    try {
      await disconnectGoogleCalendar()
      setAttempt((value) => value + 1)
    } catch (error) {
      if (error instanceof AdminAuthError && error.status === 401) {
        onUnauthorized()
        return
      }
      setDisconnectError(true)
    } finally {
      setDisconnecting(false)
    }
  }

  if (state.kind === 'loading') {
    return (
      <p className="calendar-step__loading" role="status">
        Consultando Google Calendar…
      </p>
    )
  }

  if (state.kind === 'error') {
    return (
      <div className="calendar-step__error" role="alert">
        <p>No pudimos consultar el estado de Google Calendar.</p>
        <button type="button" onClick={() => setAttempt((value) => value + 1)}>
          Reintentar
        </button>
      </div>
    )
  }

  if (!state.integration.connected) {
    return (
      <section className="calendar-step">
        <h2>Google Calendar</h2>
        <p className="calendar-step__status">Sin conexión</p>
        <p>Las citas funcionarán igualmente sin Calendar.</p>
        <div className="calendar-step__actions">
          <button
            className="calendar-step__button calendar-step__button--primary"
            type="button"
            onClick={() => connectGoogleCalendar('onboarding')}
          >
            Conectar Google Calendar
          </button>
          <button
            className="calendar-step__button calendar-step__button--secondary"
            type="button"
            onClick={onContinue}
          >
            Omitir por ahora
          </button>
        </div>
      </section>
    )
  }

  return (
    <section className="calendar-step">
      <h2>Google Calendar</h2>
      <p className="calendar-step__status">Conectado ✓</p>
      <p>Las nuevas reservas se sincronizarán con tu calendario.</p>
      {disconnectError && (
        <p role="alert">
          No pudimos desconectar Google Calendar. Inténtalo de nuevo.
        </p>
      )}
      <div className="calendar-step__actions">
        <button
          className="calendar-step__button calendar-step__button--secondary"
          type="button"
          onClick={() => void handleDisconnect()}
          disabled={disconnecting}
        >
          {disconnecting ? 'Desconectando…' : 'Desconectar'}
        </button>
        <button
          className="calendar-step__button calendar-step__button--primary"
          type="button"
          onClick={onContinue}
          disabled={disconnecting}
        >
          Continuar
        </button>
      </div>
    </section>
  )
}
