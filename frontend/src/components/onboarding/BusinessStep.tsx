import { useState } from 'react'
import { updateOnboardingBusiness } from '../../api/adminAuth'
import type { OnboardingStatus } from '../../types/onboarding'

const TIMEZONE_OPTIONS = [
  {
    value: 'America/Mexico_City',
    label: 'Centro de México (Guadalajara, Ciudad de México)',
  },
  { value: 'America/Cancun', label: 'Quintana Roo (Cancún)' },
  { value: 'America/Chihuahua', label: 'Chihuahua' },
  { value: 'America/Hermosillo', label: 'Sonora (Hermosillo)' },
  { value: 'America/Tijuana', label: 'Baja California (Tijuana)' },
]

interface BusinessStepProps {
  initialName?: string
  initialTimezone?: string
  onSaved: (status: OnboardingStatus) => void
}

export function BusinessStep({
  initialName = '',
  initialTimezone = '',
  onSaved,
}: BusinessStepProps) {
  const [name, setName] = useState(initialName)
  const [timezone, setTimezone] = useState(initialTimezone)
  const [error, setError] = useState<string | null>(null)
  const [isSaving, setIsSaving] = useState(false)

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()

    const trimmedName = name.trim()
    if (!trimmedName) {
      setError('Ingresa el nombre de tu negocio.')
      return
    }
    if (!timezone) {
      setError('Selecciona una zona horaria.')
      return
    }

    setError(null)
    setIsSaving(true)

    try {
      const status = await updateOnboardingBusiness({
        name: trimmedName,
        timezone,
      })
      onSaved(status)
    } catch {
      setError('No pudimos guardar la información. Inténtalo de nuevo.')
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <form
      className="business-step"
      onSubmit={(event) => void handleSubmit(event)}
    >
      <div className="business-step__heading">
        <h2>Tu negocio</h2>
        <p>Cuéntanos cómo se llama tu negocio y dónde opera.</p>
      </div>

      <div className="business-step__fields">
        <label className="business-step__field">
          Nombre del negocio
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            disabled={isSaving}
            required
          />
        </label>

        <label className="business-step__field">
          Zona horaria
          <select
            value={timezone}
            onChange={(event) => setTimezone(event.target.value)}
            disabled={isSaving}
            required
          >
            <option value="">Selecciona una zona horaria</option>
            {TIMEZONE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && (
        <p className="business-step__error" role="alert">
          {error}
        </p>
      )}

      <div className="business-step__actions">
        <button type="submit" disabled={isSaving}>
          {isSaving ? 'Guardando…' : 'Guardar y continuar'}
        </button>
      </div>
    </form>
  )
}
