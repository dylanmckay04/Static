import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

interface AuthState {
  token: string | null
  setToken: (t: string) => void
  clearToken: () => void
}

const AuthCtx = createContext<AuthState>(null!)
const KEY = 'static:token'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(
    () => localStorage.getItem(KEY),
  )

  const setToken = useCallback((t: string) => {
    localStorage.setItem(KEY, t)
    setTokenState(t)
  }, [])

  const clearToken = useCallback(() => {
    localStorage.removeItem(KEY)
    setTokenState(null)
  }, [])

  const value = useMemo(
    () => ({ token, setToken, clearToken }),
    [token, setToken, clearToken],
  )

  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>
}

export const useAuth = () => useContext(AuthCtx)
