import { useState } from 'react'
import {
  AdminAuthError,
  completeOnboarding,
} from '../../api/adminAuth'
import type { OnboardingStatus } from '../../types/onboarding'

interface CompleteStepProps {
  status: OnboardingStatus
  onCompleted: (status: OnboardingStatus) => void
  onUnauthorized: () => void
}

export function CompleteStep({
  status,
  onCompleted,
  onUnauthorized,
}: CompleteStepProps) {
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleComplete() {
    if (submitting) return

    setSubmitting(true)
    setError(null)

    try {
      onCompleted(await completeOnboarding())
    } catch (requestError) {
      if (
        requestError instanceof AdminAuthError &&
        requestError.status === 401
      ) {
        onUnauthorized()
        return
      }

      if (
        requestError instanceof AdminAuthError &&
        requestError.status === 409
      ) {
        setError(
          'Alguna configuración obligatoria ya no está completa. Revísala antes de finalizar.',
        )
        return
      }

      setError('No pudimos finalizar la configuración. Inténtalo de nuevo.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className="complete-step">
      <h2>¡Todo listo!</h2>
      <p className="complete-step__intro">
        Tu asistente ya tiene la información necesaria para comenzar a
        gestionar reservas.
      </p>

      <ul className="complete-step__checklist">
        <li className={status.steps.business ? '' : 'complete-step__item--pending'}>
          <span aria-hidden="true">{status.steps.business ? '✓' : '○'}</span>
          Negocio configurado
        </li>
        <li className={status.steps.services ? '' : 'complete-step__item--pending'}>
          <span aria-hidden="true">{status.steps.services ? '✓' : '○'}</span>
          Servicios configurados
        </li>
        <li className={status.steps.hours ? '' : 'complete-step__item--pending'}>
          <span aria-hidden="true">{status.steps.hours ? '✓' : '○'}</span>
          Horarios configurados
        </li>
        <li className={status.steps.calendar ? '' : 'complete-step__item--pending'}>
          <span aria-hidden="true">{status.steps.calendar ? '✓' : '○'}</span>
          {status.steps.calendar
            ? 'Google Calendar conectado'
            : 'Google Calendar omitido'}
        </li>
      </ul>

      {error && <p className="complete-step__error" role="alert">{error}</p>}

      <div className="complete-step__actions">
        <button
          className="complete-step__button"
          type="button"
          onClick={() => void handleComplete()}
          disabled={submitting}
        >
          {submitting ? 'Finalizando…' : 'Finalizar configuración'}
        </button>
      </div>
    </section>
  )
}
