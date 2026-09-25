export interface GoogleCredentialResponse {
  credential?: string
}

export interface GoogleButtonConfiguration {
  type: 'standard'
  theme: 'outline'
  size: 'large'
  text: 'continue_with'
  shape: 'rectangular'
}

export interface GoogleIdentityApi {
  accounts: {
    id: {
      initialize(options: {
        client_id: string
        callback(response: GoogleCredentialResponse): void
        use_fedcm_for_button: boolean
      }): void
      renderButton(
        parent: HTMLElement,
        options: GoogleButtonConfiguration,
      ): void
    }
  }
}

declare global {
  interface Window {
    google?: GoogleIdentityApi
  }
}
