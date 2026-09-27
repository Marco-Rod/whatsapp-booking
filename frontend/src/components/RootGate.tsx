import { useEffect, useState, type ReactNode } from 'react'
import { AdminAuthError, getOnboardingStatus } from '../api/adminAuth'

interface RootGateProps {
  children: ReactNode
}

type State = 'loading' | 'error' | 'authorized'

export function RootGate({ children }: RootGateProps) {
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState<State>('loading')

  useEffect(() => {
    let active = true
    setState('loading')

    getOnboardingStatus()
      .then((status) => {
        if (!active) return

        if (status.completed && status.ready) {
          setState('authorized')
          return
        }

        window.location.assign('/onboarding')
      })
      .catch((error: unknown) => {
        if (!active) return

        if (error instanceof AdminAuthError && error.status === 401) {
          window.location.assign('/login')
          return
        }

        setState('error')
      })

    return () => {
      active = false
    }
  }, [attempt])

  if (state === 'authorized') {
    return <>{children}</>
  }

  if (state === 'error') {
    return (
      <main>
        <p>No pudimos comprobar tu sesión.</p>
        <button type="button" onClick={() => setAttempt((value) => value + 1)}>
          Reintentar
        </button>
      </main>
    )
  }

  return <p role="status">Comprobando tu sesión…</p>
}
