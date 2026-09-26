import { useState } from 'react'
import {
  updateOnboardingHours,
  type OnboardingBusinessHourConfiguration,
} from '../../api/adminAuth'
import type { OnboardingStatus } from '../../types/onboarding'

const DAY_LABELS = [
  'Lunes',
  'Martes',
  'Miércoles',
  'Jueves',
  'Viernes',
  'Sábado',
  'Domingo',
]

interface HoursStepProps {
  initialHours: OnboardingBusinessHourConfiguration[]
  onSaved: (status: OnboardingStatus) => void
}

export function HoursStep({ initialHours, onSaved }: HoursStepProps) {
  const [hours, setHours] = useState(initialHours)
  const [error, setError] = useState<string | null>(null)
  const [isSaving, setIsSaving] = useState(false)

  function updateHour(
    dayOfWeek: number,
    update: Partial<OnboardingBusinessHourConfiguration>,
  ) {
    setHours((currentHours) =>
      currentHours.map((hour) =>
        hour.day_of_week === dayOfWeek ? { ...hour, ...update } : hour,
      ),
    )
  }

  function toggleDay(hour: OnboardingBusinessHourConfiguration) {
    const isOpen = !hour.is_open
    updateHour(hour.day_of_week, {
      is_open: isOpen,
      open_time: isOpen ? hour.open_time ?? '09:00' : null,
      close_time: isOpen ? hour.close_time ?? '18:00' : null,
    })
  }

  function validateHours(): OnboardingBusinessHourConfiguration[] | null {
    const days = new Set(hours.map((hour) => hour.day_of_week))
    if (
      hours.length !== 7 ||
      days.size !== 7 ||
      [...days].some((day) => day < 0 || day > 6)
    ) {
      setError('La configuración debe incluir los siete días de la semana.')
      return null
    }

    const normalizedHours = hours.map((hour) => {
      if (!hour.is_open) {
        return { ...hour, open_time: null, close_time: null }
      }

      return hour
    })
    const invalidOpenDay = normalizedHours.find(
      (hour) =>
        hour.is_open &&
        (!hour.open_time || !hour.close_time || hour.open_time >= hour.close_time),
    )
    if (invalidOpenDay) {
      setError('Los días abiertos necesitan un horario válido de inicio y fin.')
      return null
    }

    return normalizedHours
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()

    const validHours = validateHours()
    if (validHours === null) return

    setError(null)
    setIsSaving(true)

    try {
      const status = await updateOnboardingHours({ hours: validHours })
      onSaved(status)
    } catch {
      setError('No pudimos guardar los horarios. Inténtalo de nuevo.')
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <form
      className="hours-step"
      onSubmit={(event) => void handleSubmit(event)}
    >
      <div className="hours-step__heading">
        <h2>Horarios</h2>
        <p>Indica cuándo pueden reservar tus clientes.</p>
      </div>

      {hours.map((hour) => (
        <fieldset
          className={`hours-step__day${
            hour.is_open ? '' : ' hours-step__day--closed'
          }`}
          key={hour.day_of_week}
          disabled={isSaving}
        >
          <legend className="hours-step__day-name">
            {DAY_LABELS[hour.day_of_week]}
          </legend>
          <label className="hours-step__switch">
            <input
              type="checkbox"
              checked={hour.is_open}
              onChange={() => toggleDay(hour)}
            />
            <span className="hours-step__switch-control" aria-hidden="true" />
            <span>{hour.is_open ? 'Abierto' : 'Cerrado'}</span>
          </label>
          <div className="hours-step__times">
            <input
              type="time"
              value={hour.open_time ?? ''}
              onChange={(event) =>
                updateHour(hour.day_of_week, { open_time: event.target.value })
              }
              disabled={!hour.is_open}
              aria-label={`Hora de apertura del ${DAY_LABELS[hour.day_of_week]}`}
            />
            <span aria-hidden="true">—</span>
            <input
              type="time"
              value={hour.close_time ?? ''}
              onChange={(event) =>
                updateHour(hour.day_of_week, { close_time: event.target.value })
              }
              disabled={!hour.is_open}
              aria-label={`Hora de cierre del ${DAY_LABELS[hour.day_of_week]}`}
            />
          </div>
          {!hour.is_open && (
            <p className="hours-step__unavailable">Horario no disponible</p>
          )}
        </fieldset>
      ))}

      {error && (
        <p className="hours-step__error" role="alert">
          {error}
        </p>
      )}

      <div className="hours-step__actions">
        <button type="submit" disabled={isSaving}>
          {isSaving ? 'Guardando…' : 'Guardar y continuar'}
        </button>
      </div>
    </form>
  )
}
