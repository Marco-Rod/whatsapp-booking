import { DashboardPage } from './pages/DashboardPage'
import { GoogleSignInDemoPage } from './pages/GoogleSignInDemoPage'

export default function App() {
  if (window.location.pathname === '/google-signin-demo/unconfigured') {
    return <GoogleSignInDemoPage clientId=""/>
  }
  if (window.location.pathname === '/google-signin-demo') {
    return <GoogleSignInDemoPage/>
  }
  return <DashboardPage/>
}
