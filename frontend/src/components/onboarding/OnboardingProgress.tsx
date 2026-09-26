const steps = [
  { id: 'business', label: 'Tu negocio' },
  { id: 'services', label: 'Servicios' },
  { id: 'hours', label: 'Horarios' },
  { id: 'calendar', label: 'Google Calendar', optional: true },
  { id: 'complete', label: 'Finalizar' },
] as const

export type OnboardingStep = (typeof steps)[number]['id']

interface OnboardingProgressProps {
  currentStep: OnboardingStep
}

export function OnboardingProgress({
  currentStep,
}: OnboardingProgressProps) {
  return (
    <nav aria-label="Progreso de configuración" className="onboarding-progress">
      <ol>
        {steps.map((step, index) => {
          const isActive = step.id === currentStep

          return (
            <li
              className={`onboarding-progress__item${
                isActive ? ' onboarding-progress__item--active' : ''
              }`}
              key={step.id}
              aria-current={isActive ? 'step' : undefined}
            >
              <span className="onboarding-progress__number" aria-hidden="true">
                {index + 1}
              </span>
              <span className="onboarding-progress__label">{step.label}</span>
              {'optional' in step && step.optional && (
                <span className="onboarding-progress__optional">Opcional</span>
              )}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
