import type { ReactNode } from 'react'
import {
  OnboardingProgress,
  type OnboardingStep,
} from './OnboardingProgress'

interface OnboardingLayoutProps {
  currentStep: OnboardingStep
  children: ReactNode
}

export function OnboardingLayout({
  currentStep,
  children,
}: OnboardingLayoutProps) {
  return (
    <main className="onboarding">
      <div className="onboarding__shell">
        <header className="onboarding__header">
          <div className="onboarding__brand">
            <span className="onboarding__logo" aria-hidden="true">
              W
            </span>
            <span>WhatsApp Booking</span>
          </div>

          <div>
            <p className="onboarding__eyebrow">Configuración inicial</p>
            <h1>Prepara tu negocio para recibir reservas</h1>
            <p className="onboarding__intro">
              Configura la información básica que usaremos para gestionar tus
              citas.
            </p>
          </div>
        </header>

        <OnboardingProgress currentStep={currentStep} />

        <section className="onboarding__content">{children}</section>
      </div>
    </main>
  )
}
