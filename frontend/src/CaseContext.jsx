import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { createCase, listCases } from './api.js'

const CaseContext = createContext(null)
const STORAGE_KEY = 'ragnarok:activeCaseId'

/**
 * Owns the list of cases and which one is currently "active." The active
 * case id is persisted in localStorage so it survives a page refresh or the
 * browser being closed and reopened -- this is a real standalone app running
 * in your own browser, not a sandboxed artifact, so localStorage is exactly
 * the right tool here.
 */
export function CaseProvider({ children }) {
  const [cases, setCases] = useState([])
  const [activeCaseId, setActiveCaseIdState] = useState(() => localStorage.getItem(STORAGE_KEY))
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const refreshCases = useCallback(async () => {
    try {
      const list = await listCases()
      setCases(list)
      setError(false)
      return list
    } catch {
      setError(true)
      return []
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      const list = await refreshCases()
      if (cancelled) return
      setActiveCaseIdState((current) => {
        const stillExists = current && list.some((c) => c.id === current)
        return stillExists ? current : list[0]?.id || null
      })
      setLoading(false)
    })()
    return () => {
      cancelled = true
    }
  }, [refreshCases])

  const setActiveCaseId = useCallback((id) => {
    setActiveCaseIdState(id)
    if (id) localStorage.setItem(STORAGE_KEY, id)
    else localStorage.removeItem(STORAGE_KEY)
  }, [])

  const createAndSwitch = useCallback(
    async (name) => {
      const created = await createCase(name)
      await refreshCases()
      setActiveCaseId(created.id)
      return created
    },
    [refreshCases, setActiveCaseId],
  )

  const activeCase = cases.find((c) => c.id === activeCaseId) || null

  return (
    <CaseContext.Provider
      value={{ cases, activeCaseId, activeCase, setActiveCaseId, refreshCases, createAndSwitch, loading, error }}
    >
      {children}
    </CaseContext.Provider>
  )
}

export function useCase() {
  const ctx = useContext(CaseContext)
  if (!ctx) throw new Error('useCase() must be used inside a <CaseProvider>')
  return ctx
}
