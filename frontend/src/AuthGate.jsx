import { useAuth } from './AuthContext.jsx'
import { CaseProvider } from './CaseContext.jsx'
import LoginPage from './pages/LoginPage.jsx'
import App from './App.jsx'

export default function AuthGate() {
  const { user, loading } = useAuth()

  if (loading) {
    return <div className="auth-loading">Loading…</div>
  }

  if (!user) {
    return <LoginPage />
  }

  // CaseProvider (and everything it fetches) only ever mounts once we know
  // there's a valid logged-in user -- no case data is requested beforehand.
  return (
    <CaseProvider>
      <App />
    </CaseProvider>
  )
}
