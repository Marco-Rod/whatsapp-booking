import { useCallback, useState } from 'react'
import {
  AdminAuthError,
  getOnboardingStatus,
  linkGoogleAdmin,
  loginWithGoogle,
  logoutAdmin,
} from '../api/adminAuth'
import { GoogleSignInButton } from '../components/GoogleSignInButton'
import type { OnboardingStatus } from '../types/onboarding'

const googleClientId = import.meta.env.VITE_GOOGLE_IDENTITY_CLIENT_ID

interface GoogleSignInDemoPageProps {
  clientId?: string
}

export function GoogleSignInDemoPage({
  clientId = googleClientId,
}: GoogleSignInDemoPageProps = {}) {
  const [activation, setActivation] = useState(false)
  const [adminToken, setAdminToken] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const [status, setStatus] = useState<OnboardingStatus | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const receiveCredential = useCallback(async (credential: string) => {
    setMessage(null)
    setSubmitting(true)
    try {
      await loginWithGoogle(credential)
      const onboarding = await getOnboardingStatus()
      setStatus(onboarding)
      setMessage('Sesión iniciada correctamente.')
    } catch (error) {
      setStatus(null)
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
      const onboarding = await getOnboardingStatus()
      setStatus(onboarding)
      setActivation(false)
      setMessage('Tu cuenta Google quedó vinculada correctamente.')
    } catch {
      setStatus(null)
      setMessage('No pudimos activar este negocio. Verifica la clave e inténtalo nuevamente.')
    } finally {
      setSubmitting(false)
    }
  }, [adminToken])

  const handleError = useCallback(() => {
    setMessage('No pudimos recibir tu identidad de Google.')
  }, [])

  const logout = useCallback(async () => {
    try {
      await logoutAdmin()
      setStatus(null)
      setMessage('Sesión cerrada.')
    } catch {
      setMessage('No pudimos cerrar la sesión.')
    }
  }, [])

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
          clientId={clientId}
          onCredential={linkCredential}
          onError={handleError}
        />}
        <button className="text-button" onClick={() => {
          setAdminToken('')
          setActivation(false)
          setMessage(null)
        }}>Volver al acceso normal</button>
      </div> : !status && <>
        <GoogleSignInButton
          clientId={clientId}
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
      {status && <div className="onboarding-result">
        <strong>✓ Acceso administrativo confirmado</strong>
        <span>Onboarding: {status.completed ? 'completado' : 'pendiente'} · Configuración: {status.ready ? 'lista' : 'incompleta'}</span>
        <button className="text-button" onClick={logout}>Cerrar sesión</button>
      </div>}
    </section>
  </main>
}
