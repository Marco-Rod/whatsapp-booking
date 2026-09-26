import { useEffect, useState } from 'react'
import {
  AdminAuthError,
  getOnboardingBusiness,
  getOnboardingHours,
  getOnboardingServices,
  getOnboardingStatus,
  type OnboardingHoursConfiguration,
  type OnboardingServicesConfiguration,
} from '../api/adminAuth'
import { BusinessStep } from '../components/onboarding/BusinessStep'
import { CalendarStep } from '../components/onboarding/CalendarStep'
import { CompleteStep } from '../components/onboarding/CompleteStep'
import { HoursStep } from '../components/onboarding/HoursStep'
import { OnboardingLayout } from '../components/onboarding/OnboardingLayout'
import type { OnboardingStep } from '../components/onboarding/OnboardingProgress'
import { ServicesStep } from '../components/onboarding/ServicesStep'
import type { OnboardingStatus } from '../types/onboarding'

function getInitialStep(status: OnboardingStatus): OnboardingStep {
  if (!status.steps.business) return 'business'
  if (!status.steps.services) return 'services'
  if (!status.steps.hours) return 'hours'
  return 'calendar'
}

function getRequestedStep(): OnboardingStep | null {
  const step = new URLSearchParams(window.location.search).get('step')
  const validSteps: OnboardingStep[] = [
    'business',
    'services',
    'hours',
    'calendar',
    'complete',
  ]

  return validSteps.includes(step as OnboardingStep)
    ? (step as OnboardingStep)
    : null
}

type GoogleCalendarNotice = 'connected' | 'error' | null

function consumeGoogleCalendarNotice(): GoogleCalendarNotice {
  const url = new URL(window.location.href)
  const result = url.searchParams.get('google_calendar')

  if (result !== 'connected' && result !== 'error') {
    return null
  }

  url.searchParams.delete('google_calendar')
  window.history.replaceState(window.history.state, '', url)

  return result
}

export function OnboardingPage() {
  const [status, setStatus] = useState<OnboardingStatus | null>(null)
  const [currentStep, setCurrentStep] = useState<OnboardingStep | null>(null)
  const [googleCalendarNotice] = useState<GoogleCalendarNotice>(
    consumeGoogleCalendarNotice,
  )
  const [businessConfiguration, setBusinessConfiguration] = useState<{
    name: string
    timezone: string
  } | null>(null)
  const [error, setError] = useState(false)
  const [businessConfigurationError, setBusinessConfigurationError] =
    useState(false)
  const [servicesConfiguration, setServicesConfiguration] =
    useState<OnboardingServicesConfiguration | null>(null)
  const [servicesConfigurationError, setServicesConfigurationError] =
    useState(false)
  const [hoursConfiguration, setHoursConfiguration] =
    useState<OnboardingHoursConfiguration | null>(null)
  const [hoursConfigurationError, setHoursConfigurationError] = useState(false)

  async function loadStatus() {
    setError(false)
    setStatus(null)

    try {
      const onboardingStatus = await getOnboardingStatus()
      const requestedStep = getRequestedStep()

      if (
        onboardingStatus.completed &&
        onboardingStatus.ready &&
        requestedStep === null
      ) {
        window.location.assign('/')
        return
      }

      setStatus(onboardingStatus)
      setCurrentStep(requestedStep ?? getInitialStep(onboardingStatus))
    } catch (requestError) {
      if (requestError instanceof AdminAuthError && requestError.status === 401) {
        window.location.assign('/google-signin-demo')
        return
      }

      setError(true)
    }
  }

  useEffect(() => {
    void loadStatus()
  }, [])

  async function loadBusinessConfiguration() {
    setBusinessConfigurationError(false)
    setBusinessConfiguration(null)

    try {
      setBusinessConfiguration(await getOnboardingBusiness())
    } catch (requestError) {
      if (requestError instanceof AdminAuthError && requestError.status === 401) {
        window.location.assign('/google-signin-demo')
        return
      }

      setBusinessConfigurationError(true)
    }
  }

  useEffect(() => {
    if (currentStep === 'business') {
      void loadBusinessConfiguration()
    }
  }, [currentStep])

  async function loadServicesConfiguration() {
    setServicesConfigurationError(false)
    setServicesConfiguration(null)

    try {
      setServicesConfiguration(await getOnboardingServices())
    } catch (requestError) {
      if (requestError instanceof AdminAuthError && requestError.status === 401) {
        window.location.assign('/google-signin-demo')
        return
      }

      setServicesConfigurationError(true)
    }
  }

  useEffect(() => {
    if (currentStep === 'services') {
      void loadServicesConfiguration()
    }
  }, [currentStep])

  async function loadHoursConfiguration() {
    setHoursConfigurationError(false)
    setHoursConfiguration(null)

    try {
      setHoursConfiguration(await getOnboardingHours())
    } catch (requestError) {
      if (requestError instanceof AdminAuthError && requestError.status === 401) {
        window.location.assign('/google-signin-demo')
        return
      }

      setHoursConfigurationError(true)
    }
  }

  useEffect(() => {
    if (currentStep === 'hours') {
      void loadHoursConfiguration()
    }
  }, [currentStep])

  if (error) {
    return (
      <main>
        <p>No pudimos cargar tu configuración.</p>
        <button type="button" onClick={() => void loadStatus()}>
          Reintentar
        </button>
      </main>
    )
  }

  if (status === null || currentStep === null) {
    return <p>Cargando configuración…</p>
  }

  function handleBusinessSaved(updatedStatus: OnboardingStatus) {
    setStatus(updatedStatus)
    setCurrentStep('services')
  }

  function handleServicesSaved(updatedStatus: OnboardingStatus) {
    setStatus(updatedStatus)
    setCurrentStep('hours')
  }

  function handleHoursSaved(updatedStatus: OnboardingStatus) {
    setStatus(updatedStatus)
    setCurrentStep('calendar')
  }

  function handleCalendarContinue() {
    setCurrentStep('complete')
  }

  function handleCalendarUnauthorized() {
    window.location.assign('/google-signin-demo')
  }

  function handleCompleted(updatedStatus: OnboardingStatus) {
    setStatus(updatedStatus)

    if (updatedStatus.completed) {
      window.location.assign('/')
    }
  }

  return (
    <OnboardingLayout currentStep={currentStep}>
      {currentStep === 'business' && businessConfiguration && (
        <BusinessStep
          initialName={businessConfiguration.name}
          initialTimezone={businessConfiguration.timezone}
          onSaved={handleBusinessSaved}
        />
      )}
      {currentStep === 'business' && businessConfigurationError && (
        <>
          <p>No pudimos cargar la información de tu negocio.</p>
          <button type="button" onClick={() => void loadBusinessConfiguration()}>
            Reintentar
          </button>
        </>
      )}
      {currentStep === 'business' &&
        !businessConfiguration &&
        !businessConfigurationError && <p>Cargando información del negocio…</p>}
      {currentStep === 'services' && servicesConfiguration && (
        <ServicesStep
          initialServices={servicesConfiguration.services}
          onSaved={handleServicesSaved}
        />
      )}
      {currentStep === 'services' && servicesConfigurationError && (
        <>
          <p>No pudimos cargar tus servicios.</p>
          <button type="button" onClick={() => void loadServicesConfiguration()}>
            Reintentar
          </button>
        </>
      )}
      {currentStep === 'services' &&
        !servicesConfiguration &&
        !servicesConfigurationError && <p>Cargando servicios…</p>}
      {currentStep === 'hours' && hoursConfiguration && (
        <HoursStep
          initialHours={hoursConfiguration.hours}
          onSaved={handleHoursSaved}
        />
      )}
      {currentStep === 'hours' && hoursConfigurationError && (
        <>
          <p>No pudimos cargar tus horarios.</p>
          <button type="button" onClick={() => void loadHoursConfiguration()}>
            Reintentar
          </button>
        </>
      )}
      {currentStep === 'hours' && !hoursConfiguration && !hoursConfigurationError && (
        <p>Cargando horarios…</p>
      )}
      {currentStep === 'calendar' && (
        <>
          {googleCalendarNotice === 'connected' && (
            <p role="status">Google Calendar se conectó correctamente.</p>
          )}
          {googleCalendarNotice === 'error' && (
            <p role="alert">
              No pudimos conectar Google Calendar. Inténtalo de nuevo.
            </p>
          )}
          <CalendarStep
            onContinue={handleCalendarContinue}
            onUnauthorized={handleCalendarUnauthorized}
          />
        </>
      )}
      {currentStep === 'complete' && (
        <CompleteStep
          status={status}
          onCompleted={handleCompleted}
          onUnauthorized={handleCalendarUnauthorized}
        />
      )}
    </OnboardingLayout>
  )
}
