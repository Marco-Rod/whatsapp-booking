export interface GoogleCalendarIntegration {
  connected: boolean
  calendar_id: string | null
  connected_at: string | null
}

export interface GoogleCalendarDisconnectResult {
  connected: false
}
