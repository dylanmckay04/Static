import {
  type KeyboardEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { departSeance, dissolveSeance, enterSeance, getMyPresence, getWhispers, listPresences } from '../api/seances'
import type { OwnPresenceResponse, PresenceResponse, WhisperResponse } from '../api/types'
import type { WsMessage } from '../api/types'
import { sigilSvgHtml } from '../lib/sigil'
import {
  isEnabled,
  playConnectionDrop,
  playMessageSent,
  playReconnected,
  playWhisperReceived,
  setEnabled as setSoundEnabled,
} from '../lib/sounds'
import { useToast } from '../components/Toast'
import { useSeanceSocket } from '../lib/useSeanceSocket'
import { useAuth } from '../store/auth'

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatTime(iso: string) {
  const d = new Date(iso)
  const now = new Date()
  const timeStr = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  if (d.toDateString() === now.toDateString()) return timeStr
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' + timeStr
}

function mergeWhispers(a: WhisperResponse[], b: WhisperResponse[]): WhisperResponse[] {
  const map = new Map<number, WhisperResponse>()
  for (const w of [...a, ...b]) map.set(w.id, w)
  return Array.from(map.values()).sort((x, y) => x.id - y.id)
}

function SigilSeal({ sigil, size = 28 }: { sigil: string; size?: number }) {
  return (
    <span
      className="presence-sigil-seal"
      dangerouslySetInnerHTML={{ __html: sigilSvgHtml(sigil, size) }}
    />
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

type PageStatus = 'loading' | 'ready' | 'error'

export default function RoomPage() {
  const { id }      = useParams<{ id: string }>()
  const seanceId    = Number(id)
  const { token, clearToken } = useAuth()
  const navigate    = useNavigate()
  const toast       = useToast()

  const [status,      setStatus]      = useState<PageStatus>('loading')
  const [pageError,   setPageError]   = useState<string | null>(null)
  const [seanceName,  setSeanceName]  = useState('')
  const [myPresence,  setMyPresence]  = useState<OwnPresenceResponse | null>(null)
  const [presences,   setPresences]   = useState<PresenceResponse[]>([])
  const [whispers,    setWhispers]    = useState<WhisperResponse[]>([])
  const [nextBefore,  setNextBefore]  = useState<number | null>(null)
  const [loadingMore, setLoadingMore] = useState(false)
  const [draft,       setDraft]       = useState('')
  const [wsReady,     setWsReady]     = useState(false)
  const [soundOn,     setSoundOn]     = useState(false)

  const bottomRef   = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const mountedRef  = useRef(true)
  const prevWsStatus = useRef<string>('')

  useEffect(() => { return () => { mountedRef.current = false } }, [])

  // ── Initial load ──────────────────────────────────────────────────────────

  useEffect(() => {
    if (!token) return
    let cancelled = false

    const init = async () => {
      try {
        let own: OwnPresenceResponse
        try {
          own = await enterSeance(seanceId, token)
        } catch (err) {
          if (err instanceof ApiError && err.status === 409) {
            own = await getMyPresence(seanceId, token)
          } else if (err instanceof ApiError && err.status === 401) {
            clearToken(); return
          } else {
            throw err
          }
        }
        if (cancelled) return
        setMyPresence(own)

        const [, presenceList] = await Promise.all([
          fetch(`http://localhost:8000/seances/${seanceId}`, {
            headers: { Authorization: `Bearer ${token}` },
          }).then(r => r.json()).then((d: { name: string }) => {
            if (!cancelled) setSeanceName(d.name)
          }),
          listPresences(seanceId, token),
        ])
        if (cancelled) return
        setPresences(presenceList)

        const page = await getWhispers(seanceId, { limit: 50 }, token)
        if (cancelled) return
        setWhispers([...page.items].reverse())
        setNextBefore(page.next_before_id)

        setStatus('ready')
        setWsReady(true)
      } catch (err) {
        if (!cancelled) {
          setPageError(err instanceof ApiError ? err.message : 'The séance could not be entered.')
          setStatus('error')
        }
      }
    }

    void init()
    return () => { cancelled = true }
  }, [seanceId, token, clearToken])

  // ── Auto-scroll ───────────────────────────────────────────────────────────

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [whispers.length])

  // ── WS message handler ────────────────────────────────────────────────────

  const handleWsMessage = useCallback((msg: WsMessage) => {
    switch (msg.op) {
      case 'whisper': {
        const w: WhisperResponse = {
          id: msg.id, seance_id: msg.seance_id,
          sigil: msg.sigil, content: msg.content, created_at: msg.created_at,
        }
        setWhispers(prev => mergeWhispers(prev, [w]))
        // Only play sound for others' whispers
        setMyPresence(me => {
          if (me && msg.sigil !== me.sigil) playWhisperReceived()
          return me
        })
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
        toast('The séance has been dissolved.', 'danger')
        setTimeout(() => navigate('/lobby'), 1200)
        break
    }
  }, [navigate, toast])

  // ── Reconnect backfill ────────────────────────────────────────────────────

  const handleReconnect = useCallback(async (lastSeenId: number) => {
    if (!token) return
    try {
      const page = await getWhispers(seanceId, { limit: 50 }, token)
      if (!mountedRef.current) return
      const missed = page.items.filter(w => w.id > lastSeenId).reverse()
      if (missed.length > 0) setWhispers(prev => mergeWhispers(prev, missed))
    } catch { /* silently ignore */ }
  }, [seanceId, token])

  // ── Socket hook ───────────────────────────────────────────────────────────

  const { wsStatus, sendWhisper, setLastSeen } = useSeanceSocket({
    seanceId,
    token: token ?? '',
    enabled: wsReady,
    onMessage: handleWsMessage,
    onReconnect: handleReconnect,
  })

  // ── WS status toasts ──────────────────────────────────────────────────────

  useEffect(() => {
    const prev = prevWsStatus.current
    prevWsStatus.current = wsStatus
    if (prev === wsStatus || prev === '') return
    if (wsStatus === 'reconnecting') {
      toast('The veil shudders… seeking the other side.', 'danger')
      playConnectionDrop()
    } else if (wsStatus === 'connected' && prev === 'reconnecting') {
      toast('The channel is open once more.', 'success')
      playReconnected()
    } else if (wsStatus === 'dead') {
      toast('Contact has been lost. Refresh to try again.', 'danger')
    }
  }, [wsStatus, toast])

  // ── Sync lastSeen ─────────────────────────────────────────────────────────

  useEffect(() => {
    if (whispers.length > 0) setLastSeen(whispers[whispers.length - 1].id)
  }, [whispers, setLastSeen])

  // ── Load older history ────────────────────────────────────────────────────

  const loadMore = async () => {
    if (!token || !nextBefore || loadingMore) return
    setLoadingMore(true)
    try {
      const page = await getWhispers(seanceId, { limit: 50, before_id: nextBefore }, token)
      setWhispers(prev => mergeWhispers([...page.items].reverse(), prev))
      setNextBefore(page.next_before_id)
    } catch { /* ignore */ } finally {
      setLoadingMore(false)
    }
  }

  // ── Send ──────────────────────────────────────────────────────────────────

  const sendDraft = () => {
    const content = draft.trim()
    if (!content || wsStatus !== 'connected') return
    sendWhisper(content)
    playMessageSent()
    setDraft('')
    textareaRef.current?.focus()
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendDraft() }
  }

  // ── Sound toggle ──────────────────────────────────────────────────────────

  const toggleSound = () => {
    const next = !soundOn
    setSoundOn(next)
    setSoundEnabled(next)
    toast(next ? 'The candles are lit.' : 'Silence descends.', 'accent')
  }

  // ── Depart / dissolve ─────────────────────────────────────────────────────

  const handleDepart = async () => {
    if (!token) return
    try { await departSeance(seanceId, token) } catch { /* ignore */ }
    navigate('/lobby')
  }

  const handleDissolve = async () => {
    if (!token) return
    if (!confirm('Dissolve this séance? The circle cannot be reopened.')) return
    try { await dissolveSeance(seanceId, token) } catch { /* ignore */ }
    navigate('/lobby')
  }

  // ── Render guards ─────────────────────────────────────────────────────────

  if (status === 'loading') {
    return (
      <div className="center-page">
        <div className="spinner" />
        <span>Lighting the candles…</span>
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="center-page">
        <p className="error-msg">{pageError}</p>
        <button className="btn btn-ghost btn-sm" onClick={() => navigate('/lobby')}>
          ← Return to the lobby
        </button>
      </div>
    )
  }

  const isWarden = myPresence?.role === 'warden'

  const composerPlaceholder =
    wsStatus === 'connected'    ? 'Whisper into the void… (Enter to send, Shift+Enter for newline)'
    : wsStatus === 'reconnecting' ? 'Seeking the other side…'
    : 'Contact has been lost'

  return (
    <div className="room-layout">
      {/* Header */}
      <header className="room-header">
        <button className="btn btn-ghost btn-sm" onClick={() => navigate('/lobby')} title="Return to lobby">
          ←
        </button>
        <span className="room-header-title">{seanceName}</span>
        {myPresence && (
          <span className="room-header-sigil" title="Your sigil this session">
            {myPresence.sigil}
          </span>
        )}
        <span className={`ws-status ${wsStatus}`}>{wsStatus}</span>
        <button
          className={`sound-toggle${soundOn ? ' active' : ''}`}
          onClick={toggleSound}
          title={soundOn ? 'Silence the candles' : 'Light the candles'}
        >
          {soundOn ? '🕯' : '🕯'}
        </button>
        {isWarden ? (
          <button className="btn btn-danger btn-sm" onClick={handleDissolve}>Dissolve</button>
        ) : (
          <button className="btn btn-ghost btn-sm" onClick={handleDepart}>Depart</button>
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
                <SigilSeal sigil={p.sigil} size={22} />
                <span className="presence-sigil" title={p.sigil}>{p.sigil}</span>
                {p.role === 'warden' && <span className="presence-role">w</span>}
              </div>
            ))}
          </div>
        </aside>

        {/* Feed + composer */}
        <div className="feed-column">
          <div className="feed-scroll">
            {nextBefore !== null && (
              <button className="load-more-btn" onClick={loadMore} disabled={loadingMore}>
                {loadingMore ? 'Reaching further back…' : 'Summon older whispers'}
              </button>
            )}

            {whispers.length === 0 && (
              <p className="empty-state" style={{ marginTop: 48 }}>
                The board is silent. Whisper first.
              </p>
            )}

            {whispers.map(w => (
              <div
                key={w.id}
                className={`whisper-row${w.sigil === myPresence?.sigil ? ' is-mine' : ''}`}
              >
                <div className="whisper-header">
                  <span className="whisper-sigil-seal">
                    <SigilSeal sigil={w.sigil} size={20} />
                  </span>
                  <span
                    className="whisper-sigil"
                    style={{ color: w.sigil === myPresence?.sigil ? 'var(--accent)' : 'var(--muted)' }}
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
              placeholder={composerPlaceholder}
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
