import { DashboardPage } from './pages/DashboardPage'
import { GoogleSignInDemoPage } from './pages/GoogleSignInDemoPage'
import { OnboardingPage } from './pages/OnboardingPage'

export default function App() {
  if (window.location.pathname === '/google-signin-demo/unconfigured') {
    return <GoogleSignInDemoPage clientId=""/>
  }
  if (window.location.pathname === '/google-signin-demo') {
    return <GoogleSignInDemoPage/>
  }
  if (window.location.pathname === '/onboarding') {
    return <OnboardingPage />
  }
  return <DashboardPage/>
}
