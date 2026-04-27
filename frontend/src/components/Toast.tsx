import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'

export type ToastKind = 'default' | 'danger' | 'success' | 'accent'

interface ToastItem {
  id:      number
  message: string
  kind:    ToastKind
  exiting: boolean
}

interface ToastCtx {
  toast: (message: string, kind?: ToastKind) => void
}

const Ctx = createContext<ToastCtx>({ toast: () => {} })

let _nextId = 0
const DURATION = 3200
const EXIT_MS  = 400

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const timers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map())

  const dismiss = useCallback((id: number) => {
    setToasts(prev => prev.map(t => t.id === id ? { ...t, exiting: true } : t))
    const out = setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id))
      timers.current.delete(id)
    }, EXIT_MS)
    timers.current.set(id, out)
  }, [])

  const toast = useCallback((message: string, kind: ToastKind = 'default') => {
    const id = _nextId++
    setToasts(prev => [...prev, { id, message, kind, exiting: false }])
    const t = setTimeout(() => dismiss(id), DURATION)
    timers.current.set(id, t)
  }, [dismiss])

  // Cleanup on unmount
  useEffect(() => {
    const map = timers.current
    return () => { map.forEach(t => clearTimeout(t)); map.clear() }
  }, [])

  return (
    <Ctx.Provider value={{ toast }}>
      {children}
      <div className="toast-container">
        {toasts.map(t => (
          <div
            key={t.id}
            className={`toast ${t.kind !== 'default' ? t.kind : ''} ${t.exiting ? 'exiting' : ''}`}
          >
            {t.message}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  )
}

export function useToast() { return useContext(Ctx).toast }
