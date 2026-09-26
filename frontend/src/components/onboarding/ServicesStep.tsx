import { useState } from 'react'
import {
  updateOnboardingServices,
  type OnboardingServiceConfiguration,
} from '../../api/adminAuth'
import type { OnboardingStatus } from '../../types/onboarding'

const DURATION_OPTIONS = [15, 30, 45, 60, 90, 120]

interface ServicesStepProps {
  initialServices: OnboardingServiceConfiguration[]
  onSaved: (status: OnboardingStatus) => void
}

function createEmptyService(): OnboardingServiceConfiguration {
  return { name: '', duration_minutes: 60 }
}

export function ServicesStep({
  initialServices,
  onSaved,
}: ServicesStepProps) {
  const [services, setServices] = useState<OnboardingServiceConfiguration[]>(
    initialServices.length > 0 ? initialServices : [createEmptyService()],
  )
  const [error, setError] = useState<string | null>(null)
  const [isSaving, setIsSaving] = useState(false)

  function updateService(
    index: number,
    field: keyof OnboardingServiceConfiguration,
    value: string | number,
  ) {
    setServices((currentServices) =>
      currentServices.map((service, serviceIndex) =>
        serviceIndex === index ? { ...service, [field]: value } : service,
      ),
    )
  }

  function validateServices(): OnboardingServiceConfiguration[] | null {
    if (services.length === 0) {
      setError('Agrega al menos un servicio.')
      return null
    }

    const normalizedServices = services.map((service) => ({
      ...service,
      name: service.name.trim(),
    }))
    if (normalizedServices.some((service) => !service.name)) {
      setError('Todos los servicios necesitan un nombre.')
      return null
    }
    if (
      new Set(
        normalizedServices.map((service) => service.name.toLocaleLowerCase()),
      ).size !== normalizedServices.length
    ) {
      setError('Los nombres de los servicios deben ser únicos.')
      return null
    }
    if (normalizedServices.some((service) => service.duration_minutes <= 0)) {
      setError('La duración de cada servicio debe ser válida.')
      return null
    }

    return normalizedServices
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()

    const validServices = validateServices()
    if (validServices === null) return

    setError(null)
    setIsSaving(true)

    try {
      const status = await updateOnboardingServices({
        services: validServices,
      })
      onSaved(status)
    } catch {
      setError('No pudimos guardar los servicios. Inténtalo de nuevo.')
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <form
      className="services-step"
      onSubmit={(event) => void handleSubmit(event)}
    >
      <div className="services-step__heading">
        <h2>Servicios</h2>
        <p>Agrega los servicios que tus clientes pueden reservar.</p>
      </div>

      {services.map((service, index) => (
        <div className="services-step__row" key={index}>
          <label className="services-step__field services-step__field--name">
            Servicio
            <input
              value={service.name}
              onChange={(event) =>
                updateService(index, 'name', event.target.value)
              }
              disabled={isSaving}
              required
            />
          </label>
          <label className="services-step__field services-step__field--duration">
            Duración
            <select
              value={service.duration_minutes}
              onChange={(event) =>
                updateService(index, 'duration_minutes', Number(event.target.value))
              }
              disabled={isSaving}
            >
              {DURATION_OPTIONS.map((duration) => (
                <option key={duration} value={duration}>
                  {duration} min
                </option>
              ))}
            </select>
          </label>
          <button
            className="services-step__remove"
            type="button"
            onClick={() =>
              setServices((currentServices) =>
                currentServices.filter((_, serviceIndex) => serviceIndex !== index),
              )
            }
            disabled={isSaving}
          >
            Eliminar
          </button>
        </div>
      ))}

      <button
        className="services-step__add"
        type="button"
        onClick={() => setServices((currentServices) => [...currentServices, createEmptyService()])}
        disabled={isSaving}
      >
        + Agregar servicio
      </button>

      {error && (
        <p className="services-step__error" role="alert">
          {error}
        </p>
      )}

      <div className="services-step__actions">
        <button type="submit" disabled={isSaving}>
          {isSaving ? 'Guardando…' : 'Guardar y continuar'}
        </button>
      </div>
    </form>
  )
}
