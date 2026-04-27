import {
  type KeyboardEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import {
  createInvite,
  departSeance,
  dissolveSeance,
  enterSeance,
  getMyPresence,
  getWhispers,
  kickBySigil,
  listPresences,
  redactWhisper,
  setRoleBySigil,
  transferWardenshipBySigil,
} from '../api/seances'
import type { OwnPresenceResponse, PresenceResponse, PresenceRole, WhisperResponse, WsMessage } from '../api/types'
import { sigilSvgHtml } from '../lib/sigil'
import {
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
  const [copying,     setCopying]     = useState(false)

  const bottomRef    = useRef<HTMLDivElement>(null)
  const textareaRef  = useRef<HTMLTextAreaElement>(null)
  const mountedRef   = useRef(true)
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

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [whispers.length])

  // ── WS message handler ────────────────────────────────────────────────────

  const handleWsMessage = useCallback((msg: WsMessage) => {
    switch (msg.op) {
      case 'whisper': {
        const w: WhisperResponse = {
          id: msg.id, seance_id: msg.seance_id,
          sigil: msg.sigil, content: msg.content,
          is_deleted: msg.is_deleted ?? false,
          created_at: msg.created_at,
        }
        setWhispers(prev => mergeWhispers(prev, [w]))
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
      case 'redact':
        setWhispers(prev => prev.map(w =>
          w.id === msg.whisper_id
            ? { ...w, is_deleted: true, content: '⸻ withdrawn ⸻' }
            : w
        ))
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
    } catch { /* ignore */ }
  }, [seanceId, token])

  // ── Socket ────────────────────────────────────────────────────────────────

  const { wsStatus, sendWhisper, setLastSeen } = useSeanceSocket({
    seanceId, token: token ?? '', enabled: wsReady,
    onMessage: handleWsMessage, onReconnect: handleReconnect,
  })

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

  useEffect(() => {
    if (whispers.length > 0) setLastSeen(whispers[whispers.length - 1].id)
  }, [whispers, setLastSeen])

  // ── Load older ────────────────────────────────────────────────────────────

  const loadMore = async () => {
    if (!token || !nextBefore || loadingMore) return
    setLoadingMore(true)
    try {
      const page = await getWhispers(seanceId, { limit: 50, before_id: nextBefore }, token)
      setWhispers(prev => mergeWhispers([...page.items].reverse(), prev))
      setNextBefore(page.next_before_id)
    } catch { /* ignore */ } finally { setLoadingMore(false) }
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

  // ── Moderation (all sigil-based — no seeker_id needed) ───────────────────

  const isWarden = myPresence?.role === 'warden'
  const isMod    = myPresence?.role === 'moderator'
  const canMod   = isWarden || isMod

  const handleKick = async (sigil: string) => {
    if (!token || !canMod) return
    try {
      await kickBySigil(seanceId, sigil, token)
      // WS depart broadcast will remove them from state; do it optimistically too
      setPresences(prev => prev.filter(p => p.sigil !== sigil))
      toast(`${sigil} has been removed.`, 'accent')
    } catch (err) {
      toast(err instanceof ApiError ? err.message : 'Kick failed.', 'danger')
    }
  }

  const handleTransfer = async (sigil: string) => {
    if (!token || !isWarden) return
    if (!confirm(`Transfer wardenship to ${sigil}?`)) return
    try {
      await transferWardenshipBySigil(seanceId, sigil, token)
      // Refresh presences to reflect the new roles
      const updated = await listPresences(seanceId, token)
      setPresences(updated)
      // Update our own presence role
      const ownUpdated = updated.find(p => p.sigil === myPresence?.sigil)
      if (ownUpdated) setMyPresence(prev => prev ? { ...prev, role: ownUpdated.role } : prev)
      toast('Wardenship transferred.', 'accent')
    } catch (err) {
      toast(err instanceof ApiError ? err.message : 'Transfer failed.', 'danger')
    }
  }

  const handleSetRole = async (sigil: string, role: PresenceRole) => {
    if (!token || !isWarden) return
    try {
      await setRoleBySigil(seanceId, sigil, role, token)
      setPresences(prev => prev.map(p => p.sigil === sigil ? { ...p, role } : p))
    } catch (err) {
      toast(err instanceof ApiError ? err.message : 'Role change failed.', 'danger')
    }
  }

  const handleRedact = async (whisperId: number) => {
    if (!token || !canMod) return
    try {
      await redactWhisper(seanceId, whisperId, token)
      setWhispers(prev => prev.map(w =>
        w.id === whisperId ? { ...w, is_deleted: true, content: '⸻ withdrawn ⸻' } : w
      ))
    } catch (err) {
      toast(err instanceof ApiError ? err.message : 'Redaction failed.', 'danger')
    }
  }

  const handleMintInvite = async () => {
    if (!token || !isWarden) return
    try {
      const inv = await createInvite(seanceId, token)
      const url = `${window.location.origin}/invite?token=${encodeURIComponent(inv.token)}`
      await navigator.clipboard.writeText(url)
      setCopying(true)
      toast('Invitation link copied to the clipboard.', 'accent')
      setTimeout(() => setCopying(false), 2000)
    } catch {
      toast('Could not generate an invitation.', 'danger')
    }
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

  const composerPlaceholder =
    wsStatus === 'connected'      ? 'Whisper into the void… (Enter to send, Shift+Enter for newline)'
    : wsStatus === 'reconnecting' ? 'Seeking the other side…'
    : 'Contact has been lost'

  return (
    <div className="room-layout">
      {/* Header */}
      <header className="room-header">
        <button className="btn btn-ghost btn-sm" onClick={() => navigate('/lobby')}>←</button>
        <span className="room-header-title">{seanceName}</span>
        {myPresence && (
          <span className="room-header-sigil" title="Your sigil this session">{myPresence.sigil}</span>
        )}
        <span className={`ws-status ${wsStatus}`}>{wsStatus}</span>
        <button
          className={`sound-toggle${soundOn ? ' active' : ''}`}
          onClick={toggleSound}
          title={soundOn ? 'Silence the candles' : 'Light the candles'}
        >🕯</button>
        {isWarden ? (
          <>
            <button className="btn btn-ghost btn-sm" onClick={handleMintInvite}>
              {copying ? 'Copied!' : 'Invite'}
            </button>
            <button className="btn btn-danger btn-sm" onClick={handleDissolve}>Dissolve</button>
          </>
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
            {presences.map(p => {
              const isMe = p.sigil === myPresence?.sigil
              const canTarget = canMod && !isMe && p.role !== 'warden'
              return (
                <div
                  key={p.sigil}
                  className={`presence-item${isMe ? ' is-me' : ''}`}
                >
                  <SigilSeal sigil={p.sigil} size={22} />
                  <span className="presence-sigil" title={p.sigil}>{p.sigil}</span>
                  {p.role === 'warden'    && <span className="presence-role" style={{ color: 'var(--accent)' }}>w</span>}
                  {p.role === 'moderator' && <span className="presence-role" style={{ color: 'var(--muted)' }}>m</span>}
                  {canTarget && (
                    <div className="presence-actions">
                      <button
                        className="presence-action-btn"
                        title="Remove from séance"
                        onClick={() => handleKick(p.sigil)}
                      >✕</button>
                      {isWarden && p.role === 'attendant' && (
                        <button
                          className="presence-action-btn"
                          title="Promote to moderator"
                          onClick={() => handleSetRole(p.sigil, 'moderator')}
                        >↑</button>
                      )}
                      {isWarden && p.role === 'moderator' && (
                        <button
                          className="presence-action-btn"
                          title="Demote to attendant"
                          onClick={() => handleSetRole(p.sigil, 'attendant')}
                        >↓</button>
                      )}
                      {isWarden && (
                        <button
                          className="presence-action-btn"
                          title="Transfer wardenship"
                          onClick={() => handleTransfer(p.sigil)}
                        >⇒</button>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
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
                className={`whisper-row${w.sigil === myPresence?.sigil ? ' is-mine' : ''}${w.is_deleted ? ' is-redacted' : ''}`}
              >
                <div className="whisper-header">
                  <SigilSeal sigil={w.sigil} size={20} />
                  <span
                    className="whisper-sigil"
                    style={{ color: w.sigil === myPresence?.sigil ? 'var(--accent)' : 'var(--muted)' }}
                  >
                    {w.sigil}
                  </span>
                  <span className="whisper-time">{formatTime(w.created_at)}</span>
                  {canMod && !w.is_deleted && (
                    <button
                      className="redact-btn"
                      onClick={() => handleRedact(w.id)}
                      title="Redact this whisper"
                    >✕</button>
                  )}
                </div>
                <span className={`whisper-content${w.is_deleted ? ' whisper-withdrawn' : ''}`}>
                  {w.content}
                </span>
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
            >Send</button>
          </div>
        </div>
      </div>
    </div>
  )
}
