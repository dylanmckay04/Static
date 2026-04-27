import {
  type KeyboardEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { departSeance, dissolveSeance, enterSeance, getMyPresence, getSeance, getWhispers, listPresences } from '../api/seances'
import type { OwnPresenceResponse, PresenceResponse, WhisperResponse } from '../api/types'
import type { WsMessage } from '../api/types'
import { useSeanceSocket } from '../lib/useSeanceSocket'
import { useAuth } from '../store/auth'

// ── Helpers ───────────────────────────────────────────────────────────────────

const SIGIL_COLORS = [
  '#a78bfa', '#60a5fa', '#34d399', '#f472b6',
  '#fb923c', '#e879f9', '#2dd4bf', '#facc15',
]
function sigilColor(sigil: string) {
  let h = 0
  for (let i = 0; i < sigil.length; i++) h = (h * 31 + sigil.charCodeAt(i)) | 0
  return SIGIL_COLORS[Math.abs(h) % SIGIL_COLORS.length]
}

function formatTime(iso: string) {
  const d = new Date(iso)
  const now = new Date()
  const timeStr = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  if (d.toDateString() === now.toDateString()) return timeStr
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' + timeStr
}

/** Merge two whisper arrays, de-duplicate by id, sort oldest→newest. */
function mergeWhispers(a: WhisperResponse[], b: WhisperResponse[]): WhisperResponse[] {
  const map = new Map<number, WhisperResponse>()
  for (const w of [...a, ...b]) map.set(w.id, w)
  return Array.from(map.values()).sort((x, y) => x.id - y.id)
}

// ── Component ─────────────────────────────────────────────────────────────────

type PageStatus = 'loading' | 'ready' | 'error'

export default function RoomPage() {
  const { id }      = useParams<{ id: string }>()
  const seanceId    = Number(id)
  const { token, clearToken } = useAuth()
  const navigate    = useNavigate()

  const [status,     setStatus]     = useState<PageStatus>('loading')
  const [pageError,  setPageError]  = useState<string | null>(null)
  const [seanceName, setSeanceName] = useState('')
  const [myPresence, setMyPresence] = useState<OwnPresenceResponse | null>(null)
  const [presences,  setPresences]  = useState<PresenceResponse[]>([])
  const [whispers,   setWhispers]   = useState<WhisperResponse[]>([])
  const [nextBefore, setNextBefore] = useState<number | null>(null)
  const [loadingMore, setLoadingMore] = useState(false)
  const [draft,      setDraft]      = useState('')
  const [wsReady,    setWsReady]    = useState(false)

  const bottomRef    = useRef<HTMLDivElement>(null)
  const textareaRef  = useRef<HTMLTextAreaElement>(null)
  const mountedRef   = useRef(true)
  const mySignRef    = useRef<string>('')  // stable ref for sigil used in callbacks

  useEffect(() => { return () => { mountedRef.current = false } }, [])

  // ── Initial load ─────────────────────────────────────────────────────────

  useEffect(() => {
    if (!token) return
    let cancelled = false

    const init = async () => {
      try {
        // 1. Enter seance or recover existing presence
        let own: OwnPresenceResponse
        try {
          own = await enterSeance(seanceId, token)
        } catch (err) {
          if (err instanceof ApiError && err.status === 409) {
            // Already present (e.g., warden, or page refresh) — recover existing presence
            try {
              own = await getMyPresence(seanceId, token)
            } catch (getErr) {
              if (getErr instanceof ApiError && getErr.status === 404) {
                // Shouldn't happen (409 means we're present), but fallback to trying enter again
                own = await enterSeance(seanceId, token)
              } else {
                throw getErr
              }
            }
          } else if (err instanceof ApiError && err.status === 401) {
            clearToken(); return
          } else {
            throw err
          }
        }
        if (cancelled) return
        mySignRef.current = own.sigil
        setMyPresence(own)

        // 2. Parallel: seance details (just for name) + presence list
        const [, presenceList] = await Promise.all([
          // Fetch seance details for the name
          (async () => {
            try {
              const details = await getSeance(seanceId, token)
              if (!cancelled && details.name) setSeanceName(details.name)
            } catch (err) {
              console.warn('Could not fetch seance details:', err)
              // Non-critical; continue anyway
            }
          })(),
          listPresences(seanceId, token),
        ])
        if (cancelled) return
        setPresences(presenceList)

        // 3. Initial whisper history (newest 50, reversed to oldest-first)
        const page = await getWhispers(seanceId, { limit: 50 }, token)
        if (cancelled) return
        const initial = [...page.items].reverse()
        setWhispers(initial)
        setNextBefore(page.next_before_id)

        setStatus('ready')
        setWsReady(true)
      } catch (err) {
        if (!cancelled) {
          console.error('Error initializing room:', err)
          setPageError(err instanceof ApiError ? err.message : 'Failed to join séance')
          setStatus('error')
        }
      }
    }

    void init()
    return () => { cancelled = true }
  }, [seanceId, token, clearToken])

  // ── Auto-scroll to bottom on new messages ────────────────────────────────

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [whispers.length])

  // ── WS message handler ───────────────────────────────────────────────────

  const handleWsMessage = useCallback((msg: WsMessage) => {
    switch (msg.op) {
      case 'whisper': {
        const w: WhisperResponse = {
          id: msg.id, seance_id: msg.seance_id,
          sigil: msg.sigil, content: msg.content, created_at: msg.created_at,
        }
        setWhispers(prev => mergeWhispers(prev, [w]))
        break
      }
      case 'enter':
        setPresences(prev => {
          if (prev.some(p => p.sigil === msg.sigil)) return prev
          return [...prev, { sigil: msg.sigil, role: 'attendant', entered_at: new Date().toISOString() }]
        })
        break
      case 'depart':
        setPresences(prev => prev.filter(p => p.sigil !== msg.sigil))
        break
      case 'dissolve':
        navigate('/lobby')
        break
    }
  }, [navigate])

  // ── Reconnect backfill ───────────────────────────────────────────────────

  const handleReconnect = useCallback(async (lastSeenId: number) => {
    if (!token) return
    try {
      const page = await getWhispers(seanceId, { limit: 50 }, token)
      if (!mountedRef.current) return
      const missed = page.items.filter(w => w.id > lastSeenId).reverse()
      if (missed.length > 0) setWhispers(prev => mergeWhispers(prev, missed))
    } catch { /* silently ignore */ }
  }, [seanceId, token])

  // ── Socket hook ──────────────────────────────────────────────────────────

  const { wsStatus, sendWhisper, setLastSeen } = useSeanceSocket({
    seanceId,
    token: token ?? '',
    enabled: wsReady,
    onMessage: handleWsMessage,
    onReconnect: handleReconnect,
  })

  // Sync lastSeen into the hook whenever whispers state changes
  useEffect(() => {
    if (whispers.length > 0) {
      setLastSeen(whispers[whispers.length - 1].id)
    }
  }, [whispers, setLastSeen])

  // ── Load older history ───────────────────────────────────────────────────

  const loadMore = async () => {
    if (!token || !nextBefore || loadingMore) return
    setLoadingMore(true)
    try {
      const page = await getWhispers(seanceId, { limit: 50, before_id: nextBefore }, token)
      const older = [...page.items].reverse()
      setWhispers(prev => mergeWhispers(older, prev))
      setNextBefore(page.next_before_id)
    } catch { /* ignore */ } finally {
      setLoadingMore(false)
    }
  }

  // ── Send ─────────────────────────────────────────────────────────────────

  const sendDraft = () => {
    const content = draft.trim()
    if (!content || wsStatus !== 'connected') return
    sendWhisper(content)
    setDraft('')
    textareaRef.current?.focus()
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendDraft()
    }
  }

  // ── Depart / dissolve ────────────────────────────────────────────────────

  const handleDepart = async () => {
    if (!token) return
    try { await departSeance(seanceId, token) } catch { /* ignore */ }
    navigate('/lobby')
  }

  const handleDissolve = async () => {
    if (!token) return
    if (!confirm('Dissolve this séance? This cannot be undone.')) return
    try { await dissolveSeance(seanceId, token) } catch { /* ignore */ }
    navigate('/lobby')
  }

  // ── Render guards ────────────────────────────────────────────────────────

  if (status === 'loading') {
    return (
      <div className="center-page">
        <div className="spinner" />
        <span>Stepping through the veil…</span>
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="center-page">
        <p className="error-msg">{pageError}</p>
        <button className="btn btn-ghost btn-sm" onClick={() => navigate('/lobby')}>
          ← Back to lobby
        </button>
      </div>
    )
  }

  const isWarden = myPresence?.role === 'warden'

  return (
    <div className="room-layout">
      {/* Header */}
      <header className="room-header">
        <button
          className="btn btn-ghost btn-sm"
          onClick={() => navigate('/lobby')}
          title="Back to lobby"
        >
          ←
        </button>
        <span className="room-header-title">{seanceName}</span>
        {myPresence && (
          <span className="room-header-sigil" title="Your sigil this session">
            {myPresence.sigil}
          </span>
        )}
        <span className={`ws-status ${wsStatus}`}>
          {wsStatus}
        </span>
        {isWarden ? (
          <button className="btn btn-danger btn-sm" onClick={handleDissolve}>
            Dissolve
          </button>
        ) : (
          <button className="btn btn-ghost btn-sm" onClick={handleDepart}>
            Depart
          </button>
        )}
      </header>

      {/* Body */}
      <div className="room-body">
        {/* Presence sidebar */}
        <aside className="presence-sidebar">
          <div className="presence-sidebar-title">Present</div>
          <div className="presence-list">
            {presences.map(p => (
              <div
                key={p.sigil}
                className={`presence-item${p.sigil === myPresence?.sigil ? ' is-me' : ''}`}
              >
                <span
                  className="presence-dot"
                  style={{ background: sigilColor(p.sigil) }}
                />
                <span className="presence-sigil" title={p.sigil}>
                  {p.sigil}
                </span>
                {p.role === 'warden' && (
                  <span className="presence-role">w</span>
                )}
              </div>
            ))}
          </div>
        </aside>

        {/* Feed + composer */}
        <div className="feed-column">
          <div className="feed-scroll">
            {nextBefore !== null && (
              <button
                className="load-more-btn"
                onClick={loadMore}
                disabled={loadingMore}
              >
                {loadingMore ? 'Loading…' : 'Load older messages'}
              </button>
            )}

            {whispers.length === 0 && (
              <p className="empty-state" style={{ marginTop: 40 }}>
                No whispers yet. Say something.
              </p>
            )}

            {whispers.map(w => (
              <div
                key={w.id}
                className={`whisper-row${w.sigil === myPresence?.sigil ? ' is-mine' : ''}`}
              >
                <div className="whisper-header">
                  <span
                    className="whisper-sigil"
                    style={{ color: sigilColor(w.sigil) }}
                  >
                    {w.sigil}
                  </span>
                  <span className="whisper-time">{formatTime(w.created_at)}</span>
                </div>
                <span className="whisper-content">{w.content}</span>
              </div>
            ))}

            <div ref={bottomRef} />
          </div>

          {/* Composer */}
          <div className="composer">
            <textarea
              ref={textareaRef}
              className="composer-input"
              placeholder={
                wsStatus === 'connected'
                  ? 'Whisper into the void… (Enter to send, Shift+Enter for newline)'
                  : wsStatus === 'reconnecting'
                  ? 'Reconnecting…'
                  : 'Connection lost'
              }
              value={draft}
              onChange={e => setDraft(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={wsStatus !== 'connected'}
              rows={1}
              maxLength={4000}
            />
            <button
              className="btn btn-primary"
              onClick={sendDraft}
              disabled={wsStatus !== 'connected' || !draft.trim()}
            >
              Send
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
