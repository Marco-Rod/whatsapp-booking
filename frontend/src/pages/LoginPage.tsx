import { useCallback, useEffect, useState } from 'react'
import {
  AdminAuthError,
  getOnboardingStatus,
  linkGoogleAdmin,
  loginWithGoogle,
} from '../api/adminAuth'
import { GoogleSignInButton } from '../components/GoogleSignInButton'

const googleClientId = import.meta.env.VITE_GOOGLE_IDENTITY_CLIENT_ID

export function LoginPage() {
  const [activation, setActivation] = useState(false)
  const [adminToken, setAdminToken] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [sessionState, setSessionState] = useState<
    'checking' | 'unauthenticated' | 'error'
  >('checking')
  const [sessionAttempt, setSessionAttempt] = useState(0)

  useEffect(() => {
    let active = true
    setSessionState('checking')

    getOnboardingStatus()
      .then((onboarding) => {
        if (!active) return

        window.location.assign(
          onboarding.completed && onboarding.ready ? '/' : '/onboarding',
        )
      })
      .catch((error: unknown) => {
        if (!active) return

        if (error instanceof AdminAuthError && error.status === 401) {
          setSessionState('unauthenticated')
          return
        }

        setSessionState('error')
      })

    return () => {
      active = false
    }
  }, [sessionAttempt])

  const receiveCredential = useCallback(async (credential: string) => {
    setMessage(null)
    setSubmitting(true)
    try {
      await loginWithGoogle(credential)
      const onboarding = await getOnboardingStatus()

      window.location.assign(
        onboarding.completed && onboarding.ready ? '/' : '/onboarding',
      )
    } catch (error) {
      setMessage(
        error instanceof AdminAuthError && error.status === 401
          ? 'Esta cuenta todavía no está vinculada.'
          : 'No pudimos iniciar sesión. Inténtalo nuevamente.',
      )
    } finally {
      setSubmitting(false)
    }
  }, [])

  const linkCredential = useCallback(async (credential: string) => {
    const activationToken = adminToken
    setAdminToken('')
    setMessage(null)
    setSubmitting(true)
    try {
      await linkGoogleAdmin(credential, activationToken)
      await getOnboardingStatus()
      setActivation(false)
      window.location.assign('/onboarding')
    } catch {
      setMessage('No pudimos activar este negocio. Verifica la clave e inténtalo nuevamente.')
    } finally {
      setSubmitting(false)
    }
  }, [adminToken])

  const handleError = useCallback(() => {
    setMessage('No pudimos recibir tu identidad de Google.')
  }, [])

  if (sessionState === 'checking') {
    return <p role="status">Comprobando tu sesión…</p>
  }

  if (sessionState === 'error') {
    return (
      <main className="google-sign-in-page">
        <section className="google-sign-in-card">
          <h1>No pudimos comprobar tu sesión.</h1>
          <button
            type="button"
            onClick={() => setSessionAttempt((value) => value + 1)}
          >
            Reintentar
          </button>
        </section>
      </main>
    )
  }

  return <main className="google-sign-in-page">
    <section className="google-sign-in-card">
      <div className="brand google-sign-in-brand">
        <span className="brand-mark">w<span>·</span></span>
        <span>WhatsApp <b>Booking</b></span>
      </div>
      <h1>Administra tu negocio<span>.</span></h1>
      <p>Accede para administrar tu negocio y tus reservaciones.</p>
      {activation ? <div className="activation-form">
        <label htmlFor="activation-key">Clave de activación</label>
        <input
          id="activation-key"
          type="password"
          autoComplete="off"
          value={adminToken}
          onChange={event => setAdminToken(event.target.value)}
        />
        {adminToken && !submitting && <GoogleSignInButton
          clientId={googleClientId}
          onCredential={linkCredential}
          onError={handleError}
        />}
        <button className="text-button" onClick={() => {
          setAdminToken('')
          setActivation(false)
          setMessage(null)
        }}>Volver al acceso normal</button>
      </div> : <>
        <GoogleSignInButton
          clientId={googleClientId}
          onCredential={receiveCredential}
          onError={handleError}
        />
        <button className="text-button activation-link" onClick={() => {
          setActivation(true)
          setMessage(null)
        }}>¿Es la primera vez que accedes? Activar mi negocio</button>
      </>}
      {submitting && <div className="identity-received" role="status">Verificando identidad…</div>}
      {message && <div className="auth-message" role="status">{message}</div>}
    </section>
  </main>
}
