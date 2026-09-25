import type { GoogleIdentityApi } from './types/googleIdentity'

const SCRIPT_ID = 'google-identity-services'
const SCRIPT_SOURCE = 'https://accounts.google.com/gsi/client'

let loading: Promise<GoogleIdentityApi> | null = null

export function loadGoogleIdentity(): Promise<GoogleIdentityApi> {
  if (window.google?.accounts.id) return Promise.resolve(window.google)
  if (loading) return loading

  loading = new Promise((resolve, reject) => {
    const existing = document.getElementById(SCRIPT_ID) as HTMLScriptElement | null
    const script = existing ?? document.createElement('script')

    const loaded = () => {
      if (window.google?.accounts.id) resolve(window.google)
      else {
        script.remove()
        loading = null
        reject(new Error('Google Identity Services did not initialize'))
      }
    }
    const failed = () => {
      script.remove()
      loading = null
      reject(new Error('Google Identity Services failed to load'))
    }

    script.addEventListener('load', loaded, { once: true })
    script.addEventListener('error', failed, { once: true })

    if (!existing) {
      script.id = SCRIPT_ID
      script.src = SCRIPT_SOURCE
      script.async = true
      script.defer = true
      document.head.append(script)
    }
  })

  return loading
}
