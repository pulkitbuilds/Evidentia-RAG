import { useState } from 'react'
import { useAuth } from '../AuthContext.jsx'

export default function LoginPage() {
  const { login, register } = useAuth()

  const [mode, setMode] = useState('login') // 'login' | 'register'
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e) {
    e.preventDefault()
    if (!email.trim() || !password) return
    setBusy(true)
    setError('')
    try {
      if (mode === 'login') {
        await login(email.trim(), password)
      } else {
        await register(email.trim(), password)
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Something went wrong. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-shell">
      <div className="login-card">
        <div className="login-header">
          <h1>Evidentia</h1>
          <span className="tagline">Evidence-First Research &amp; Writing</span>
        </div>

        <div className="login-mode-toggle">
          <button
            type="button"
            className={mode === 'login' ? 'tab tab-active' : 'tab'}
            onClick={() => {
              setMode('login')
              setError('')
            }}
          >
            Log In
          </button>
          <button
            type="button"
            className={mode === 'register' ? 'tab tab-active' : 'tab'}
            onClick={() => {
              setMode('register')
              setError('')
            }}
          >
            Create Account
          </button>
        </div>

        <form onSubmit={handleSubmit} className="login-form">
          <label className="login-field">
            <span>Email</span>
            <input
              type="email"
              className="title-input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              autoFocus
              disabled={busy}
            />
          </label>

          <label className="login-field">
            <span>Password</span>
            <input
              type="password"
              className="title-input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              disabled={busy}
            />
          </label>

          {mode === 'register' && <p className="muted login-hint">At least 8 characters.</p>}

          {error && <div className="banner-error">{error}</div>}

          <button type="submit" disabled={busy || !email.trim() || !password}>
            {busy ? 'Please wait…' : mode === 'login' ? 'Log In' : 'Create Account'}
          </button>
        </form>

        <p className="login-footnote">
          {mode === 'login' ? (
            <>
              New here?{' '}
              <button type="button" className="link-button" onClick={() => setMode('register')}>
                Create an account
              </button>
            </>
          ) : (
            <>
              Already have an account?{' '}
              <button type="button" className="link-button" onClick={() => setMode('login')}>
                Log in
              </button>
            </>
          )}
        </p>
      </div>
    </div>
  )
}
