import { useEffect, useRef, useState } from 'react'
import { loadGoogleIdentity } from '../googleIdentity'

interface GoogleSignInButtonProps {
  clientId?: string
  onCredential(credential: string): void
  onError?(): void
}

type State = 'loading' | 'ready' | 'error' | 'unconfigured'

export function GoogleSignInButton({
  clientId,
  onCredential,
  onError,
}: GoogleSignInButtonProps) {
  const button = useRef<HTMLDivElement>(null)
  const [state, setState] = useState<State>(
    clientId ? 'loading' : 'unconfigured',
  )

  useEffect(() => {
    if (!clientId) {
      setState('unconfigured')
      return
    }

    let active = true
    loadGoogleIdentity().then(google => {
      if (!active || !button.current) return

      google.accounts.id.initialize({
        client_id: clientId,
        use_fedcm_for_button: true,
        callback: response => {
          if (!response.credential) {
            setState('error')
            onError?.()
            return
          }
          onCredential(response.credential)
        },
      })

      button.current.replaceChildren()
      google.accounts.id.renderButton(button.current, {
        type: 'standard',
        theme: 'outline',
        size: 'large',
        text: 'continue_with',
        shape: 'rectangular',
      })
      setState('ready')
    }).catch(() => {
      if (!active) return
      setState('error')
      onError?.()
    })

    return () => {
      active = false
    }
  }, [clientId, onCredential, onError])

  return <div className="google-sign-in-control">
    <div ref={button} aria-label="Continuar con Google"/>
    {state === 'loading' && <p role="status">Cargando Google Sign-In…</p>}
    {state === 'unconfigured' && <p role="alert">Google Sign-In no está configurado.</p>}
    {state === 'error' && <p role="alert">No pudimos cargar Google Sign-In. Inténtalo nuevamente.</p>}
  </div>
}
