import { useState, type ReactNode } from 'react'
import { logoutAdmin } from '../../api/adminAuth'
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
  const [isLoggingOut, setIsLoggingOut] = useState(false)
  const [logoutError, setLogoutError] = useState(false)

  async function handleLogout() {
    if (isLoggingOut) return

    setIsLoggingOut(true)
    setLogoutError(false)
    try {
      await logoutAdmin()
      window.location.assign('/login')
    } catch {
      setIsLoggingOut(false)
      setLogoutError(true)
    }
  }

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

          <div className="onboarding__header-copy">
            <button
              className="onboarding__logout"
              type="button"
              onClick={handleLogout}
              disabled={isLoggingOut}
            >
              {isLoggingOut ? 'Cerrando sesión…' : 'Cerrar sesión'}
            </button>
            <p className="onboarding__eyebrow">Configuración inicial</p>
            <h1>Prepara tu negocio para recibir reservas</h1>
            <p className="onboarding__intro">
              Configura la información básica que usaremos para gestionar tus
              citas.
            </p>
            {logoutError && (
              <p className="onboarding__logout-error" role="alert">
                No pudimos cerrar la sesión. Inténtalo nuevamente.
              </p>
            )}
          </div>
        </header>

        <OnboardingProgress currentStep={currentStep} />

        <section className="onboarding__content">{children}</section>
      </div>
    </main>
  )
}
