import { useEffect } from 'react'
import { DashboardPage } from './pages/DashboardPage'
import { LoginPage } from './pages/LoginPage'
import { OnboardingPage } from './pages/OnboardingPage'
import { RootGate } from './components/RootGate'

function LegacyLoginRedirect() {
  useEffect(() => {
    window.location.replace(`/login${window.location.search}`)
  }, [])

  return null
}

export default function App() {
  if (window.location.pathname === '/google-signin-demo') {
    return <LegacyLoginRedirect />
  }
  if (window.location.pathname === '/login') {
    return <LoginPage />
  }
  if (window.location.pathname === '/onboarding') {
    return <OnboardingPage />
  }
  return (
    <RootGate>
      <DashboardPage />
    </RootGate>
  )
}
