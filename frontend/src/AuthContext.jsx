import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { getMe, getStoredToken, login as apiLogin, register as apiRegister, setStoredToken } from './api.js'

const AuthContext = createContext(null)

/**
 * Owns the current login state. On mount, if a token is already stored
 * (from a previous session), it's verified against GET /auth/me -- if the
 * server rejects it (expired, or the user was deleted), we fall back to the
 * login screen rather than showing a broken app.
 */
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const token = getStoredToken()
    if (!token) {
      setLoading(false)
      return
    }
    getMe()
      .then(setUser)
      .catch(() => setStoredToken(null))
      .finally(() => setLoading(false))
  }, [])

  const login = useCallback(async (email, password) => {
    const data = await apiLogin(email, password)
    setStoredToken(data.access_token)
    setUser(data.user)
  }, [])

  const register = useCallback(async (email, password) => {
    const data = await apiRegister(email, password)
    setStoredToken(data.access_token)
    setUser(data.user)
  }, [])

  const logout = useCallback(() => {
    setStoredToken(null)
    setUser(null)
  }, [])

  return <AuthContext.Provider value={{ user, loading, login, register, logout }}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth() must be used inside an <AuthProvider>')
  return ctx
}
