export interface DashboardAppointment {
  id: number
  starts_at: string
  ends_at: string
  status: 'CONFIRMED' | 'CANCELLED'
  service: { id: number; name: string }
  customer: { id: number; name: string } | null
  calendar_synced: boolean
  reminder_sent: boolean
}

export interface DashboardResponse {
  date: string
  timezone: string
  summary: { total: number; confirmed: number; cancelled: number }
  appointments: DashboardAppointment[]
}
