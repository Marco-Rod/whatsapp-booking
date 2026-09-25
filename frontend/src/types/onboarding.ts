export interface OnboardingStatus {
  completed: boolean
  ready: boolean
  steps: {
    business: boolean
    services: boolean
    hours: boolean
    calendar: boolean
  }
}
